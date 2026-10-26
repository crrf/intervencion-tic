"""Interrupciones: creacion, detalle, clasificacion y acciones."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.blueprints import _acciones
from app.extensions import db
from app.models.enums import CategoriaInterrupcion, Prioridad, RolUsuario
from app.models.interrupcion import Interrupcion
from app.security.decoradores import (
    aplicar_filtro,
    exigir_ver,
    filtro_interrupciones,
    rol_requerido,
)
from app.services import tickets as servicio
from app.services.estados import TransicionInvalida, transiciones_permitidas

bp = Blueprint("interrupciones", __name__, url_prefix="/interrupciones")


def _obtener(interrupcion_id: int) -> Interrupcion:
    inter = db.session.get(Interrupcion, interrupcion_id)
    if inter is None:
        abort(404)
    exigir_ver(inter)
    return inter


@bp.get("/")
@login_required
def listar():
    consulta = aplicar_filtro(select(Interrupcion), filtro_interrupciones())
    interrupciones = (
        db.session.execute(consulta.order_by(Interrupcion.creado_en.desc()).limit(200))
        .scalars()
        .unique()
        .all()
    )
    return render_template("interrupciones/listar.html", interrupciones=interrupciones)


def _crear_desde_formulario(categoria: CategoriaInterrupcion):
    """Parte comun de los dos formularios de creacion.

    Devuelve la respuesta de exito, o None si hubo un error (que ya quedo en
    un aviso) para que la vista vuelva a dibujar su propio formulario.
    """
    asignado = None
    valor = (request.form.get("asignado_a_id") or "").strip()
    if valor.isdigit():
        from app.models.usuario import Usuario

        asignado = db.session.get(Usuario, int(valor))
    try:
        inter = servicio.crear_interrupcion(
            current_user,
            identificador_externo=request.form.get("identificador_externo", ""),
            nombre_cliente=request.form.get("nombre_cliente", ""),
            telefono_contacto=request.form.get("telefono_contacto"),
            titulo=request.form.get("titulo", ""),
            descripcion=request.form.get("descripcion", ""),
            prioridad=request.form.get("prioridad", Prioridad.MEDIA.name),
            categoria=categoria,
            direccion=request.form.get("direccion"),
            foto=request.files.get("foto"),
            asignado_a=asignado,
        )
    except servicio.DatosInvalidos as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return None

    flash(f"Interrupcion {inter.folio} creada.", "ok")
    return redirect(inter.url_detalle)


@bp.route("/nueva", methods=["GET", "POST"])
@rol_requerido(RolUsuario.ADMIN, RolUsuario.DESPACHADOR)
def nueva():
    """Interrupcion del enlace de un cliente: la atiende un operador."""
    if request.method == "POST":
        respuesta = _crear_desde_formulario(CategoriaInterrupcion.ENLACE_CLIENTE)
        if respuesta is not None:
            return respuesta

    return render_template(
        "interrupciones/nueva.html",
        operadores=_acciones.operadores_activos(),
        datos=request.form,
    )


@bp.route("/nueva-wifi", methods=["GET", "POST"])
@rol_requerido(RolUsuario.ADMIN, RolUsuario.DESPACHADOR)
def nueva_wifi():
    """Interrupcion de un sitio wifi: la atiende un tecnico de wifi."""
    if request.method == "POST":
        respuesta = _crear_desde_formulario(CategoriaInterrupcion.SITIO_WIFI)
        if respuesta is not None:
            return respuesta

    return render_template(
        "interrupciones/nueva_wifi.html",
        tecnicos=_acciones.tecnicos_wifi_activos(),
        operadores=_acciones.operadores_activos(),
        datos=request.form,
    )


@bp.get("/<int:interrupcion_id>")
@login_required
def detalle(interrupcion_id: int):
    inter = _obtener(interrupcion_id)
    return render_template(
        "interrupciones/detalle.html",
        ticket=inter,
        transiciones=transiciones_permitidas(inter, current_user),
        eventos=servicio.linea_de_tiempo(inter),
        operadores=_acciones.destinatarios_para(inter),
        es_interrupcion=True,
        tipo_adjunto="interrupcion",
        id_kwarg="interrupcion_id",
        endpoint_foto="interrupciones.cambiar_foto",
        endpoint_mover="interrupciones.mover",
        endpoint_comentar="interrupciones.comentar",
        endpoint_reasignar="interrupciones.reasignar",
        endpoint_contacto="interrupciones.cambiar_contacto",
    )


@bp.post("/<int:interrupcion_id>/mover")
@login_required
def mover(interrupcion_id: int):
    return _acciones.mover(_obtener(interrupcion_id))


@bp.post("/<int:interrupcion_id>/comentar")
@login_required
def comentar(interrupcion_id: int):
    return _acciones.comentar(_obtener(interrupcion_id))


@bp.post("/<int:interrupcion_id>/reasignar")
@login_required
def reasignar(interrupcion_id: int):
    return _acciones.reasignar(_obtener(interrupcion_id))


@bp.post("/<int:interrupcion_id>/foto/<cual>")
@login_required
def cambiar_foto(interrupcion_id: int, cual: str):
    return _acciones.cambiar_foto(_obtener(interrupcion_id), cual)


@bp.post("/<int:interrupcion_id>/dependencia")
@login_required
def clasificar(interrupcion_id: int):
    """El operador fija la dependencia al diagnosticar (Core / Distribucion / Fisica)."""
    inter = _obtener(interrupcion_id)
    try:
        servicio.clasificar_dependencia(inter, current_user, request.form.get("dependencia"))
        flash("Dependencia actualizada.", "ok")
    except (servicio.DatosInvalidos, TransicionInvalida) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(inter.url_detalle)


@bp.post("/<int:interrupcion_id>/categoria")
@login_required
def cambiar_categoria(interrupcion_id: int):
    """El despachador corrige si es enlace de cliente o sitio wifi."""
    inter = _obtener(interrupcion_id)
    try:
        servicio.actualizar_categoria(inter, current_user, request.form.get("categoria"))
        flash("Categoria actualizada.", "ok")
    except (servicio.DatosInvalidos, TransicionInvalida) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(inter.url_detalle)


@bp.post("/<int:interrupcion_id>/contacto")
@login_required
def cambiar_contacto(interrupcion_id: int):
    return _acciones.cambiar_contacto(_obtener(interrupcion_id))
