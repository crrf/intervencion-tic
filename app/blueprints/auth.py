"""Inicio de sesion, cierre y cambio de contrasena."""
from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from app.extensions import db, limiter
from app.models.usuario import Usuario
from app.services import usuarios as servicio

bp = Blueprint("auth", __name__)


def _destino_seguro(destino: str | None) -> str:
    """Evita redirecciones abiertas: solo se aceptan rutas internas."""
    if not destino:
        return url_for("tablero.inicio")
    partes = urlparse(destino)
    if partes.scheme or partes.netloc or not destino.startswith("/"):
        return url_for("tablero.inicio")
    return destino


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("tablero.inicio"))

    if request.method == "POST":
        nombre = (request.form.get("usuario") or "").strip()
        password = request.form.get("password") or ""
        usuario = db.session.execute(
            select(Usuario).where(Usuario.usuario == nombre)
        ).scalar_one_or_none()

        if usuario is None or not usuario.check_password(password):
            # Mismo mensaje en ambos casos: no se revela si el usuario existe.
            flash("Usuario o contrasena incorrectos.", "error")
            return render_template("login.html", usuario=nombre), 401
        if not usuario.activo:
            flash("Tu cuenta esta desactivada. Contacta al administrador.", "error")
            return render_template("login.html", usuario=nombre), 403
        if not usuario.roles:
            flash("Tu cuenta no tiene ningun rol asignado.", "error")
            return render_template("login.html", usuario=nombre), 403

        login_user(usuario, remember=bool(request.form.get("recordarme")))
        return redirect(_destino_seguro(request.args.get("next")))

    return render_template("login.html", usuario="")


@bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesion cerrada.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/mi-cuenta", methods=["GET", "POST"])
@login_required
def cuenta():
    if request.method == "POST":
        try:
            servicio.cambiar_password_propia(
                current_user,
                request.form.get("actual"),
                request.form.get("nueva") or "",
                request.form.get("repetir") or "",
            )
            flash("Contrasena actualizada.", "ok")
            return redirect(url_for("tablero.inicio"))
        except servicio.ErrorUsuario as exc:
            db.session.rollback()
            flash(str(exc), "error")

    return render_template("cuenta.html")
