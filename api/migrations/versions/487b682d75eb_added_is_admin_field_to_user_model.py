"""Added is_admin field to User model

Revision ID: 487b682d75eb
Revises: 2f0974a562a5
Create Date: 2019-11-07 13:23:34.572009

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '487b682d75eb'
down_revision = '2f0974a562a5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user', sa.Column('is_admin', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user', 'is_admin')
    # ### end Alembic commands ###
