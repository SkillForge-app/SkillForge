"""Add design_runs: one row per run of the AI pipeline

Revision ID: b4e7c91a2d58
Revises: 3520f9f375de
Create Date: 2026-11-16 22:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4e7c91a2d58'
down_revision: Union[str, Sequence[str], None] = '3520f9f375de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('design_runs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('request_text', sa.Text(), nullable=False),
    sa.Column('selected_targets', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('status', sa.String(length=30), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('step', sa.String(length=30), nullable=True),
    sa.Column('analyzed', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('progress', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('issues', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('usage', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('user_message', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('spec_version_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'needs_input', 'completed', 'blocked', 'retry_later', 'failed')", name='chk_design_run_status'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name='fk_design_runs_project'),
    sa.ForeignKeyConstraint(['spec_version_id'], ['spec_versions.id'], name='fk_design_runs_spec_version'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_design_runs_project_id', 'design_runs', ['project_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_design_runs_project_id', table_name='design_runs')
    op.drop_table('design_runs')
