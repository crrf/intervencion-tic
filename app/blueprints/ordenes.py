"""Ordenes de trabajo: creacion, detalle y acciones."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import select

from app.blueprints import _acciones
from app.extensions import db
from app.models.enums import Prioridad, RolUsuario
from app.models.orden import OrdenTrabajo
from app.security.decoradores import aplicar_filtro, exigir_ver, filtro_ordenes, rol_requerido
from app.services import tickets as servicio
from app.services.estados import transiciones_permitidas

bp = Blueprint("ordenes", __name__, url_prefix="/ordenes")


def _obtener(orden_id: int) -> OrdenTrabajo:
    orden = db.session.get(OrdenTrabajo, orden_id)
    if orden is None:
        abort(404)
    exigir_ver(orden)
    return orden


@bp.get("/")
@login_required
def listar():
    consulta = aplicar_filtro(select(OrdenTrabajo), filtro_ordenes())
    ordenes = (
        db.session.execute(consulta.order_by(OrdenTrabajo.creado_en.desc()).limit(200))
        .scalars()
        .unique()
        .all()
    )
    return render_template("ordenes/listar.html", ordenes=ordenes)


@bp.route("/nueva", methods=["GET", "POST"])
@rol_requerido(RolUsuario.ADMIN, RolUsuario.DESPACHADOR)
def nueva():
    operadores = _acciones.operadores_activos()

    if request.method == "POST":
        asignado = None
        valor = (request.form.get("asignado_a_id") or "").strip()
        if valor.isdigit():
            from app.models.usuario import Usuario

            asignado = db.session.get(Usuario, int(valor))
        try:
            orden = servicio.crear_orden(
                current_user,
                identificador_externo=request.form.get("identificador_externo", ""),
                nombre_cliente=request.form.get("nombre_cliente", ""),
                telefono_contacto=request.form.get("telefono_contacto"),
                titulo=request.form.get("titulo", ""),
                descripcion=request.form.get("descripcion", ""),
                prioridad=request.form.get("prioridad", Prioridad.MEDIA.name),
                direccion=request.form.get("direccion"),
                foto_anverso=request.files.get("foto_anverso"),
                foto_reverso=request.files.get("foto_reverso"),
                asignado_a=asignado,
            )
            flash(f"Orden {orden.folio} creada.", "ok")
            return redirect(orden.url_detalle)
        except servicio.DatosInvalidos as exc:
            db.session.rollback()
            flash(str(exc), "error")

    return render_template(
        "ordenes/nueva.html", operadores=operadores, datos=request.form
    )


@bp.get("/<int:orden_id>")
@login_required
def detalle(orden_id: int):
    orden = _obtener(orden_id)
    return render_template(
        "ordenes/detalle.html",
        ticket=orden,
        transiciones=transiciones_permitidas(orden, current_user),
        eventos=servicio.linea_de_tiempo(orden),
        operadores=_acciones.operadores_activos(),
        # La plantilla de detalle es compartida; estos valores le dicen a que
        # entidad pertenece el ticket que esta mostrando.
        es_interrupcion=False,
        tipo_adjunto="orden",
        id_kwarg="orden_id",
        endpoint_foto="ordenes.cambiar_foto",
        endpoint_mover="ordenes.mover",
        endpoint_comentar="ordenes.comentar",
        endpoint_reasignar="ordenes.reasignar",
        endpoint_contacto="ordenes.cambiar_contacto",
    )


@bp.post("/<int:orden_id>/mover")
@login_required
def mover(orden_id: int):
    return _acciones.mover(_obtener(orden_id))


@bp.post("/<int:orden_id>/comentar")
@login_required
def comentar(orden_id: int):
    return _acciones.comentar(_obtener(orden_id))


@bp.post("/<int:orden_id>/reasignar")
@login_required
def reasignar(orden_id: int):
    return _acciones.reasignar(_obtener(orden_id))


@bp.post("/<int:orden_id>/foto/<cual>")
@login_required
def cambiar_foto(orden_id: int, cual: str):
    return _acciones.cambiar_foto(_obtener(orden_id), cual)




@bp.post("/<int:orden_id>/contacto")
@login_required
def cambiar_contacto(orden_id: int):
    return _acciones.cambiar_contacto(_obtener(orden_id))
