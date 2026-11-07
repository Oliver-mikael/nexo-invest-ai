"""alertas automatizadas y estado del planificador (fase 6)

Revision ID: 3a8f1c05d2b7
Revises: 2b7d5f3a91e4
Create Date: 2026-11-02 20:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3a8f1c05d2b7'
down_revision: Union[str, None] = '2b7d5f3a91e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'alert_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('threshold', sa.Numeric(24, 10), nullable=True),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('alert_rules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alert_rules_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_rules_instrument_id'), ['instrument_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_rules_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_rules_active'), ['active'], unique=False)

    op.create_table(
        'alert_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('rule_id', sa.Integer(), nullable=True),
        sa.Column('instrument_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('severity', sa.String(length=12), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=191), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key', name='uq_alert_event_dedupe'),
    )
    with op.batch_alter_table('alert_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alert_events_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_events_rule_id'), ['rule_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_events_instrument_id'), ['instrument_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_events_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_events_created_at'), ['created_at'], unique=False)

    op.create_table(
        'system_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('system_state', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_system_state_key'), ['key'], unique=True)


def downgrade() -> None:
    op.drop_table('system_state')
    op.drop_table('alert_events')
    op.drop_table('alert_rules')
