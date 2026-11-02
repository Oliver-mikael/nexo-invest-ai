"""tesis versionadas y watchlist (fase 7)

Revision ID: 5d91e7a3c6b8
Revises: 3a8f1c05d2b7
Create Date: 2026-11-02 21:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5d91e7a3c6b8'
down_revision: Union[str, None] = '3a8f1c05d2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'watchlist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'instrument_id', name='uq_watchlist_user_instrument'),
    )
    with op.batch_alter_table('watchlist_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watchlist_items_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_watchlist_items_instrument_id'), ['instrument_id'], unique=False)

    op.create_table(
        'investment_theses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('horizon', sa.String(length=8), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('hypothesis', sa.Text(), nullable=False),
        sa.Column('invalidation_conditions', sa.JSON(), nullable=False),
        sa.Column('uncertainty_level', sa.String(length=12), nullable=False),
        sa.Column('missing_info', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('entry_target', sa.Numeric(24, 10), nullable=True),
        sa.Column('exit_target', sa.Numeric(24, 10), nullable=True),
        sa.Column('version_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('investment_theses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_investment_theses_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_investment_theses_instrument_id'), ['instrument_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_investment_theses_status'), ['status'], unique=False)

    op.create_table(
        'thesis_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('thesis_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('hypothesis', sa.Text(), nullable=False),
        sa.Column('invalidation_conditions', sa.JSON(), nullable=False),
        sa.Column('uncertainty_level', sa.String(length=12), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['thesis_id'], ['investment_theses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('thesis_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_thesis_versions_thesis_id'), ['thesis_id'], unique=False)

    op.create_table(
        'thesis_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('thesis_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('detected_by', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['thesis_id'], ['investment_theses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('thesis_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_thesis_events_thesis_id'), ['thesis_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_thesis_events_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_thesis_events_created_at'), ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('thesis_events')
    op.drop_table('thesis_versions')
    op.drop_table('investment_theses')
    op.drop_table('watchlist_items')
