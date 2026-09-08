"""Autorizacion: decoradores de rol y filtros de visibilidad.

Regla de oro: la visibilidad se resuelve EN LA CONSULTA, no en la plantilla.
Nunca se cargan todos los tickets para despues esconder unos cuantos en Jinja.

Los permisos son la UNION de los que aportan los roles del usuario: quien es
despachador y operador a la vez ve todo (por despachador) y ademas puede
trabajar lo que tiene asignado (por operador).
"""
from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user
from sqlalchemy import false, or_

from app.models.enums import EstadoInterrupcion, RolUsuario
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo


# ---------------------------------------------------------------------------
# Decoradores
# ---------------------------------------------------------------------------
def rol_requerido(*roles: RolUsuario):
    """Exige al menos uno de los roles indicados (interseccion no vacia)."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Inicia sesion para continuar.", "aviso")
                return redirect(url_for("auth.login", next=request.full_path))
            if not current_user.tiene_alguno(*roles):
                abort(403)
            return vista(*args, **kwargs)

        return envoltura

    return decorador


def solo_gestion(vista):
    """Busqueda, reportes y dashboard: exclusivos de admin y despachador."""
    return rol_requerido(RolUsuario.ADMIN, RolUsuario.DESPACHADOR)(vista)


# ---------------------------------------------------------------------------
# Visibilidad de un ticket concreto
# ---------------------------------------------------------------------------
def puede_ver(ticket, usuario=None) -> bool:
    usuario = usuario or current_user
    if not getattr(usuario, "is_authenticated", False):
        return False
    if usuario.tiene_alguno(RolUsuario.ADMIN, RolUsuario.DESPACHADOR):
        return True
    if usuario.tiene_rol(RolUsuario.OPERADOR) and ticket.asignado_a_id == usuario.id:
        return True
    if (
        usuario.tiene_rol(RolUsuario.AGENTE_FIBRA)
        and isinstance(ticket, Interrupcion)
        and ticket.estado is EstadoInterrupcion.DERIVADA_FIBRA
    ):
        return True
    return False


def exigir_ver(ticket, usuario=None) -> None:
    if not puede_ver(ticket, usuario):
        abort(403)


def puede_gestionar(usuario=None) -> bool:
    usuario = usuario or current_user
    return getattr(usuario, "is_authenticated", False) and usuario.tiene_alguno(
        RolUsuario.ADMIN, RolUsuario.DESPACHADOR
    )


def puede_crear(usuario=None) -> bool:
    return puede_gestionar(usuario)


# ---------------------------------------------------------------------------
# Filtros de visibilidad para las consultas
# ---------------------------------------------------------------------------
def filtro_ordenes(usuario=None):
    """Condicion SQL que limita las ordenes visibles para el usuario."""
    usuario = usuario or current_user
    if not getattr(usuario, "is_authenticated", False):
        return false()
    if usuario.tiene_alguno(RolUsuario.ADMIN, RolUsuario.DESPACHADOR):
        return None  # sin restriccion
    if usuario.tiene_rol(RolUsuario.OPERADOR):
        return OrdenTrabajo.asignado_a_id == usuario.id
    # El agente de fibra no ve ordenes de trabajo en absoluto.
    return false()


def filtro_interrupciones(usuario=None):
    """Condicion SQL que limita las interrupciones visibles para el usuario."""
    usuario = usuario or current_user
    if not getattr(usuario, "is_authenticated", False):
        return false()
    if usuario.tiene_alguno(RolUsuario.ADMIN, RolUsuario.DESPACHADOR):
        return None

    condiciones = []
    if usuario.tiene_rol(RolUsuario.OPERADOR):
        condiciones.append(Interrupcion.asignado_a_id == usuario.id)
    if usuario.tiene_rol(RolUsuario.AGENTE_FIBRA):
        condiciones.append(Interrupcion.estado == EstadoInterrupcion.DERIVADA_FIBRA)

    if not condiciones:
        return false()
    return condiciones[0] if len(condiciones) == 1 else or_(*condiciones)


def aplicar_filtro(consulta, condicion):
    return consulta if condicion is None else consulta.where(condicion)
