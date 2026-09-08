"""Maquinas de estado de los dos tipos de ticket.

Este modulo es la unica autoridad sobre "quien puede mover que". Las vistas
nunca cambian un estado directamente: llaman a `ejecutar_transicion`, que
valida rol + estado de origen + campos obligatorios, escribe el historial y
dispara las notificaciones.

Roles multiples: un usuario puede ser, por ejemplo, despachador y operador a
la vez. Por eso cada transicion declara una lista de *concesiones* (rol + si
exige ser el asignado) y el permiso resultante es la UNION: basta que una
concesion coincida.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.base import ahora
from app.models.enums import (
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    RolUsuario,
)
from app.models.interrupcion import Interrupcion
from app.models.orden import OrdenTrabajo


class TransicionInvalida(Exception):
    """El cambio de estado solicitado no esta permitido o le faltan datos."""


@dataclass(frozen=True)
class Concesion:
    """Un rol que habilita una transicion, y bajo que condicion."""

    rol: RolUsuario
    solo_asignado: bool = False

    def concede(self, ticket, usuario) -> bool:
        if not usuario.tiene_rol(self.rol):
            return False
        if self.solo_asignado and ticket.asignado_a_id != usuario.id:
            return False
        return True


ADMIN = Concesion(RolUsuario.ADMIN)
DESPACHADOR = Concesion(RolUsuario.DESPACHADOR)
OPERADOR = Concesion(RolUsuario.OPERADOR, solo_asignado=True)
FIBRA = Concesion(RolUsuario.AGENTE_FIBRA)


@dataclass(frozen=True)
class Transicion:
    origen: object
    destino: object
    etiqueta: str
    concesiones: tuple[Concesion, ...]
    campo: str = "estado"
    exige_comentario: bool = False
    exige_motivo: bool = False
    exige_dependencia: bool = False
    exige_capa_fisica: bool = False
    exige_asignado: bool = False
    peligrosa: bool = False
    ayuda: str = ""

    @property
    def clave(self) -> str:
        return f"{self.campo}:{self.destino.name}"

    def permitida_para(self, ticket, usuario) -> bool:
        return any(c.concede(ticket, usuario) for c in self.concesiones)

    @property
    def pide_datos(self) -> bool:
        """Si es True la interfaz debe abrir un modal en vez de mover directo."""
        return (
            self.exige_comentario
            or self.exige_motivo
            or self.exige_asignado
            or self.exige_dependencia
        )


# ---------------------------------------------------------------------------
# Orden de trabajo
# ---------------------------------------------------------------------------
TRANSICIONES_ORDEN: tuple[Transicion, ...] = (
    Transicion(
        EstadoOrden.NUEVA,
        EstadoOrden.ASIGNADA,
        "Asignar a un operador",
        (DESPACHADOR, ADMIN),
        exige_asignado=True,
        ayuda="Selecciona el operador que atendera la orden.",
    ),
    Transicion(
        EstadoOrden.ASIGNADA,
        EstadoOrden.EN_PROCESO,
        "Tomar / iniciar trabajo",
        (OPERADOR, ADMIN),
    ),
    Transicion(
        EstadoOrden.EN_PROCESO,
        EstadoOrden.CERRADA,
        "Cerrar orden",
        (OPERADOR, ADMIN),
        exige_comentario=True,
        ayuda="Describe el trabajo realizado.",
    ),
    Transicion(
        EstadoOrden.EN_PROCESO,
        EstadoOrden.ABIERTA_CON_MOTIVO,
        "Dejar abierta con motivo",
        (OPERADOR, ADMIN),
        exige_comentario=True,
        exige_motivo=True,
        ayuda="Indica por que no se puede cerrar todavia.",
    ),
    Transicion(
        EstadoOrden.ABIERTA_CON_MOTIVO,
        EstadoOrden.EN_PROCESO,
        "Retomar trabajo",
        (OPERADOR, ADMIN),
    ),
    Transicion(
        EstadoOrden.ABIERTA_CON_MOTIVO,
        EstadoOrden.CERRADA,
        "Cerrar orden",
        (OPERADOR, ADMIN),
        exige_comentario=True,
    ),
    Transicion(
        EstadoOrden.CERRADA,
        EstadoOrden.EN_PROCESO,
        "Reabrir orden",
        (ADMIN,),
        exige_comentario=True,
        peligrosa=True,
        ayuda="La reapertura queda registrada en el historial.",
    ),
)


# ---------------------------------------------------------------------------
# Interrupcion
# ---------------------------------------------------------------------------
TRANSICIONES_INTERRUPCION: tuple[Transicion, ...] = (
    Transicion(
        EstadoInterrupcion.NUEVA,
        EstadoInterrupcion.ASIGNADA,
        "Asignar a un operador",
        (DESPACHADOR, ADMIN),
        exige_asignado=True,
    ),
    Transicion(
        EstadoInterrupcion.ASIGNADA,
        EstadoInterrupcion.EN_PROCESO,
        "Tomar / iniciar diagnostico",
        (OPERADOR, ADMIN),
    ),
    Transicion(
        EstadoInterrupcion.EN_PROCESO,
        EstadoInterrupcion.CERRADA,
        "Cerrar interrupcion",
        (OPERADOR, ADMIN),
        exige_comentario=True,
        exige_dependencia=True,
        ayuda="Clasifica la dependencia y describe la solucion.",
    ),
    Transicion(
        EstadoInterrupcion.EN_PROCESO,
        EstadoInterrupcion.DERIVADA_FIBRA,
        "Derivar a fibra optica",
        (OPERADOR, ADMIN),
        exige_comentario=True,
        exige_dependencia=True,
        exige_capa_fisica=True,
        ayuda="Solo para fallas de capa fisica: pasa a la bandeja del agente de fibra.",
    ),
    Transicion(
        EstadoInterrupcion.EN_PROCESO,
        EstadoInterrupcion.ABIERTA_OTRO_MOTIVO,
        "Dejar abierta / otro motivo",
        (OPERADOR, ADMIN),
        exige_comentario=True,
        exige_motivo=True,
        exige_dependencia=True,
    ),
    Transicion(
        EstadoInterrupcion.ABIERTA_OTRO_MOTIVO,
        EstadoInterrupcion.EN_PROCESO,
        "Retomar diagnostico",
        (OPERADOR, ADMIN),
    ),
    Transicion(
        EstadoInterrupcion.ABIERTA_OTRO_MOTIVO,
        EstadoInterrupcion.CERRADA,
        "Cerrar interrupcion",
        (OPERADOR, ADMIN),
        exige_comentario=True,
    ),
    Transicion(
        EstadoInterrupcion.DERIVADA_FIBRA,
        EstadoInterrupcion.CERRADA,
        "Cerrar interrupcion",
        (OPERADOR, ADMIN),
        exige_comentario=True,
        ayuda="Cierra tras revisar la respuesta del agente de fibra.",
    ),
    Transicion(
        EstadoInterrupcion.DERIVADA_FIBRA,
        EstadoInterrupcion.EN_PROCESO,
        "Retomar (quitar de fibra)",
        (OPERADOR, ADMIN),
        exige_comentario=True,
    ),
    Transicion(
        EstadoInterrupcion.CERRADA,
        EstadoInterrupcion.EN_PROCESO,
        "Reabrir interrupcion",
        (ADMIN,),
        exige_comentario=True,
        peligrosa=True,
    ),
)


# ---------------------------------------------------------------------------
# estado_fibra: columna aparte, la mueve solo el agente de fibra.
# Se permite ir de cualquier valor a cualquier otro, siempre con comentario.
# ---------------------------------------------------------------------------
def _construir_transiciones_fibra() -> tuple[Transicion, ...]:
    etiquetas = {
        EstadoFibra.EN_REVISION: "Devolver a revision",
        EstadoFibra.FIBRA_OK: "Marcar fibra OK",
        EstadoFibra.FIBRA_CON_FALLA: "Marcar fibra con falla",
    }
    salida = []
    for origen in EstadoFibra:
        for destino in EstadoFibra:
            if origen is destino:
                continue
            salida.append(
                Transicion(
                    origen,
                    destino,
                    etiquetas[destino],
                    (FIBRA, ADMIN),
                    campo="estado_fibra",
                    exige_comentario=True,
                    ayuda="El operador vera este resultado y decidira el cierre.",
                )
            )
    return tuple(salida)


TRANSICIONES_FIBRA: tuple[Transicion, ...] = _construir_transiciones_fibra()


# ---------------------------------------------------------------------------
# Consulta de transiciones
# ---------------------------------------------------------------------------
def _tabla(ticket) -> tuple[Transicion, ...]:
    if isinstance(ticket, OrdenTrabajo):
        return TRANSICIONES_ORDEN
    if isinstance(ticket, Interrupcion):
        return TRANSICIONES_INTERRUPCION
    raise TypeError(f"tipo de ticket desconocido: {type(ticket)!r}")


def transiciones_permitidas(ticket, usuario) -> list[Transicion]:
    """Union de las transiciones que los roles del usuario habilitan aqui."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return []

    salida = [
        t
        for t in _tabla(ticket)
        if t.origen is ticket.estado and t.permitida_para(ticket, usuario)
    ]

    # El estado_fibra solo se puede tocar mientras la interrupcion esta derivada.
    if isinstance(ticket, Interrupcion) and ticket.estado is EstadoInterrupcion.DERIVADA_FIBRA:
        actual = ticket.estado_fibra or EstadoFibra.EN_REVISION
        salida += [
            t
            for t in TRANSICIONES_FIBRA
            if t.origen is actual and t.permitida_para(ticket, usuario)
        ]
    return salida


