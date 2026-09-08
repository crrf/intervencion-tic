"""Reportes: historico por periodo y bitacora de auditoria."""
from __future__ import annotations

from flask import Blueprint, render_template, request
from flask_login import current_user
from sqlalchemy import select

from app.extensions import db
from app.models.usuario import Usuario
from app.security.decoradores import solo_gestion
from app.services import auditoria, exportacion
from app.services.consultas import (
    PRESETS,
    Filtros,
    buscar as ejecutar_busqueda,
    resolver_rango,
    zona_app,
)

bp = Blueprint("reportes", __name__, url_prefix="/reportes")


def _usuarios() -> list[Usuario]:
    return list(
        db.session.execute(select(Usuario).order_by(Usuario.nombre_completo))
        .scalars()
        .unique()
        .all()
    )


def _rango_del_request():
    preset = request.args.get("preset") or "30d"
    return resolver_rango(preset, request.args.get("desde"), request.args.get("hasta"))


# ---------------------------------------------------------------------------
# Historico por periodo
# ---------------------------------------------------------------------------
def _filtros_historico() -> Filtros:
    # to_dict() y no dict(): un MultiDict copiado con dict() deja listas como valores.
    args = request.args.to_dict()
    args.setdefault("preset", "30d")
    filtros = Filtros.desde_request(args)
    if not filtros.rango:
        filtros.rango = resolver_rango(filtros.preset or "30d", filtros.desde, filtros.hasta)[:2]
    return filtros


@bp.get("/historico")
@solo_gestion
def historico():
    filtros = _filtros_historico()
    pagina = max(1, int(request.args.get("pagina", 1) or 1))
    datos = ejecutar_busqueda(filtros, current_user, pagina=pagina, por_pagina=50)
    inicio, fin, preset = resolver_rango(filtros.preset, filtros.desde, filtros.hasta)

    resumen = {
        "total": datos["total"],
        "cerrados": sum(1 for f in datos["filas"] if f["cerrado_en"]),
        "abiertos": sum(1 for f in datos["filas"] if not f["cerrado_en"]),
    }
    contexto = {
        "filtros": filtros,
        "datos": datos,
        "presets": PRESETS,
        "preset": preset,
        "inicio": inicio,
        "fin": fin,
        "resumen": resumen,
    }
    if request.headers.get("HX-Request") == "true":
        return render_template("partials/_historico.html", **contexto)
    return render_template("reportes/historico.html", **contexto)


@bp.get("/historico/csv")
@solo_gestion
def historico_csv():
    filtros = _filtros_historico()
    # Se pasa el objeto real, no el proxy: el generador se consume despues.
    generador = exportacion.filas_tickets(filtros, current_user._get_current_object(), zona_app())
    return exportacion.respuesta_csv(generador, "historico")


# ---------------------------------------------------------------------------
# Bitacora de auditoria
# ---------------------------------------------------------------------------
def _parametros_auditoria() -> dict:
    valor = (request.args.get("usuario_id") or "").strip()
    clase = (request.args.get("clase") or "").strip()
    return {
        "usuario_id": int(valor) if valor.isdigit() else None,
        "folio": (request.args.get("folio") or "").strip() or None,
        "clase": clase if clase in {"cambio", "comentario"} else None,
    }


@bp.get("/auditoria")
@solo_gestion
def bitacora():
    inicio, fin, preset = _rango_del_request()
    parametros = _parametros_auditoria()
    pagina = max(1, int(request.args.get("pagina", 1) or 1))
    datos = auditoria.listar((inicio, fin), current_user, pagina=pagina, **parametros)

    contexto = {
        "datos": datos,
        "presets": PRESETS,
        "preset": preset,
        "inicio": inicio,
        "fin": fin,
        "usuarios": _usuarios(),
        "parametros": parametros,
        "args": request.args,
    }
    if request.headers.get("HX-Request") == "true":
        return render_template("partials/_auditoria.html", **contexto)
    return render_template("reportes/auditoria.html", **contexto)


@bp.get("/auditoria/csv")
@solo_gestion
def bitacora_csv():
    inicio, fin, _ = _rango_del_request()
    eventos = auditoria.iterar_todo(
        (inicio, fin), current_user._get_current_object(), **_parametros_auditoria()
    )
    generador = exportacion.filas_auditoria(eventos, zona_app())
    return exportacion.respuesta_csv(generador, "auditoria")
