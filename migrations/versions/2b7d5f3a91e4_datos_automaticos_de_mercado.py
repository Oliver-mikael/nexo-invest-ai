"""datos automáticos de mercado (fase 5): runs, caché, fundamentales, noticias

Revision ID: 2b7d5f3a91e4
Revises: 1a0119241c07
Create Date: 2026-10-31 23:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2b7d5f3a91e4'
down_revision: Union[str, None] = '1a0119241c07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'provider_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('category', sa.String(length=24), nullable=False),
        sa.Column('task_key', sa.String(length=191), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('request_count', sa.Integer(), nullable=False),
        sa.Column('items_fetched', sa.Integer(), nullable=False),
        sa.Column('items_stored', sa.Integer(), nullable=False),
        sa.Column('items_skipped', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('provider_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_provider_runs_provider'), ['provider'], unique=False)
        batch_op.create_index(batch_op.f('ix_provider_runs_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_provider_runs_task_key'), ['task_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_provider_runs_status'), ['status'], unique=False)

    op.create_table(
        'data_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cache_key', sa.String(length=191), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('category', sa.String(length=24), nullable=False),
        sa.Column('subject', sa.String(length=191), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('data_cache', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_data_cache_cache_key'), ['cache_key'], unique=True)
        batch_op.create_index(batch_op.f('ix_data_cache_provider'), ['provider'], unique=False)
        batch_op.create_index(batch_op.f('ix_data_cache_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_data_cache_expires_at'), ['expires_at'], unique=False)

    op.create_table(
        'fundamentals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=False),
        sa.Column('period_type', sa.String(length=16), nullable=False),
        sa.Column('fiscal_start', sa.Date(), nullable=True),
        sa.Column('fiscal_end', sa.Date(), nullable=False),
        sa.Column('reported_at', sa.Date(), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('revenue', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('net_income', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('ebitda', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('eps_diluted', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('shares_outstanding', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('total_debt', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('cash', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('free_cash_flow', sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('quality', sa.String(length=16), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'instrument_id', 'period_type', 'fiscal_end', 'source',
            name='uq_fundamental_instrument_period_source',
        ),
    )
    with op.batch_alter_table('fundamentals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fundamentals_instrument_id'), ['instrument_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_fundamentals_fiscal_end'), ['fiscal_end'], unique=False)
        batch_op.create_index(batch_op.f('ix_fundamentals_source'), ['source'], unique=False)

    op.create_table(
        'news_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=24), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('external_id', sa.String(length=191), nullable=False),
        sa.Column('quality', sa.String(length=16), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'external_id', name='uq_news_source_external'),
    )
    with op.batch_alter_table('news_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_news_items_instrument_id'), ['instrument_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_news_items_source'), ['source'], unique=False)

    with op.batch_alter_table('instruments', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'auto_sync_prices', sa.Boolean(), nullable=False, server_default=sa.text('0')
        ))

    with op.batch_alter_table('quotes', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'adjusted', sa.Boolean(), nullable=False, server_default=sa.text('0')
        ))

    with op.batch_alter_table('fx_rates', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'kind', sa.String(length=16), nullable=False, server_default='market'
        ))


def downgrade() -> None:
    with op.batch_alter_table('fx_rates', schema=None) as batch_op:
        batch_op.drop_column('kind')

    with op.batch_alter_table('quotes', schema=None) as batch_op:
        batch_op.drop_column('adjusted')

    with op.batch_alter_table('instruments', schema=None) as batch_op:
        batch_op.drop_column('auto_sync_prices')

    op.drop_table('news_items')
    op.drop_table('fundamentals')
    op.drop_table('data_cache')
    op.drop_table('provider_runs')
