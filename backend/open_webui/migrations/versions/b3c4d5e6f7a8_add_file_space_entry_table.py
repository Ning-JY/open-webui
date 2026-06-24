"""Add file_space_entry table.

Revision ID: b3c4d5e6f7a8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-24 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from open_webui.migrations.util import get_existing_tables

revision: str = 'b3c4d5e6f7a8'
down_revision: str | None = 'c2d3e4f5a6b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_tables = set(get_existing_tables())

    if 'file_space_entry' not in existing_tables:
        op.create_table(
            'file_space_entry',
            sa.Column('id', sa.Text(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=True),
            sa.Column('session_id', sa.String(), nullable=True),
            sa.Column('conversation_id', sa.String(), nullable=True),
            sa.Column('conversation_title', sa.Text(), nullable=True),
            sa.Column('filename', sa.Text(), nullable=False),
            sa.Column('file_path', sa.Text(), nullable=True),
            sa.Column('file_size', sa.BigInteger(), nullable=True),
            sa.Column('mime_type', sa.Text(), nullable=True),
            sa.Column('file_type', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_file_space_user_id', 'file_space_entry', ['user_id'])
        op.create_index('idx_file_space_session_id', 'file_space_entry', ['session_id'])
        op.create_index('idx_file_space_conversation_id', 'file_space_entry', ['conversation_id'])
        op.create_index('idx_file_space_created_at', 'file_space_entry', ['created_at'])


def downgrade() -> None:
    existing_tables = set(get_existing_tables())

    if 'file_space_entry' in existing_tables:
        op.drop_index('idx_file_space_created_at', table_name='file_space_entry')
        op.drop_index('idx_file_space_conversation_id', table_name='file_space_entry')
        op.drop_index('idx_file_space_session_id', table_name='file_space_entry')
        op.drop_index('idx_file_space_user_id', table_name='file_space_entry')
        op.drop_table('file_space_entry')
