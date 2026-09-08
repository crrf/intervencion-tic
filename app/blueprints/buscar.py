"""Busqueda avanzada de tickets (admin y despachador)."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template, request
from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models.enums import (
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
    RolUsuario,
    TipoTicket,
)
from app.models.usuario import Usuario, UsuarioRol
from app.security.decoradores import solo_gestion
from app.services import exportacion
from app.services.consultas import PRESETS, Filtros, buscar as ejecutar_busqueda, zona_app

bp = Blueprint("buscar", __name__, url_prefix="/buscar")


def _usuarios_por_rol(rol: RolUsuario) -> list[Usuario]:
    return list(
        db.session.execute(
            select(Usuario)
            .join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
            .where(UsuarioRol.rol == rol)
            .order_by(Usuario.nombre_completo)
        )
        .scalars()
        .unique()
        .all()
    )


def _catalogos() -> dict:
    return {
        "presets": PRESETS,
        "operadores": _usuarios_por_rol(RolUsuario.OPERADOR),
        "despachadores": _usuarios_por_rol(RolUsuario.DESPACHADOR),
        "agentes": _usuarios_por_rol(RolUsuario.AGENTE_FIBRA),
        "tipos": TipoTicket,
        "prioridades": Prioridad,
        "dependencias": Dependencia,
        "estados_fibra": EstadoFibra,
        "estados_orden": EstadoOrden,
        "estados_interrupcion": EstadoInterrupcion,
    }


@bp.get("/")
@solo_gestion
def index():
    filtros = Filtros.desde_request(request.args)
    pagina = max(1, int(request.args.get("pagina", 1) or 1))
    datos = ejecutar_busqueda(
        filtros, current_user, pagina=pagina, por_pagina=current_app.config["POR_PAGINA"]
    )
    contexto = {"filtros": filtros, "datos": datos, **_catalogos()}

    # Peticion HTMX: solo la tabla de resultados.
    if request.headers.get("HX-Request") == "true":
        return render_template("partials/_resultados.html", **contexto)
    return render_template("buscar/buscar.html", **contexto)


@bp.get("/csv")
@solo_gestion
def csv():
    filtros = Filtros.desde_request(request.args)
    # Se pasa el objeto real, no el proxy: el generador se consume despues.
    generador = exportacion.filas_tickets(filtros, current_user._get_current_object(), zona_app())
    return exportacion.respuesta_csv(generador, "tickets")
