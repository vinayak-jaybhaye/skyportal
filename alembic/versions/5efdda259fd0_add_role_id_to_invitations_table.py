"""Add role_id to invitations table

Revision ID: 5efdda259fd0
Revises: c0e0173c90b0
Create Date: 2021-05-17 12:43:50.376261

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5efdda259fd0'
down_revision = 'c0e0173c90b0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('invitations', sa.Column('role_id', sa.String(), nullable=False))
    op.create_foreign_key(None, 'invitations', 'roles', ['role_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'invitations', type_='foreignkey')
    op.drop_column('invitations', 'role_id')
    # ### end Alembic commands ###