def buscar_transicion(ticket, usuario, clave: str) -> Transicion:
    """Localiza por clave (`campo:DESTINO`) una transicion permitida."""
    for t in transiciones_permitidas(ticket, usuario):
        if t.clave == clave:
            return t
    raise TransicionInvalida(
        "Ese cambio no esta permitido para tu perfil o para el estado actual del ticket."
    )


# ---------------------------------------------------------------------------
# Ejecucion
# ---------------------------------------------------------------------------
def ejecutar_transicion(
    ticket,
    usuario,
    clave: str,
    *,
    comentario: str | None = None,
    motivo: str | None = None,
    dependencia: Dependencia | str | None = None,
    asignado_a=None,
    telefono_contacto: str | None = None,
) -> Transicion:
    """Aplica una transicion validando permisos y datos obligatorios.

    No hace commit: eso queda en manos de quien llama, para que el cambio de
    estado, el comentario, el historial y las notificaciones formen una sola
    transaccion.
    """
    from app.models.base import normalizar_telefono, telefono_valido
    from app.services import notificaciones as notif
    from app.services.tickets import agregar_comentario, registrar_historial

    transicion = buscar_transicion(ticket, usuario, clave)
    comentario = (comentario or "").strip()
    motivo = (motivo or "").strip()

    if transicion.exige_comentario and not comentario:
        raise TransicionInvalida("Este cambio exige un comentario.")
    if transicion.exige_motivo and not motivo:
        raise TransicionInvalida("Debes indicar el motivo por el que queda abierto.")

    # --- Dependencia (solo interrupciones) ---------------------------------
    if isinstance(dependencia, str):
        dependencia = Dependencia.desde_nombre(dependencia)
    if isinstance(ticket, Interrupcion):
        if dependencia is not None and dependencia is not ticket.dependencia:
            registrar_historial(
                ticket,
                usuario,
                "dependencia",
                ticket.dependencia.etiqueta if ticket.dependencia else None,
                dependencia.etiqueta,
            )
            ticket.dependencia = dependencia
        if transicion.exige_dependencia and ticket.dependencia is None:
            raise TransicionInvalida(
                "Antes de mover la interrupcion debes clasificar la dependencia."
            )
        if transicion.exige_capa_fisica and ticket.dependencia is not Dependencia.CAPA_FISICA:
            raise TransicionInvalida(
                "Solo se puede derivar a fibra una interrupcion clasificada como capa fisica."
            )

    # --- Asignacion --------------------------------------------------------
    if transicion.exige_asignado:
        if asignado_a is None:
            raise TransicionInvalida("Debes elegir el operador al que se asigna el ticket.")
        if not asignado_a.tiene_rol(RolUsuario.OPERADOR) or not asignado_a.activo:
            raise TransicionInvalida("El destinatario debe ser un operador activo.")

    # --- Telefono de contacto ---------------------------------------------
    # Opcional, pero es al asignar cuando mas falta le hace al operador, asi
    # que el formulario de asignacion lo ofrece y aqui se guarda si viene.
    if telefono_contacto is not None and telefono_contacto.strip():
        if not telefono_valido(telefono_contacto):
            raise TransicionInvalida(
                "El telefono de contacto solo admite digitos y los separadores "
                "+ ( ) - . y debe tener al menos 7 digitos."
            )
        limpio = normalizar_telefono(telefono_contacto)
        if limpio != ticket.telefono_contacto:
            registrar_historial(
                ticket, usuario, "telefono_contacto", ticket.telefono_contacto, limpio
            )
            ticket.telefono_contacto = limpio

    anterior = getattr(ticket, transicion.campo)
    etiqueta_anterior = anterior.etiqueta if anterior is not None else None

    if transicion.campo == "estado":
        ticket.estado = transicion.destino

        if transicion.exige_asignado and asignado_a is not None:
            previo = ticket.asignado_a.nombre_completo if ticket.asignado_a else None
            ticket.asignado_a_id = asignado_a.id
            ticket.asignado_en = ahora()
            registrar_historial(ticket, usuario, "asignado_a", previo, asignado_a.nombre_completo)
            notif.avisar_asignacion(ticket, asignado_a, usuario)

        if transicion.exige_motivo:
            ticket.motivo_apertura = motivo

        if transicion.destino.name == "CERRADA":
            ticket.cerrado_en = ahora()
            notif.avisar_cierre(ticket, usuario)
        elif anterior is not None and anterior.name == "CERRADA":
            ticket.cerrado_en = None  # reapertura

        if transicion.destino.name == "DERIVADA_FIBRA":
            ticket.derivado_fibra_en = ahora()
            ticket.estado_fibra = EstadoFibra.EN_REVISION
            ticket.respuesta_fibra_en = None
            ticket.agente_fibra_id = None
            notif.avisar_derivacion_a_fibra(ticket, usuario)

    else:  # estado_fibra
        ticket.estado_fibra = transicion.destino
        ticket.agente_fibra_id = usuario.id
        ticket.respuesta_fibra_en = ahora()
        notif.avisar_respuesta_de_fibra(ticket, usuario)

    registrar_historial(
        ticket, usuario, transicion.campo, etiqueta_anterior, transicion.destino.etiqueta
    )
    if comentario:
        agregar_comentario(ticket, usuario, comentario)

    return transicion
