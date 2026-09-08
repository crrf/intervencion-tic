"""Operaciones sobre cuentas de usuario que no son simple CRUD."""
from __future__ import annotations

import logging
import secrets

from app.extensions import db
from app.models.enums import RolUsuario

log = logging.getLogger(__name__)

LARGO_MINIMO = 8

#: Alfabeto sin caracteres que se confunden al dictarlos por radio o telefono
#: (0/O, 1/l/I). Los tecnicos reciben la clave de viva voz.
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


class ErrorUsuario(Exception):
    """La operacion sobre la cuenta no se puede realizar."""


def generar_password(grupos: int = 3, largo_grupo: int = 4) -> str:
    """Genera una clave temporal legible: por ejemplo `Kzr7-Xm4Q-9Tvb`."""
    partes = [
        "".join(secrets.choice(_ALFABETO) for _ in range(largo_grupo)) for _ in range(grupos)
    ]
    return "-".join(partes)


def validar_password(password: str) -> None:
    if len(password or "") < LARGO_MINIMO:
        raise ErrorUsuario(f"La contrasena debe tener al menos {LARGO_MINIMO} caracteres.")


def restablecer_password(usuario, admin, password: str | None = None) -> str:
    """Asigna una contrasena nueva a `usuario`. Solo la puede ejecutar un admin.

    Si no se indica ninguna, se genera una temporal. Devuelve la contrasena en
    claro para mostrarsela UNA vez al administrador; nunca se vuelve a poder
    consultar porque solo se guarda su hash.

    Al restablecerle la clave a otra persona se marca `debe_cambiar_password`:
    el administrador conoce esa clave, asi que el titular debe reemplazarla en
    su proximo ingreso. Cuando un admin cambia la suya propia no se marca.
    """
    if not admin.tiene_rol(RolUsuario.ADMIN):
        raise ErrorUsuario("Solo un administrador puede restablecer contrasenas.")
    if usuario is None:
        raise ErrorUsuario("El usuario no existe.")

    generada = not password
    if generada:
        password = generar_password()
    else:
        validar_password(password)

    usuario.set_password(password)
    usuario.debe_cambiar_password = usuario.id != admin.id
    db.session.commit()

    # Queda constancia en el log de la aplicacion: quien y a quien, nunca la clave.
    log.warning(
        "restablecimiento de contrasena: admin=%s (id=%s) -> usuario=%s (id=%s), generada=%s",
        admin.usuario, admin.id, usuario.usuario, usuario.id, generada,
    )
    return password


def cambiar_password_propia(usuario, actual: str | None, nueva: str, repetir: str) -> None:
    """Cambio de contrasena por el propio titular.

    Si viene de un restablecimiento (`debe_cambiar_password`) no se pide la
    actual: el administrador se la fijo y el titular puede tener ya una sesion
    abierta con la clave vieja.
    """
    if not usuario.debe_cambiar_password:
        if not usuario.check_password(actual or ""):
            raise ErrorUsuario("La contrasena actual no es correcta.")

    validar_password(nueva)
    if nueva != repetir:
        raise ErrorUsuario("Las contrasenas nuevas no coinciden.")
    if usuario.check_password(nueva):
        raise ErrorUsuario("La contrasena nueva debe ser distinta de la anterior.")

    usuario.set_password(nueva)
    usuario.debe_cambiar_password = False
    db.session.commit()
