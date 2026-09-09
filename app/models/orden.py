"""Orden de trabajo: se asigna a un operador, que la cierra o la deja abierta."""
from __future__ import annotations

from sqlalchemy import Enum as SAEnum

from app.extensions import db
from app.models.base import TicketMixin
from app.models.enums import EstadoOrden, TipoTicket


class OrdenTrabajo(TicketMixin, db.Model):
    __tablename__ = "orden_trabajo"

    tipo = TipoTicket.ORDEN

    estado = db.Column(
        SAEnum(EstadoOrden, name="estado_orden"),
        nullable=False,
        default=EstadoOrden.NUEVA,
        index=True,
    )

    creado_por_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    asignado_a_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), index=True)

    # Foto del documento fisico de la orden, por sus dos caras. Obligatorias
    # al crear; solo las sube el despachador (o un admin).
    # Recomendadas, no obligatorias: el ticket puede nacer sin ellas y el
    # despachador las agrega despues desde el detalle.
    foto_anverso_key = db.Column(db.String(255))
    foto_reverso_key = db.Column(db.String(255))

    creado_por = db.relationship("Usuario", foreign_keys=[creado_por_id])
    asignado_a = db.relationship("Usuario", foreign_keys=[asignado_a_id])

    comentarios = db.relationship(
        "Comentario",
        back_populates="orden",
        cascade="all, delete-orphan",
        order_by="Comentario.creado_en",
    )
    historial = db.relationship(
        "Historial",
        back_populates="orden",
        cascade="all, delete-orphan",
        order_by="Historial.creado_en",
    )

    __table_args__ = (
        db.Index("ix_orden_asignado_estado", "asignado_a_id", "estado"),
    )

    #: Nombre logico de las fotos que admite este tipo de ticket.
    FOTOS = ("anverso", "reverso")

    def clave_foto(self, cual: str) -> str | None:
        return {"anverso": self.foto_anverso_key, "reverso": self.foto_reverso_key}.get(cual)

    def set_clave_foto(self, cual: str, clave: str) -> None:
        if cual == "anverso":
            self.foto_anverso_key = clave
        elif cual == "reverso":
            self.foto_reverso_key = clave
        else:
            raise ValueError(f"foto desconocida: {cual}")

    @property
    def url_detalle(self) -> str:
        return f"/ordenes/{self.id}"

    def __repr__(self) -> str:
        return f"<OrdenTrabajo {self.folio} {self.estado.name}>"
