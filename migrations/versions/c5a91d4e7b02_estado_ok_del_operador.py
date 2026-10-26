"""estado OK del operador en las ordenes de trabajo

Revision ID: c5a91d4e7b02
Revises: 44467c37bf63
Create Date: 2026-10-01 10:00:00.000000

El operador ya no cierra la orden: da su OK y la orden queda a la vista del
despachador, que la cierra en SIPREC. Eso agrega un valor al enum
estado_orden, justo antes de CERRADA.

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c5a91d4e7b02'
down_revision = '44467c37bf63'
branch_labels = None
depends_on = None

#: Valores del enum antes de este cambio (los necesita el downgrade).
ESTADOS_SIN_OK = ('NUEVA', 'ASIGNADA', 'EN_PROCESO', 'ABIERTA_CON_MOTIVO', 'CERRADA')


def upgrade():
    # PostgreSQL 12+ admite ADD VALUE dentro de la transaccion de la migracion
    # mientras el valor nuevo no se USE en ella; aqui solo se declara.
    op.execute(
        "ALTER TYPE estado_orden ADD VALUE IF NOT EXISTS 'OK_OPERADOR' BEFORE 'CERRADA'"
    )


def downgrade():
    # A un enum de PostgreSQL no se le puede quitar un valor: hay que recrear
    # el tipo sin el. Las ordenes que estuvieran con OK vuelven a proceso, que
    # es el estado del que salieron.
    op.execute("UPDATE orden_trabajo SET estado = 'EN_PROCESO' WHERE estado = 'OK_OPERADOR'")
    op.execute("ALTER TYPE estado_orden RENAME TO estado_orden_con_ok")
    valores = ", ".join(f"'{estado}'" for estado in ESTADOS_SIN_OK)
    op.execute(f"CREATE TYPE estado_orden AS ENUM ({valores})")
    op.execute(
        "ALTER TABLE orden_trabajo ALTER COLUMN estado TYPE estado_orden "
        "USING estado::text::estado_orden"
    )
    op.execute("DROP TYPE estado_orden_con_ok")
