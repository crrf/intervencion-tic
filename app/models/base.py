"""Piezas compartidas por las dos tablas de ticket."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import Enum as SAEnum

from app.extensions import db
from app.models.enums import Prioridad

#: Identificador del sistema externo: dos letras cualesquiera y de 4 a 8
#: digitos (ED1234, FD12345678, WF987654...). El largo varia segun el sistema
#: del que venga, asi que no se fija en seis.
MIN_DIGITOS_IDENTIFICADOR = 4
MAX_DIGITOS_IDENTIFICADOR = 8
PATRON_IDENTIFICADOR = re.compile(
    rf"^[A-Z]{{2}}\d{{{MIN_DIGITOS_IDENTIFICADOR},{MAX_DIGITOS_IDENTIFICADOR}}}$"
)

#: Caracteres admitidos en un telefono: digitos y separadores de uso comun.
PATRON_TELEFONO = re.compile(r"^[\d+()\-.\s]+$")
MIN_DIGITOS_TELEFONO = 7


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def normalizar_identificador(valor: str | None) -> str:
    return (valor or "").strip().upper().replace(" ", "")


def identificador_valido(valor: str | None) -> bool:
    return bool(PATRON_IDENTIFICADOR.match(normalizar_identificador(valor)))


def normalizar_telefono(valor: str | None) -> str | None:
    """Limpia el telefono. Vacio devuelve None: el campo es opcional."""
    limpio = " ".join((valor or "").split())
    return limpio or None


def telefono_valido(valor: str | None) -> bool:
    """Un telefono ausente es valido: el campo es recomendado, no obligatorio."""
    limpio = normalizar_telefono(valor)
    if limpio is None:
        return True
    if not PATRON_TELEFONO.match(limpio):
        return False
    return sum(c.isdigit() for c in limpio) >= MIN_DIGITOS_TELEFONO


class TicketMixin:
    """Columnas comunes a `orden_trabajo` e `interrupcion`.

    Las dos tablas viven separadas a proposito (flujos distintos), pero
    comparten esta base para que las consultas unificadas de
    `services/consultas.py` puedan tratarlas por igual.
    """

    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(24), unique=True, nullable=False, index=True)
    identificador_externo = db.Column(db.String(20), nullable=False, index=True)
    nombre_cliente = db.Column(db.String(160), nullable=False)
    # Opcional pero recomendado: le ahorra al operador una vuelta al sitio.
    telefono_contacto = db.Column(db.String(40))
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    prioridad = db.Column(
        SAEnum(Prioridad, name="prioridad"), nullable=False, default=Prioridad.MEDIA
    )
    motivo_apertura = db.Column(db.Text)

    creado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=ahora, index=True)
    asignado_en = db.Column(db.DateTime(timezone=True))
    cerrado_en = db.Column(db.DateTime(timezone=True), index=True)

    @property
    def abierto(self) -> bool:
        return self.estado.name != "CERRADA"

    @property
    def minutos_resolucion(self) -> int | None:
        if not self.cerrado_en:
            return None
        return int((self.cerrado_en - self.creado_en).total_seconds() // 60)

    @property
    def minutos_transcurridos(self) -> int:
        fin = self.cerrado_en or ahora()
        return int((fin - self.creado_en).total_seconds() // 60)

    @property
    def fotos_faltantes(self) -> list[str]:
        """Fotos recomendadas que todavia no se han adjuntado."""
        return [cual for cual in self.FOTOS if not self.clave_foto(cual)]

    @property
    def tiene_todas_las_fotos(self) -> bool:
        return not self.fotos_faltantes

    @property
    def telefono_marcable(self) -> str | None:
        """El telefono sin separadores, para el enlace `tel:`."""
        if not self.telefono_contacto:
            return None
        return "".join(c for c in self.telefono_contacto if c.isdigit() or c == "+")
