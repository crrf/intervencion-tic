"""Dashboard de desempeno (admin y despachador)."""
from __future__ import annotations

from flask import Blueprint, render_template, request
from flask_login import current_user

from app.security.decoradores import solo_gestion
from app.services import metricas
from app.services.consultas import PRESETS, resolver_rango

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.get("/")
@solo_gestion
def ver():
    inicio, fin, preset = resolver_rango(
        request.args.get("preset") or "30d",
        request.args.get("desde"),
        request.args.get("hasta"),
    )
    panel = metricas.panel_completo((inicio, fin), current_user)
    return render_template(
        "dashboard/dashboard.html",
        presets=PRESETS,
        preset=preset,
        inicio=inicio,
        fin=fin,
        desde=request.args.get("desde", ""),
        hasta=request.args.get("hasta", ""),
        **panel,
    )
