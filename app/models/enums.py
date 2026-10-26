"""Enumeraciones del dominio.

El valor de cada miembro es su etiqueta en espanol (lo que ve el usuario);
SQLAlchemy persiste el *nombre* del miembro, de modo que se puede cambiar la
redaccion de una etiqueta sin migrar la base de datos.
"""
from __future__ import annotations

import enum


class _EnumEtiquetado(enum.Enum):
    @property
    def etiqueta(self) -> str:
        return self.value

    @classmethod
    def opciones(cls) -> list[tuple[str, str]]:
        return [(m.name, m.value) for m in cls]

    @classmethod
    def desde_nombre(cls, nombre: str | None):
        if not nombre:
            return None
        try:
            return cls[nombre.upper()]
        except KeyError:
            return None

    def __str__(self) -> str:  # util en plantillas
        return self.value


class RolUsuario(_EnumEtiquetado):
    ADMIN = "Administrador"
    DESPACHADOR = "Despachador"
    OPERADOR = "Operador"
    AGENTE_FIBRA = "Agente de fibra"
    #: Va al sitio wifi a detectar la falla y, si puede, a resolverla. Trabaja
    #: la interrupcion igual que un operador, pero solo se le entregan las de
    #: categoria SITIO_WIFI.
    TECNICO_WIFI = "Tecnico de wifi"


class TipoTicket(_EnumEtiquetado):
    ORDEN = "Orden de trabajo"
    INTERRUPCION = "Interrupcion"

    @property
    def prefijo(self) -> str:
        return "OT" if self is TipoTicket.ORDEN else "INT"


class EstadoOrden(_EnumEtiquetado):
    NUEVA = "Nueva"
    ASIGNADA = "Asignada"
    EN_PROCESO = "En proceso"
    ABIERTA_CON_MOTIVO = "Abierta con motivo"
    #: El operador dio el trabajo por bueno. La orden NO se cierra aqui: queda
    #: a la vista del despachador, que la cierra en SIPREC. Para metricas y
    #: filtros sigue contando como abierta.
    OK_OPERADOR = "OK del operador"
    CERRADA = "Cerrada"


class CategoriaInterrupcion(_EnumEtiquetado):
    """Que se cayo: el enlace de un cliente o un sitio wifi.

    La fija el despachador al crear la interrupcion (no el operador al
    diagnosticar, como la dependencia) porque la necesita para saber a quien
    se la entrega.
    """

    ENLACE_CLIENTE = "Enlace de cliente"
    SITIO_WIFI = "Sitio wifi"


class EstadoInterrupcion(_EnumEtiquetado):
    NUEVA = "Nueva"
    ASIGNADA = "Asignada"
    EN_PROCESO = "En proceso"
    DERIVADA_FIBRA = "Derivada a fibra"
    ABIERTA_OTRO_MOTIVO = "Abierta / otro motivo"
    CERRADA = "Cerrada"


class EstadoFibra(_EnumEtiquetado):
    EN_REVISION = "En revision"
    FIBRA_OK = "Fibra OK"
    FIBRA_CON_FALLA = "Fibra con falla"


class Dependencia(_EnumEtiquetado):
    CORE_IPMPLS = "Core (IPMPLS)"
    DISTRIBUCION = "Distribucion"
    CAPA_FISICA = "Capa fisica (fibra)"


class Prioridad(_EnumEtiquetado):
    BAJA = "Baja"
    MEDIA = "Media"
    ALTA = "Alta"
    CRITICA = "Critica"

    @property
    def peso(self) -> int:
        return {"BAJA": 1, "MEDIA": 2, "ALTA": 3, "CRITICA": 4}[self.name]


#: Estados que se consideran "cerrado" para efectos de metricas y filtros.
ESTADOS_CERRADOS = {"CERRADA"}

#: Colores de las insignias en la interfaz, por nombre de miembro.
COLORES_ESTADO = {
    "NUEVA": "gris",
    "ASIGNADA": "azul",
    "EN_PROCESO": "ambar",
    "DERIVADA_FIBRA": "violeta",
    "ABIERTA_CON_MOTIVO": "rojo",
    "ABIERTA_OTRO_MOTIVO": "rojo",
    "OK_OPERADOR": "cian",
    "CERRADA": "verde",
    "EN_REVISION": "ambar",
    "FIBRA_OK": "verde",
    "FIBRA_CON_FALLA": "rojo",
}

COLORES_PRIORIDAD = {"BAJA": "gris", "MEDIA": "azul", "ALTA": "ambar", "CRITICA": "rojo"}

#: Solo se pinta la insignia de sitio wifi: el enlace de cliente es lo normal
#: y marcarlo seria ruido en la tarjeta. El fucsia es exclusivo de esta
#: categoria: el violeta ya significa "derivada a fibra" y las dos insignias
#: conviven en la misma tarjeta.
COLORES_CATEGORIA = {"ENLACE_CLIENTE": "gris", "SITIO_WIFI": "fucsia"}
