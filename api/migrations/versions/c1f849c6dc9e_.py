"""empty message

Revision ID: c1f849c6dc9e
Revises: f28c7cd8bf98
Create Date: 2020-01-31 11:59:10.488856

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'c1f849c6dc9e'
down_revision = 'f28c7cd8bf98'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('probes_types')
    op.add_column('probe_data', sa.Column('prtype_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'probe_data', 'sensor_type', ['prtype_id'], ['id'])
    op.add_column('sensor_type', sa.Column('ptype', sa.String(length=200), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('sensor_type', 'ptype')
    op.drop_constraint(None, 'probe_data', type_='foreignkey')
    op.drop_column('probe_data', 'prtype_id')
    op.create_table('probes_types',
    sa.Column('sensor_type_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True),
    sa.Column('probe_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['probe_id'], ['probe.id'], name='probes_types_ibfk_1'),
    sa.ForeignKeyConstraint(['sensor_type_id'], ['sensor_type.id'], name='probes_types_ibfk_2'),
    mysql_default_charset='utf8',
    mysql_engine='InnoDB'
    )
    # ### end Alembic commands ###