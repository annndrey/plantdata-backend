"""empty message

Revision ID: f50f2fbf4e19
Revises: 558cabb2c775
Create Date: 2020-01-31 04:37:18.832563

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'f50f2fbf4e19'
down_revision = '558cabb2c775'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('probe_data', 'value')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('probe_data', sa.Column('value', mysql.DECIMAL(precision=3, scale=0), nullable=True))
    # ### end Alembic commands ###
