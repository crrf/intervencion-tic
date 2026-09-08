"""Comentarios de un ticket.

Una sola tabla para los dos tipos de ticket, con FK opcionales y un CHECK que
obliga a que exactamente una este presente: evita duplicar la tabla y mantiene
la integridad referencial.
"""
from __future__ import annotations

from app.extensions import db
from app.models.base import ahora


class Comentario(db.Model):
    __tablename__ = "comentario"

    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey("orden_trabajo.id", ondelete="CASCADE"))
    interrupcion_id = db.Column(db.Integer, db.ForeignKey("interrupcion.id", ondelete="CASCADE"))
    autor_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=ahora, index=True)

    autor = db.relationship("Usuario")
    orden = db.relationship("OrdenTrabajo", back_populates="comentarios")
    interrupcion = db.relationship("Interrupcion", back_populates="comentarios")

    __table_args__ = (
        db.CheckConstraint(
            "num_nonnulls(orden_id, interrupcion_id) = 1", name="ck_comentario_un_ticket"
        ),
    )

    @property
    def ticket(self):
        return self.orden or self.interrupcion
