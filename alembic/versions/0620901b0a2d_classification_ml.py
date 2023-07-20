"""classification_ml

Revision ID: 0620901b0a2d
Revises: 849e70f9a857
Create Date: 2023-07-20 10:55:33.259729

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0620901b0a2d'
down_revision = '849e70f9a857'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        'classifications',
        sa.Column('ml', sa.Boolean(), server_default='false', nullable=False),
    )
    op.create_index(
        op.f('ix_classifications_ml'), 'classifications', ['ml'], unique=False
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_classifications_ml'), table_name='classifications')
    op.drop_column('classifications', 'ml')
    # ### end Alembic commands ###
