"""Notificaciones in-app.

No hacen commit: se suman a la transaccion que las origina para que un fallo
posterior no deje avisos de un cambio que nunca ocurrio.
"""
from __future__ import annotations

from sqlalchemy import select, update

from app.extensions import db
from app.models.enums import RolUsuario
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario, UsuarioRol


def crear(usuario_id: int, titulo: str, mensaje: str = "", url: str | None = None) -> None:
    db.session.add(
        Notificacion(usuario_id=usuario_id, titulo=titulo, mensaje=mensaje[:400], url=url)
    )


def _usuarios_con_rol(rol: RolUsuario) -> list[Usuario]:
    return list(
        db.session.execute(
            select(Usuario)
            .join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
            .where(UsuarioRol.rol == rol, Usuario.activo.is_(True))
        )
        .scalars()
        .unique()
    )


def avisar_asignacion(ticket, destinatario, actor) -> None:
    if destinatario is None or destinatario.id == actor.id:
        return
    crear(
        destinatario.id,
        f"Te asignaron {ticket.folio}",
        f"{actor.nombre_completo} te asigno {ticket.tipo.etiqueta.lower()} "
        f"de {ticket.nombre_cliente}.",
        ticket.url_detalle,
    )


def avisar_ok_del_operador(ticket, actor) -> None:
    """El operador dio su OK: avisa a los despachadores, que son los que
    cierran la orden en SIPREC."""
    for despachador in _usuarios_con_rol(RolUsuario.DESPACHADOR):
        if despachador.id == actor.id:
            continue
        crear(
            despachador.id,
            f"{ticket.folio} con OK del operador",
            f"{actor.nombre_completo} dio el OK del trabajo de "
            f"{ticket.nombre_cliente}. Falta cerrarla en SIPREC.",
            ticket.url_detalle,
        )


def avisar_ok_devuelto(ticket, actor) -> None:
    """El despachador devolvio la orden al operador asignado."""
    if not ticket.asignado_a_id or ticket.asignado_a_id == actor.id:
        return
    crear(
        ticket.asignado_a_id,
        f"{ticket.folio} volvio a tu bandeja",
        f"{actor.nombre_completo} devolvio la orden de {ticket.nombre_cliente}: "
        f"revisa el comentario antes de dar el OK de nuevo.",
        ticket.url_detalle,
    )


def avisar_derivacion_a_fibra(ticket, actor) -> None:
    for agente in _usuarios_con_rol(RolUsuario.AGENTE_FIBRA):
        if agente.id == actor.id:
            continue
        crear(
            agente.id,
            f"Nueva interrupcion en fibra: {ticket.folio}",
            f"{actor.nombre_completo} derivo a capa fisica la interrupcion de "
            f"{ticket.nombre_cliente}.",
            ticket.url_detalle,
        )


def avisar_respuesta_de_fibra(ticket, actor) -> None:
    if not ticket.asignado_a_id or ticket.asignado_a_id == actor.id:
        return
    resultado = ticket.estado_fibra.etiqueta if ticket.estado_fibra else "actualizada"
    crear(
        ticket.asignado_a_id,
        f"Fibra respondio en {ticket.folio}: {resultado}",
        f"{actor.nombre_completo} actualizo la revision de fibra. "
        f"Revisa el comentario y decide el cierre.",
        ticket.url_detalle,
    )


def avisar_cierre(ticket, actor) -> None:
    if not ticket.creado_por_id or ticket.creado_por_id == actor.id:
        return
    crear(
        ticket.creado_por_id,
        f"{ticket.folio} fue cerrado",
        f"{actor.nombre_completo} cerro {ticket.tipo.etiqueta.lower()} de "
        f"{ticket.nombre_cliente}.",
        ticket.url_detalle,
    )


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def contar_no_leidas(usuario_id: int) -> int:
    return (
        db.session.execute(
            select(db.func.count(Notificacion.id)).where(
                Notificacion.usuario_id == usuario_id, Notificacion.leida.is_(False)
            )
        ).scalar_one()
        or 0
    )


def listar(usuario_id: int, limite: int = 15) -> list[Notificacion]:
    return list(
        db.session.execute(
            select(Notificacion)
            .where(Notificacion.usuario_id == usuario_id)
            .order_by(Notificacion.creada_en.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )


def marcar_todas_leidas(usuario_id: int) -> int:
    resultado = db.session.execute(
        update(Notificacion)
        .where(Notificacion.usuario_id == usuario_id, Notificacion.leida.is_(False))
        .values(leida=True)
    )
    db.session.commit()
    return resultado.rowcount or 0


def marcar_leida(notificacion_id: int, usuario_id: int) -> None:
    db.session.execute(
        update(Notificacion)
        .where(Notificacion.id == notificacion_id, Notificacion.usuario_id == usuario_id)
        .values(leida=True)
    )
    db.session.commit()
