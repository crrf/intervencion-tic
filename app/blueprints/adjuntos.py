"""Entrega de las fotos guardadas en Garage.

La ruta comprueba el permiso sobre el ticket y redirige a una URL prefirmada
de corta duracion. El bucket permanece privado: nadie llega a un objeto sin
pasar antes por esta verificacion.
"""
from __future__ import annotations

from flask import Blueprint, abort, redirect
from flask_login import login_required

from app.extensions import db
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo
from app.security.decoradores import exigir_ver
from app.services import storage

bp = Blueprint("adjuntos", __name__, url_prefix="/adjuntos")

MODELOS = {"orden": OrdenTrabajo, "interrupcion": Interrupcion}


@bp.get("/<tipo>/<int:ticket_id>/<cual>")
@login_required
def ver(tipo: str, ticket_id: int, cual: str):
    modelo = MODELOS.get(tipo)
    if modelo is None:
        abort(404)

    ticket = db.session.get(modelo, ticket_id)
    if ticket is None:
        abort(404)
    exigir_ver(ticket)

    if cual not in ticket.FOTOS:
        abort(404)
    clave = ticket.clave_foto(cual)
    if not clave:
        abort(404)

    url = storage.url_prefirmada(clave)
    if not url:
        abort(503)
    return redirect(url)
