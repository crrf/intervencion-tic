"""tecnico de wifi y categoria de la interrupcion

Revision ID: d7b24e8f1a36
Revises: c5a91d4e7b02
Create Date: 2026-10-01 18:00:00.000000

Dos cosas: un rol nuevo (el tecnico que va al sitio wifi) y la categoria de la
interrupcion, que es la que decide si se le puede entregar a el. Las
interrupciones que ya existian quedan como enlace de cliente.

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7b24e8f1a36'
down_revision = 'c5a91d4e7b02'
branch_labels = None
depends_on = None

categoria = sa.Enum('ENLACE_CLIENTE', 'SITIO_WIFI', name='categoria_interrupcion')

#: Roles antes de este cambio (los necesita el downgrade).
ROLES_SIN_WIFI = ('ADMIN', 'DESPACHADOR', 'OPERADOR', 'AGENTE_FIBRA')


def upgrade():
    # PostgreSQL 12+ admite ADD VALUE dentro de la transaccion de la migracion
    # mientras el valor nuevo no se USE en ella; aqui solo se declara.
    op.execute(
        "ALTER TYPE rol_usuario ADD VALUE IF NOT EXISTS 'TECNICO_WIFI' AFTER 'AGENTE_FIBRA'"
    )

    categoria.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'interrupcion',
        sa.Column('categoria', categoria, nullable=False, server_default='ENLACE_CLIENTE'),
    )
    # El defecto solo hacia falta para las filas que ya existian; de aqui en
    # adelante lo pone el modelo.
    op.alter_column('interrupcion', 'categoria', existing_type=categoria, server_default=None)
    op.create_index(
        op.f('ix_interrupcion_categoria'), 'interrupcion', ['categoria'], unique=False
    )


def downgrade():
    op.drop_index(op.f('ix_interrupcion_categoria'), table_name='interrupcion')
    op.drop_column('interrupcion', 'categoria')
    categoria.drop(op.get_bind(), checkfirst=True)

    # A un enum de PostgreSQL no se le puede quitar un valor: se recrea el tipo
    # sin el. Los usuarios que solo eran tecnicos de wifi se quedan sin roles,
    # asi que primero se borra la fila del rol.
    op.execute("DELETE FROM usuario_rol WHERE rol = 'TECNICO_WIFI'")
    op.execute("ALTER TYPE rol_usuario RENAME TO rol_usuario_con_wifi")
    valores = ", ".join(f"'{rol}'" for rol in ROLES_SIN_WIFI)
    op.execute(f"CREATE TYPE rol_usuario AS ENUM ({valores})")
    op.execute(
        "ALTER TABLE usuario_rol ALTER COLUMN rol TYPE rol_usuario "
        "USING rol::text::rol_usuario"
    )
    op.execute("DROP TYPE rol_usuario_con_wifi")
