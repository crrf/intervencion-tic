"""Bitacora de auditoria: quien cambio que, cuando y de que valor a cual.

La escribe siempre la capa de servicios, nunca las vistas.
"""
from __future__ import annotations

from app.extensions import db
from app.models.base import ahora


class Historial(db.Model):
    __tablename__ = "historial"

    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey("orden_trabajo.id", ondelete="CASCADE"))
    interrupcion_id = db.Column(db.Integer, db.ForeignKey("interrupcion.id", ondelete="CASCADE"))
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False, index=True)
    campo = db.Column(db.String(40), nullable=False, index=True)
    valor_anterior = db.Column(db.String(120))
    valor_nuevo = db.Column(db.String(120))
    detalle = db.Column(db.Text)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=ahora, index=True)

    usuario = db.relationship("Usuario")
    orden = db.relationship("OrdenTrabajo", back_populates="historial")
    interrupcion = db.relationship("Interrupcion", back_populates="historial")

    __table_args__ = (
        db.CheckConstraint(
            "num_nonnulls(orden_id, interrupcion_id) = 1", name="ck_historial_un_ticket"
        ),
        db.Index("ix_historial_campo_valor", "campo", "valor_nuevo"),
    )

    @property
    def ticket(self):
        return self.orden or self.interrupcion
