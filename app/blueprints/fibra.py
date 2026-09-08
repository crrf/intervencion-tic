"""Bandeja del agente de fibra.

Solo ve interrupciones derivadas a capa fisica y solo mueve la columna
`estado_fibra`. No crea, no asigna, no cierra y no ve ordenes de trabajo:
eso lo garantiza `filtro_interrupciones` mas la maquina de estados.

La bandeja esta pensada para cuando se acumula trabajo: trae busqueda,
filtros, ordenamiento y la posibilidad de ampliar una columna para revisar de
una sola vez todo lo que hay en ella.
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template, request
from flask_login import current_user
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.enums import EstadoFibra, EstadoInterrupcion, Prioridad, RolUsuario
from app.models.interrupcion import Interrupcion
from app.security.decoradores import exigir_ver, rol_requerido
from app.services.estados import (
    TransicionInvalida,
    buscar_transicion,
    ejecutar_transicion,
    transiciones_permitidas,
)
from app.services.tickets import DatosInvalidos

bp = Blueprint("fibra", __name__, url_prefix="/fibra")

ACCESO = (RolUsuario.AGENTE_FIBRA, RolUsuario.ADMIN)

ORDENES = {
    "antiguas": "Mas tiempo esperando",
    "recientes": "Derivadas hace poco",
    "prioridad": "Prioridad",
    "cliente": "Cliente (A-Z)",
}

#: A partir de aqui una interrupcion sin respuesta se marca como demorada.
MINUTOS_DEMORA = 240


def _consulta(q: str, prioridad: str, orden: str):
    consulta = (
        select(Interrupcion)
        .where(Interrupcion.estado == EstadoInterrupcion.DERIVADA_FIBRA)
        .options(selectinload(Interrupcion.comentarios))
    )

    if q:
        patron = f"%{q}%"
        consulta = consulta.where(
            or_(
                Interrupcion.folio.ilike(patron),
                Interrupcion.identificador_externo.ilike(patron),
                Interrupcion.nombre_cliente.ilike(patron),
                Interrupcion.telefono_contacto.ilike(patron),
                Interrupcion.titulo.ilike(patron),
                Interrupcion.descripcion.ilike(patron),
            )
        )

    miembro = Prioridad.desde_nombre(prioridad) if prioridad else None
    if miembro:
        consulta = consulta.where(Interrupcion.prioridad == miembro)

    if orden == "recientes":
        consulta = consulta.order_by(Interrupcion.derivado_fibra_en.desc().nullslast())
    elif orden == "prioridad":
        # El enum se declara de menor a mayor, asi que desc() deja Critica arriba.
        consulta = consulta.order_by(
            Interrupcion.prioridad.desc(), Interrupcion.derivado_fibra_en.asc().nullslast()
        )
    elif orden == "cliente":
        consulta = consulta.order_by(Interrupcion.nombre_cliente.asc())
    else:
        consulta = consulta.order_by(Interrupcion.derivado_fibra_en.asc().nullslast())

    return consulta


def _contexto(error: str | None = None) -> dict:
    q = (request.args.get("q") or "").strip()
    prioridad = (request.args.get("prioridad") or "").strip().upper()
    orden = request.args.get("orden") or "antiguas"
    if orden not in ORDENES:
        orden = "antiguas"
    ampliada = (request.args.get("ampliada") or "").strip().upper()
    if ampliada not in EstadoFibra.__members__:
        ampliada = ""

    interrupciones = (
        db.session.execute(_consulta(q, prioridad, orden)).scalars().unique().all()
    )

    columnas = []
    for estado in EstadoFibra:
        del_estado = [
            i for i in interrupciones if (i.estado_fibra or EstadoFibra.EN_REVISION) is estado
        ]
        columnas.append(
            {
                "estado": estado,
                "tickets": del_estado,
                "total": len(del_estado),
                "ampliada": ampliada == estado.name,
                "reducida": bool(ampliada) and ampliada != estado.name,
            }
        )

    # Cuantas llevan demasiado tiempo sin que nadie las revise.
    demoradas = sum(
        1
        for i in interrupciones
        if (i.estado_fibra or EstadoFibra.EN_REVISION) is EstadoFibra.EN_REVISION
        and (i.minutos_en_fibra or 0) >= MINUTOS_DEMORA
    )

    # Se arrastran los filtros vigentes a cada URL para que el refresco
    # automatico y los enlaces de ampliar no los pierdan.
    args = {k: v for k, v in request.args.items(multi=False) if v}

    return {
        "columnas": columnas,
        "total": len(interrupciones),
        "q": q,
        "prioridad": prioridad,
        "orden": orden,
        "ordenes": ORDENES,
        "ampliada": ampliada,
        "demoradas": demoradas,
        "minutos_demora": MINUTOS_DEMORA,
        "args": args,
        "error": error,
        "transiciones_de": lambda t: [
            tr for tr in transiciones_permitidas(t, current_user) if tr.campo == "estado_fibra"
        ],
    }


@bp.get("/")
@rol_requerido(*ACCESO)
def bandeja():
    return render_template("fibra/bandeja.html", **_contexto())


@bp.get("/columnas")
@rol_requerido(*ACCESO)
def columnas():
    return render_template("partials/_tablero_fibra.html", **_contexto())


def _obtener(interrupcion_id: int) -> Interrupcion:
    inter = db.session.get(Interrupcion, interrupcion_id)
    if inter is None:
        abort(404)
    exigir_ver(inter)
    return inter


@bp.get("/accion/<int:interrupcion_id>")
@rol_requerido(*ACCESO)
def accion(interrupcion_id: int):
    inter = _obtener(interrupcion_id)
    clave = (request.args.get("transicion") or "").strip()
    try:
        transicion = buscar_transicion(inter, current_user, clave)
    except TransicionInvalida as exc:
        return render_template("partials/_modal_error.html", mensaje=str(exc)), 200
    if transicion.campo != "estado_fibra":
        abort(403)
    return render_template(
        "partials/_modal_transicion.html",
        ticket=inter,
        tipo="fibra",
        transicion=transicion,
        operadores=[],
    )


@bp.post("/mover/<int:interrupcion_id>")
@rol_requerido(*ACCESO)
def mover(interrupcion_id: int):
    inter = _obtener(interrupcion_id)
    clave = (request.form.get("transicion") or "").strip()
    error = None
    try:
        if not clave.startswith("estado_fibra:"):
            raise TransicionInvalida("Desde esta bandeja solo se cambia el estado de la fibra.")
        ejecutar_transicion(
            inter, current_user, clave, comentario=request.form.get("comentario")
        )
        db.session.commit()
    except (TransicionInvalida, DatosInvalidos) as exc:
        db.session.rollback()
        error = str(exc)
    return render_template("partials/_tablero_fibra.html", **_contexto(error=error))
