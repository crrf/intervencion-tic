"""Campana de notificaciones (parciales HTMX)."""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services import notificaciones as servicio

bp = Blueprint("notificaciones", __name__, url_prefix="/notificaciones")


@bp.get("/badge")
@login_required
def badge():
    """Solo el contador: es lo que refresca el polling de la barra superior."""
    return render_template(
        "partials/_badge.html", total=servicio.contar_no_leidas(current_user.id)
    )


@bp.get("/panel")
@login_required
def panel():
    return render_template(
        "partials/_notificaciones.html",
        notificaciones=servicio.listar(current_user.id),
        total=servicio.contar_no_leidas(current_user.id),
    )


@bp.post("/leer-todas")
@login_required
def leer_todas():
    servicio.marcar_todas_leidas(current_user.id)
    return render_template(
        "partials/_notificaciones.html",
        notificaciones=servicio.listar(current_user.id),
        total=0,
    )


@bp.get("/abrir/<int:notificacion_id>")
@login_required
def abrir(notificacion_id: int):
    servicio.marcar_leida(notificacion_id, current_user.id)
    destino = request.args.get("url") or url_for("tablero.inicio")
    if not destino.startswith("/"):
        destino = url_for("tablero.inicio")
    return redirect(destino)
