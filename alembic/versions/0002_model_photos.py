"""model photos

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'model_photos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('make', sa.String(length=80), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('file', sa.String(length=300), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('page_url', sa.Text(), nullable=True),
        sa.Column('author', sa.String(length=300), nullable=True),
        sa.Column('license', sa.String(length=80), nullable=True),
        sa.Column('license_url', sa.Text(), nullable=True),
        sa.Column('chosen_by', sa.String(length=10), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('make', 'model', name='uq_photo_make_model'),
    )


def downgrade() -> None:
    op.drop_table('model_photos')
