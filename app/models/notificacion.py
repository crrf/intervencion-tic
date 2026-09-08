"""Notificaciones in-app (campana con contador)."""
from __future__ import annotations

from app.extensions import db
from app.models.base import ahora


class Notificacion(db.Model):
    __tablename__ = "notificacion"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False
    )
    titulo = db.Column(db.String(140), nullable=False)
    mensaje = db.Column(db.String(400), nullable=False, default="")
    url = db.Column(db.String(255))
    leida = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))
    creada_en = db.Column(db.DateTime(timezone=True), nullable=False, default=ahora, index=True)

    usuario = db.relationship("Usuario")

    __table_args__ = (db.Index("ix_notificacion_usuario_leida", "usuario_id", "leida"),)
