"""Modelos de datos."""
from app.models.comentario import Comentario
from app.models.contador import ContadorFolio, siguiente_folio
from app.models.enums import (
    COLORES_CATEGORIA,
    COLORES_ESTADO,
    COLORES_PRIORIDAD,
    ESTADOS_CERRADOS,
    CategoriaInterrupcion,
    Dependencia,
    EstadoFibra,
    EstadoInterrupcion,
    EstadoOrden,
    Prioridad,
    RolUsuario,
    TipoTicket,
)
from app.models.historial import Historial
from app.models.interrupcion import Interrupcion
from app.models.notificacion import Notificacion
from app.models.orden import OrdenTrabajo
from app.models.usuario import Usuario, UsuarioRol

__all__ = [
    "COLORES_CATEGORIA",
    "COLORES_ESTADO",
    "COLORES_PRIORIDAD",
    "ESTADOS_CERRADOS",
    "CategoriaInterrupcion",
    "Comentario",
    "ContadorFolio",
    "Dependencia",
    "EstadoFibra",
    "EstadoInterrupcion",
    "EstadoOrden",
    "Historial",
    "Interrupcion",
    "Notificacion",
    "OrdenTrabajo",
    "Prioridad",
    "RolUsuario",
    "TipoTicket",
    "Usuario",
    "UsuarioRol",
    "siguiente_folio",
]
