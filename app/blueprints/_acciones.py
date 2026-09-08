"""Acciones compartidas por las vistas de detalle de los dos tipos de ticket.

Ordenes e interrupciones son entidades distintas, pero mover un estado,
comentar, reasignar o reemplazar una foto se hace igual en ambas. Aqui vive
esa parte comun para no escribirla dos veces.
"""
from __future__ import annotations

from flask import flash, redirect, request
from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models.enums import RolUsuario
from app.models.usuario import Usuario, UsuarioRol
from app.services import tickets as servicio
from app.services.estados import TransicionInvalida, ejecutar_transicion


def operadores_activos() -> list[Usuario]:
    """Todos los operadores activos, incluidos los que ademas son despachadores."""
    return list(
        db.session.execute(
            select(Usuario)
            .join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
            .where(UsuarioRol.rol == RolUsuario.OPERADOR, Usuario.activo.is_(True))
            .order_by(Usuario.nombre_completo)
        )
        .scalars()
        .unique()
        .all()
    )


def _usuario_del_form(campo: str = "asignado_a_id") -> Usuario | None:
    valor = (request.form.get(campo) or "").strip()
    if not valor.isdigit():
        return None
    return db.session.get(Usuario, int(valor))


def mover(ticket):
    """Aplica una transicion desde la pantalla de detalle."""
    clave = (request.form.get("transicion") or "").strip()
    try:
        transicion = ejecutar_transicion(
            ticket,
            current_user,
            clave,
            comentario=request.form.get("comentario"),
            motivo=request.form.get("motivo"),
            dependencia=request.form.get("dependencia") or None,
            asignado_a=_usuario_del_form(),
            telefono_contacto=request.form.get("telefono_contacto"),
        )
        db.session.commit()
        flash(f"{ticket.folio}: {transicion.etiqueta.lower()}.", "ok")
    except TransicionInvalida as exc:
        db.session.rollback()
        flash(str(exc), "error")
    except servicio.DatosInvalidos as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(ticket.url_detalle)


def comentar(ticket):
    try:
        servicio.comentar(ticket, current_user, request.form.get("texto"))
        flash("Comentario agregado.", "ok")
    except servicio.DatosInvalidos as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(ticket.url_detalle)


def reasignar(ticket):
    try:
        servicio.reasignar(ticket, current_user, _usuario_del_form("nuevo_operador_id"))
        flash("Ticket reasignado.", "ok")
    except TransicionInvalida as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(ticket.url_detalle)


def cambiar_telefono(ticket):
    """Completa o corrige el telefono de contacto despues de crear el ticket."""
    try:
        servicio.actualizar_telefono(
            ticket, current_user, request.form.get("telefono_contacto")
        )
        flash("Telefono de contacto actualizado.", "ok")
    except servicio.DatosInvalidos as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(ticket.url_detalle)


def cambiar_foto(ticket, cual: str):
    if not current_user.tiene_alguno(RolUsuario.ADMIN, RolUsuario.DESPACHADOR):
        flash("Solo el despachador o un administrador puede cambiar las fotos.", "error")
        return redirect(ticket.url_detalle)
    try:
        servicio.reemplazar_foto(ticket, current_user, cual, request.files.get("foto"))
        flash("Foto actualizada.", "ok")
    except servicio.DatosInvalidos as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(ticket.url_detalle)
