"""direccion del sitio en ordenes e interrupciones

Revision ID: e1c38a95f604
Revises: d7b24e8f1a36
Create Date: 2026-10-26 10:00:00.000000

Donde se hace el trabajo o donde esta el servicio caido. Opcional, como el
telefono: los tickets que ya existian se quedan sin ella y se puede completar
desde el detalle.

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1c38a95f604'
down_revision = 'd7b24e8f1a36'
branch_labels = None
depends_on = None

TABLAS = ("orden_trabajo", "interrupcion")


def upgrade():
    for tabla in TABLAS:
        op.add_column(tabla, sa.Column('direccion', sa.String(length=240), nullable=True))


def downgrade():
    for tabla in TABLAS:
        op.drop_column(tabla, 'direccion')
