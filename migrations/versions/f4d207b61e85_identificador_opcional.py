"""el identificador externo pasa a ser opcional

Revision ID: f4d207b61e85
Revises: e1c38a95f604
Create Date: 2026-10-26 14:00:00.000000

Las interrupciones de sitio wifi no vienen del sistema externo y no tienen
identificador: para ellas el folio es el identificador. La columna deja de ser
obligatoria en las dos tablas.

El downgrade solo puede volver a NOT NULL si no quedan filas sin
identificador, asi que les pone el folio antes de restaurar la restriccion.

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4d207b61e85'
down_revision = 'e1c38a95f604'
branch_labels = None
depends_on = None

TABLAS = ("orden_trabajo", "interrupcion")


def upgrade():
    for tabla in TABLAS:
        op.alter_column(
            tabla,
            'identificador_externo',
            existing_type=sa.VARCHAR(length=20),
            nullable=True,
        )


def downgrade():
    for tabla in TABLAS:
        op.execute(
            f"UPDATE {tabla} SET identificador_externo = folio "  # noqa: S608
            "WHERE identificador_externo IS NULL"
        )
        op.alter_column(
            tabla,
            'identificador_externo',
            existing_type=sa.VARCHAR(length=20),
            nullable=False,
        )
