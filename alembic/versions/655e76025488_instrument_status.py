"""instrument_status

Revision ID: 655e76025488
Revises: 16c6e68ae49b
Create Date: 2023-06-12 15:06:29.984901

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '655e76025488'
down_revision = '16c6e68ae49b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        'instruments',
        sa.Column('status', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'instruments', sa.Column('last_status_update', sa.DateTime(), nullable=True)
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('instruments', 'last_status_update')
    op.drop_column('instruments', 'status')
    # ### end Alembic commands ###
