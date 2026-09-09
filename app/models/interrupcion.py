"""Interrupcion: el operador diagnostica, clasifica la dependencia y decide
si la resuelve, la deriva al agente de fibra o la deja abierta."""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum

from app.extensions import db
from app.models.base import TicketMixin
from app.models.enums import Dependencia, EstadoFibra, EstadoInterrupcion, TipoTicket


class Interrupcion(TicketMixin, db.Model):
    __tablename__ = "interrupcion"

    tipo = TipoTicket.INTERRUPCION

    estado = db.Column(
        SAEnum(EstadoInterrupcion, name="estado_interrupcion"),
        nullable=False,
        default=EstadoInterrupcion.NUEVA,
        index=True,
    )

    # Nula al crear: "por diagnosticar". Solo el operador la fija.
    dependencia = db.Column(SAEnum(Dependencia, name="dependencia"), index=True)

    # Columna aparte que solo maneja el agente de fibra.
    estado_fibra = db.Column(SAEnum(EstadoFibra, name="estado_fibra"))

    creado_por_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    asignado_a_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), index=True)
    agente_fibra_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), index=True)

    derivado_fibra_en = db.Column(db.DateTime(timezone=True))
    respuesta_fibra_en = db.Column(db.DateTime(timezone=True))

    # Recomendada, no obligatoria (ver OrdenTrabajo).
    foto_key = db.Column(db.String(255))

    creado_por = db.relationship("Usuario", foreign_keys=[creado_por_id])
    asignado_a = db.relationship("Usuario", foreign_keys=[asignado_a_id])
    agente_fibra = db.relationship("Usuario", foreign_keys=[agente_fibra_id])

    comentarios = db.relationship(
        "Comentario",
        back_populates="interrupcion",
        cascade="all, delete-orphan",
        order_by="Comentario.creado_en",
    )
    historial = db.relationship(
        "Historial",
        back_populates="interrupcion",
        cascade="all, delete-orphan",
        order_by="Historial.creado_en",
    )

    __table_args__ = (
        db.Index("ix_interrupcion_asignado_estado", "asignado_a_id", "estado"),
    )

    FOTOS = ("foto",)

    def clave_foto(self, cual: str) -> str | None:
        return self.foto_key if cual == "foto" else None

    def set_clave_foto(self, cual: str, clave: str) -> None:
        if cual != "foto":
            raise ValueError(f"foto desconocida: {cual}")
        self.foto_key = clave

    @property
    def en_fibra(self) -> bool:
        return self.estado is EstadoInterrupcion.DERIVADA_FIBRA

    @property
    def minutos_respuesta_fibra(self) -> int | None:
        if not (self.derivado_fibra_en and self.respuesta_fibra_en):
            return None
        return int((self.respuesta_fibra_en - self.derivado_fibra_en).total_seconds() // 60)

    @property
    def minutos_en_fibra(self) -> int | None:
        """Cuanto lleva esperando al agente de fibra."""
        if not self.derivado_fibra_en:
            return None
        from app.models.base import ahora

        return int((ahora() - self.derivado_fibra_en).total_seconds() // 60)

    @property
    def ultimo_comentario(self):
        """El comentario mas reciente: da contexto sin abrir el ticket."""
        return self.comentarios[-1] if self.comentarios else None

    @property
    def url_detalle(self) -> str:
        return f"/interrupciones/{self.id}"

    def __repr__(self) -> str:
        return f"<Interrupcion {self.folio} {self.estado.name}>"
