"""Casos de uso sobre tickets: creacion, asignacion, comentarios, fotos.

Todo lo que muta un ticket pasa por aqui o por `services/estados.py`, de modo
que el historial y las notificaciones nunca se queden atras.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models.base import (
    ahora,
    identificador_valido,
    normalizar_identificador,
    normalizar_telefono,
    telefono_valido,
)
from app.models.comentario import Comentario
from app.models.contador import siguiente_folio
from app.models.enums import (
    Dependencia,
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
    RolUsuario,
    TipoTicket,
)
from app.models.historial import Historial
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo
from app.services import notificaciones as notif
from app.services import storage
from app.services.estados import TransicionInvalida


class DatosInvalidos(Exception):
    """Los datos recibidos no permiten crear o modificar el ticket."""


# ---------------------------------------------------------------------------
# Auditoria y comentarios
# ---------------------------------------------------------------------------
def _fk(ticket) -> dict:
    if isinstance(ticket, OrdenTrabajo):
        return {"orden_id": ticket.id}
    if isinstance(ticket, Interrupcion):
        return {"interrupcion_id": ticket.id}
    raise TypeError(f"tipo de ticket desconocido: {type(ticket)!r}")


def registrar_historial(ticket, usuario, campo, anterior, nuevo, detalle=None) -> Historial:
    fila = Historial(
        usuario_id=usuario.id,
        campo=campo,
        valor_anterior=str(anterior)[:120] if anterior is not None else None,
        valor_nuevo=str(nuevo)[:120] if nuevo is not None else None,
        detalle=detalle,
        **_fk(ticket),
    )
    db.session.add(fila)
    return fila


def agregar_comentario(ticket, usuario, texto: str) -> Comentario:
    texto = (texto or "").strip()
    if not texto:
        raise DatosInvalidos("El comentario no puede estar vacio.")
    fila = Comentario(autor_id=usuario.id, texto=texto, **_fk(ticket))
    db.session.add(fila)
    return fila


def comentar(ticket, usuario, texto: str) -> Comentario:
    """Comentario suelto, sin cambio de estado. Hace commit."""
    fila = agregar_comentario(ticket, usuario, texto)
    db.session.commit()
    return fila


def linea_de_tiempo(ticket) -> list[dict]:
    """Historial y comentarios de un ticket, mezclados y ordenados."""
    eventos = [
        {
            "tipo": "cambio",
            "cuando": h.creado_en,
            "usuario": h.usuario,
            "campo": h.campo,
            "anterior": h.valor_anterior,
            "nuevo": h.valor_nuevo,
            "detalle": h.detalle,
        }
        for h in ticket.historial
    ]
    eventos += [
        {
            "tipo": "comentario",
            "cuando": c.creado_en,
            "usuario": c.autor,
            "texto": c.texto,
        }
        for c in ticket.comentarios
    ]
    return sorted(eventos, key=lambda e: e["cuando"])


# ---------------------------------------------------------------------------
# Fotos
# ---------------------------------------------------------------------------
def _validar_y_subir(archivo, clave_base: str) -> str:
    if archivo is None or not getattr(archivo, "filename", ""):
        raise DatosInvalidos("Falta una de las fotos obligatorias.")

    extension = storage.extension_de(archivo.filename)
    if extension not in current_app.config["EXTENSIONES_FOTO"]:
        permitidas = ", ".join(sorted(current_app.config["EXTENSIONES_FOTO"]))
        raise DatosInvalidos(f"Formato no admitido. Usa: {permitidas}.")

    datos = archivo.read()
    tope_mb = current_app.config["MAX_FOTO_MB"]
    if not datos:
        raise DatosInvalidos("El archivo esta vacio.")
    if len(datos) > tope_mb * 1024 * 1024:
        raise DatosInvalidos(f"La foto supera el maximo de {tope_mb} MB.")

    try:
        datos, extension = storage.normalizar_imagen(datos, extension)
    except storage.ErrorAlmacenamiento as exc:
        raise DatosInvalidos(str(exc)) from exc

    clave = f"{clave_base}.{extension}"
    try:
        storage.subir(clave, datos, extension)
    except storage.ErrorAlmacenamiento as exc:
        raise DatosInvalidos(
            "No se pudo guardar la foto en el almacenamiento. Intenta de nuevo."
        ) from exc
    return clave


def reemplazar_foto(ticket, usuario, cual: str, archivo) -> str:
    """Sustituye una foto mientras el ticket siga abierto. Queda en historial."""
    if cual not in ticket.FOTOS:
        raise DatosInvalidos("Esa foto no existe para este tipo de ticket.")
    if not ticket.abierto:
        raise DatosInvalidos("No se pueden cambiar las fotos de un ticket cerrado.")

    carpeta = "ordenes" if isinstance(ticket, OrdenTrabajo) else "interrupciones"
    version = int(datetime.now(timezone.utc).timestamp())
    anterior = ticket.clave_foto(cual)
    clave = _validar_y_subir(archivo, f"{carpeta}/{ticket.folio}/{cual}-{version}")

    ticket.set_clave_foto(cual, clave)
    registrar_historial(ticket, usuario, f"foto_{cual}", anterior, clave)
    db.session.commit()
    if anterior and anterior != clave:
        storage.eliminar(anterior)
    return clave


# ---------------------------------------------------------------------------
# Creacion
# ---------------------------------------------------------------------------
def _validar_comunes(identificador: str, cliente: str, titulo: str, telefono: str | None) -> str:
    identificador = normalizar_identificador(identificador)
    if not identificador_valido(identificador):
        raise DatosInvalidos(
            "El identificador debe tener dos letras y seis digitos, por ejemplo ED123456."
        )
    if not (cliente or "").strip():
        raise DatosInvalidos("El nombre del cliente es obligatorio.")
    if not (titulo or "").strip():
        raise DatosInvalidos("El titulo es obligatorio.")
    _validar_telefono(telefono)
    return identificador


def _validar_telefono(telefono: str | None) -> str | None:
    """El telefono es opcional; si viene, tiene que ser plausible."""
    if not telefono_valido(telefono):
        raise DatosInvalidos(
            "El telefono de contacto solo admite digitos y los separadores + ( ) - . "
            "y debe tener al menos 7 digitos."
        )
    return normalizar_telefono(telefono)


def actualizar_telefono(ticket, usuario, telefono: str | None) -> None:
    """Permite completar o corregir el telefono despues de crear el ticket."""
    if not usuario.tiene_alguno(RolUsuario.ADMIN, RolUsuario.DESPACHADOR):
        raise DatosInvalidos("Solo un despachador o un administrador puede cambiar el telefono.")
    limpio = _validar_telefono(telefono)
    if limpio == ticket.telefono_contacto:
        return
    anterior = ticket.telefono_contacto
    ticket.telefono_contacto = limpio
    registrar_historial(ticket, usuario, "telefono_contacto", anterior, limpio)
    db.session.commit()


def _asignar_en_creacion(ticket, usuario, asignado_a, estado_destino, estado_previo) -> None:
    if not asignado_a.tiene_rol(RolUsuario.OPERADOR) or not asignado_a.activo:
        raise DatosInvalidos("El destinatario debe ser un operador activo.")
    ticket.asignado_a_id = asignado_a.id
    ticket.asignado_en = ahora()
    ticket.estado = estado_destino
    registrar_historial(ticket, usuario, "asignado_a", None, asignado_a.nombre_completo)
    registrar_historial(
        ticket, usuario, "estado", estado_previo.etiqueta, estado_destino.etiqueta
    )
    notif.avisar_asignacion(ticket, asignado_a, usuario)


def crear_orden(
    usuario,
    *,
    identificador_externo: str,
    nombre_cliente: str,
    titulo: str,
    telefono_contacto: str | None = None,
    descripcion: str = "",
    prioridad: Prioridad | str = Prioridad.MEDIA,
    foto_anverso=None,
    foto_reverso=None,
    asignado_a=None,
) -> OrdenTrabajo:
    """Crea una orden de trabajo. Las dos caras de la foto son obligatorias."""
    identificador = _validar_comunes(
        identificador_externo, nombre_cliente, titulo, telefono_contacto
    )
    if isinstance(prioridad, str):
        prioridad = Prioridad.desde_nombre(prioridad) or Prioridad.MEDIA

    folio = siguiente_folio(TipoTicket.ORDEN, ahora().year)
    anverso = _validar_y_subir(foto_anverso, f"ordenes/{folio}/anverso")
    try:
        reverso = _validar_y_subir(foto_reverso, f"ordenes/{folio}/reverso")
    except DatosInvalidos:
        storage.eliminar(anverso)
        raise

    orden = OrdenTrabajo(
        folio=folio,
        identificador_externo=identificador,
        nombre_cliente=nombre_cliente.strip(),
        telefono_contacto=normalizar_telefono(telefono_contacto),
        titulo=titulo.strip(),
        descripcion=(descripcion or "").strip(),
        prioridad=prioridad,
        estado=EstadoOrden.NUEVA,
        creado_por_id=usuario.id,
        foto_anverso_key=anverso,
        foto_reverso_key=reverso,
    )
    db.session.add(orden)
    db.session.flush()
    registrar_historial(orden, usuario, "estado", None, EstadoOrden.NUEVA.etiqueta)

    if asignado_a is not None:
        _asignar_en_creacion(
            orden, usuario, asignado_a, EstadoOrden.ASIGNADA, EstadoOrden.NUEVA
        )

    db.session.commit()
    return orden


def crear_interrupcion(
    usuario,
    *,
    identificador_externo: str,
    nombre_cliente: str,
    titulo: str,
    telefono_contacto: str | None = None,
    descripcion: str = "",
    prioridad: Prioridad | str = Prioridad.MEDIA,
    foto=None,
    asignado_a=None,
) -> Interrupcion:
    """Crea una interrupcion. La foto es obligatoria.

    La dependencia NO se define aqui: nace como "por diagnosticar" y la fija
    el operador cuando revisa.
    """
    identificador = _validar_comunes(
        identificador_externo, nombre_cliente, titulo, telefono_contacto
    )
    if isinstance(prioridad, str):
        prioridad = Prioridad.desde_nombre(prioridad) or Prioridad.MEDIA

    folio = siguiente_folio(TipoTicket.INTERRUPCION, ahora().year)
    clave = _validar_y_subir(foto, f"interrupciones/{folio}/foto")

    inter = Interrupcion(
        folio=folio,
        identificador_externo=identificador,
        nombre_cliente=nombre_cliente.strip(),
        telefono_contacto=normalizar_telefono(telefono_contacto),
        titulo=titulo.strip(),
        descripcion=(descripcion or "").strip(),
        prioridad=prioridad,
        estado=EstadoInterrupcion.NUEVA,
        dependencia=None,
        creado_por_id=usuario.id,
        foto_key=clave,
    )
    db.session.add(inter)
    db.session.flush()
    registrar_historial(inter, usuario, "estado", None, EstadoInterrupcion.NUEVA.etiqueta)

    if asignado_a is not None:
        _asignar_en_creacion(
            inter, usuario, asignado_a, EstadoInterrupcion.ASIGNADA, EstadoInterrupcion.NUEVA
        )

    db.session.commit()
    return inter


# ---------------------------------------------------------------------------
# Reasignacion (accion aparte de la maquina de estados)
# ---------------------------------------------------------------------------
def reasignar(ticket, usuario, nuevo_operador) -> None:
    """Cambia el operador de un ticket ya asignado. Solo admin o despachador."""
    if not usuario.tiene_alguno(RolUsuario.ADMIN, RolUsuario.DESPACHADOR):
        raise TransicionInvalida("Solo un despachador o un administrador puede reasignar.")
    if not ticket.abierto:
        raise TransicionInvalida("No se puede reasignar un ticket cerrado.")
    if nuevo_operador is None or not nuevo_operador.tiene_rol(RolUsuario.OPERADOR):
        raise TransicionInvalida("El destinatario debe ser un operador activo.")
    if not nuevo_operador.activo:
        raise TransicionInvalida("El destinatario debe ser un operador activo.")
    if ticket.asignado_a_id == nuevo_operador.id:
        return

    previo = ticket.asignado_a.nombre_completo if ticket.asignado_a else None
    ticket.asignado_a_id = nuevo_operador.id
    ticket.asignado_en = ahora()
    registrar_historial(ticket, usuario, "asignado_a", previo, nuevo_operador.nombre_completo)
    notif.avisar_asignacion(ticket, nuevo_operador, usuario)
    db.session.commit()


# ---------------------------------------------------------------------------
# Clasificacion de dependencia (solo el operador asignado, al diagnosticar)
# ---------------------------------------------------------------------------
def clasificar_dependencia(interrupcion, usuario, dependencia) -> None:
    if isinstance(dependencia, str):
        dependencia = Dependencia.desde_nombre(dependencia)
    if dependencia is None:
        raise DatosInvalidos("Selecciona una dependencia valida.")

    permitido = usuario.tiene_rol(RolUsuario.ADMIN) or (
        usuario.tiene_rol(RolUsuario.OPERADOR) and interrupcion.asignado_a_id == usuario.id
    )
    if not permitido:
        raise TransicionInvalida("Solo el operador asignado clasifica la dependencia.")
    if not interrupcion.abierto:
        raise TransicionInvalida("La interrupcion ya esta cerrada.")
    if dependencia is interrupcion.dependencia:
        return

    anterior = interrupcion.dependencia.etiqueta if interrupcion.dependencia else None
    interrupcion.dependencia = dependencia
    registrar_historial(interrupcion, usuario, "dependencia", anterior, dependencia.etiqueta)
    db.session.commit()
