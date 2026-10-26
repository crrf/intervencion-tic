"""Tablero kanban.

Una sola vista para los cuatro perfiles. Lo que cambia es *que* tickets trae
la consulta (filtro de visibilidad) y *que* transiciones habilita cada tarjeta
(union de los roles del usuario). El servidor siempre revalida: el atributo
`data-transiciones` del HTML es una ayuda para la interfaz, nunca la autoridad.
"""
from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from app.blueprints import _acciones
from app.extensions import db
from app.models.enums import (
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
    RolUsuario,
)
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo
from app.security.decoradores import (
    aplicar_filtro,
    exigir_ver,
    filtro_interrupciones,
    filtro_ordenes,
)
from app.services.estados import (
    TransicionInvalida,
    buscar_transicion,
    ejecutar_transicion,
    transiciones_permitidas,
)
from app.services.tickets import DatosInvalidos

bp = Blueprint("tablero", __name__)

TIPOS = {
    "ordenes": (OrdenTrabajo, EstadoOrden, filtro_ordenes),
    "interrupciones": (Interrupcion, EstadoInterrupcion, filtro_interrupciones),
}


def _tipo_inicial() -> str:
    """Con que pestana entra cada perfil.

    Quien no ve ordenes de trabajo (el tecnico de wifi) entra directo a las
    interrupciones, para no toparse con un tablero vacio.
    """
    if current_user.tiene_alguno(
        RolUsuario.ADMIN, RolUsuario.DESPACHADOR, RolUsuario.OPERADOR
    ):
        return "ordenes"
    return "interrupciones"


@bp.get("/")
@login_required
def inicio():
    # Quien solo atiende fibra entra directo a su bandeja.
    if current_user.roles == {RolUsuario.AGENTE_FIBRA}:
        return redirect(url_for("fibra.bandeja"))
    return redirect(url_for("tablero.ver"))


def _cargar(tipo: str, solo_mios: bool, prioridad: str):
    modelo, enum_estado, filtro = TIPOS[tipo]
    consulta = aplicar_filtro(select(modelo), filtro())
    if solo_mios:
        consulta = consulta.where(modelo.asignado_a_id == current_user.id)
    miembro_prioridad = Prioridad.desde_nombre(prioridad) if prioridad else None
    if miembro_prioridad:
        consulta = consulta.where(modelo.prioridad == miembro_prioridad)

    tickets = (
        db.session.execute(consulta.order_by(modelo.creado_en.desc()).limit(500))
        .scalars()
        .unique()
        .all()
    )

    columnas = []
    for estado in enum_estado:
        del_estado = [t for t in tickets if t.estado is estado]
        columnas.append(
            {
                "estado": estado,
                "tickets": del_estado,
                "total": len(del_estado),
            }
        )
    return columnas, len(tickets)


def _contexto(tipo: str, error: str | None = None) -> dict:
    solo_mios = request.args.get("mios") == "1"
    prioridad = (request.args.get("prioridad") or "").strip().upper()
    columnas, total = _cargar(tipo, solo_mios, prioridad)
    return {
        "tipo": tipo,
        "columnas": columnas,
        "total": total,
        "solo_mios": solo_mios,
        "prioridad": prioridad,
        "error": error,
        "transiciones_de": lambda t: transiciones_permitidas(t, current_user),
    }


@bp.get("/tablero")
@login_required
def ver():
    # El agente de fibra puro no tiene nada que hacer en este tablero.
    if current_user.roles == {RolUsuario.AGENTE_FIBRA}:
        return redirect(url_for("fibra.bandeja"))

    tipo = request.args.get("tipo", _tipo_inicial())
    if tipo not in TIPOS:
        tipo = _tipo_inicial()
    return render_template("tablero/tablero.html", **_contexto(tipo))


@bp.get("/tablero/columnas")
@login_required
def columnas():
    """Refresco parcial del tablero (polling HTMX)."""
    tipo = request.args.get("tipo", _tipo_inicial())
    if tipo not in TIPOS:
        abort(404)
    return render_template("partials/_tablero.html", **_contexto(tipo))


def _obtener(tipo: str, ticket_id: int):
    if tipo not in TIPOS:
        abort(404)
    modelo = TIPOS[tipo][0]
    ticket = db.session.get(modelo, ticket_id)
    if ticket is None:
        abort(404)
    exigir_ver(ticket)
    return ticket


@bp.get("/tablero/accion/<tipo>/<int:ticket_id>")
@login_required
def accion(tipo: str, ticket_id: int):
    """Devuelve el modal con los datos que exige una transicion."""
    ticket = _obtener(tipo, ticket_id)
    clave = (request.args.get("transicion") or "").strip()
    try:
        transicion = buscar_transicion(ticket, current_user, clave)
    except TransicionInvalida as exc:
        return render_template("partials/_modal_error.html", mensaje=str(exc)), 200

    return render_template(
        "partials/_modal_transicion.html",
        ticket=ticket,
        tipo=tipo,
        transicion=transicion,
        operadores=_acciones.destinatarios_para(ticket) if transicion.exige_asignado else [],
    )


@bp.post("/tablero/mover/<tipo>/<int:ticket_id>")
@login_required
def mover(tipo: str, ticket_id: int):
    """Aplica una transicion desde el tablero y redibuja las columnas."""
    ticket = _obtener(tipo, ticket_id)
    clave = (request.form.get("transicion") or "").strip()
    error = None

    asignado = None
    valor = (request.form.get("asignado_a_id") or "").strip()
    if valor.isdigit():
        from app.models.usuario import Usuario

        asignado = db.session.get(Usuario, int(valor))

    try:
        ejecutar_transicion(
            ticket,
            current_user,
            clave,
            comentario=request.form.get("comentario"),
            motivo=request.form.get("motivo"),
            dependencia=request.form.get("dependencia") or None,
            asignado_a=asignado,
            telefono_contacto=request.form.get("telefono_contacto"),
            direccion=request.form.get("direccion"),
        )
        db.session.commit()
    except (TransicionInvalida, DatosInvalidos) as exc:
        db.session.rollback()
        error = str(exc)

    return render_template("partials/_tablero.html", **_contexto(tipo, error=error))
