"""Contador de folios.

El folio se genera bloqueando esta fila dentro de la misma transaccion
(SELECT ... FOR UPDATE), no con COUNT(*): con varios workers de gunicorn un
COUNT produce folios duplicados bajo concurrencia.
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.extensions import db
from app.models.enums import TipoTicket


class ContadorFolio(db.Model):
    __tablename__ = "contador_folio"

    anio = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(8), primary_key=True)
    valor = db.Column(db.Integer, nullable=False, default=0)


def siguiente_folio(tipo: TipoTicket, anio: int) -> str:
    """Reserva y devuelve el siguiente folio del tipo y ano dados.

    Debe llamarse dentro de una transaccion; el commit lo hace quien llama.

    Se hace en un solo UPDATE atomico con upsert previo: dos transacciones
    simultaneas no pueden reservar el mismo numero (la segunda se bloquea en la
    fila hasta que la primera termina) ni chocar creando la fila inicial.
    """
    prefijo = tipo.prefijo

    # Crea la fila del contador solo si no existe; si otra transaccion se
    # adelanto, no hace nada en vez de reventar por clave duplicada.
    db.session.execute(
        pg_insert(ContadorFolio.__table__)
        .values(anio=anio, tipo=prefijo, valor=0)
        .on_conflict_do_nothing(index_elements=["anio", "tipo"])
    )

    valor = db.session.execute(
        ContadorFolio.__table__.update()
        .where(ContadorFolio.anio == anio, ContadorFolio.tipo == prefijo)
        .values(valor=ContadorFolio.valor + 1)
        .returning(ContadorFolio.valor)
    ).scalar_one()

    return f"{prefijo}-{anio}-{valor:04d}"
