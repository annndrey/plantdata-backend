"""empty message

Revision ID: 558cabb2c775
Revises: a01c436142a0
Create Date: 2020-01-31 03:43:53.916114

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '558cabb2c775'
down_revision = 'a01c436142a0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('probe', sa.Column('data_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'probe', 'data', ['data_id'], ['id'])
    op.drop_constraint('probe_data_ibfk_2', 'probe_data', type_='foreignkey')
    op.drop_column('probe_data', 'data_id')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('probe_data', sa.Column('data_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.create_foreign_key('probe_data_ibfk_2', 'probe_data', 'data', ['data_id'], ['id'])
    op.drop_constraint(None, 'probe', type_='foreignkey')
    op.drop_column('probe', 'data_id')
    # ### end Alembic commands ###
