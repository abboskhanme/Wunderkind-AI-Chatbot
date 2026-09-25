"""multiple funnels

SPEC §11.1 — additive, with backfill:
  * `funnels` table + the default funnel ("Asosiy voronka", slug `asosiy`, empty
    overrides → behaves exactly like before);
  * `funnel_id` (FK, NOT NULL after backfill to the default funnel) on
    funnel_entries, funnel_messages and funnel_files;
  * funnel_entries: tg_user_id unique → unique (tg_user_id, funnel_id) — one person
    may go through several funnels;
  * funnel_files: primary key key → (funnel_id, key) — one lead magnet per funnel;
  * all entries marked sheet_dirty so the Sheet gets its new "Voronka" column.
Downgrade deletes the non-default funnels' rows first, then restores the old shape.

Revision ID: cc521603ff79
Revises: 087311873265
Create Date: 2026-09-25 23:24:25.206976

"""
from typing import Sequence, Union

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'cc521603ff79'
down_revision: Union[str, Sequence[str], None] = '087311873265'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
_TABLES = ("funnel_entries", "funnel_messages", "funnel_files")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('funnels',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('slug', sa.String(length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('keywords', sa.Text(), server_default='', nullable=False),
    sa.Column('ig_media_ids', sa.Text(), server_default='', nullable=False),
    sa.Column('texts', _JSON, nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_index(op.f('ix_funnels_created_at'), 'funnels', ['created_at'], unique=False)
    op.create_index('uq_funnels_one_default', 'funnels', ['is_default'], unique=True, postgresql_where=sa.text('is_default'), sqlite_where=sa.text('is_default'))

    default_id = uuid.uuid4()
    op.bulk_insert(sa.table(
        "funnels", sa.column("id", sa.Uuid()), sa.column("name", sa.String()),
        sa.column("slug", sa.String()), sa.column("is_active", sa.Boolean()),
        sa.column("is_default", sa.Boolean()), sa.column("keywords", sa.Text()),
        sa.column("ig_media_ids", sa.Text()), sa.column("texts", _JSON),
        sa.column("sort_order", sa.Integer()),
    ), [{"id": default_id, "name": "Asosiy voronka", "slug": "asosiy", "is_active": True,
         "is_default": True, "keywords": "", "ig_media_ids": "", "texts": {}, "sort_order": 0}])

    # Backfill: everything that exists belongs to the default funnel
    for table in _TABLES:
        op.add_column(table, sa.Column('funnel_id', sa.Uuid(), nullable=True))
        op.execute(sa.table(table, sa.column("funnel_id", sa.Uuid()))
                   .update().values(funnel_id=default_id))
        op.alter_column(table, 'funnel_id', nullable=False)

    op.create_foreign_key('funnel_entries_funnel_id_fkey', 'funnel_entries', 'funnels', ['funnel_id'], ['id'])
    op.create_index(op.f('ix_funnel_entries_funnel_id'), 'funnel_entries', ['funnel_id'], unique=False)
    op.drop_constraint('funnel_entries_tg_user_id_key', 'funnel_entries', type_='unique')
    op.create_unique_constraint('uq_funnel_entries_tg_user_funnel', 'funnel_entries', ['tg_user_id', 'funnel_id'])

    op.create_foreign_key('funnel_messages_funnel_id_fkey', 'funnel_messages', 'funnels', ['funnel_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_funnel_messages_funnel_id'), 'funnel_messages', ['funnel_id'], unique=False)

    op.create_foreign_key('funnel_files_funnel_id_fkey', 'funnel_files', 'funnels', ['funnel_id'], ['id'], ondelete='CASCADE')
    op.drop_constraint('funnel_files_pkey', 'funnel_files', type_='primary')
    op.create_primary_key('funnel_files_pkey', 'funnel_files', ['funnel_id', 'key'])

    # The Sheet gets the new "Voronka" column on the next sync
    op.execute("UPDATE funnel_entries SET sheet_dirty = true")


def downgrade() -> None:
    """Downgrade schema: only the default funnel's data survives (SPEC §11.1)."""
    default_id = op.get_bind().execute(
        sa.text("SELECT id FROM funnels WHERE is_default")).scalar()
    if default_id is not None:
        others = sa.bindparam("fid", value=default_id, type_=sa.Uuid())
        # Bookings and deliveries go with their entries/messages (ON DELETE CASCADE)
        for table in _TABLES:
            op.execute(sa.text(f"DELETE FROM {table} WHERE funnel_id <> :fid").bindparams(others))

    op.drop_constraint('funnel_files_pkey', 'funnel_files', type_='primary')
    op.create_primary_key('funnel_files_pkey', 'funnel_files', ['key'])
    op.drop_constraint('funnel_files_funnel_id_fkey', 'funnel_files', type_='foreignkey')
    op.drop_column('funnel_files', 'funnel_id')

    op.drop_constraint('funnel_messages_funnel_id_fkey', 'funnel_messages', type_='foreignkey')
    op.drop_index(op.f('ix_funnel_messages_funnel_id'), table_name='funnel_messages')
    op.drop_column('funnel_messages', 'funnel_id')

    op.drop_constraint('uq_funnel_entries_tg_user_funnel', 'funnel_entries', type_='unique')
    op.create_unique_constraint('funnel_entries_tg_user_id_key', 'funnel_entries', ['tg_user_id'])
    op.drop_constraint('funnel_entries_funnel_id_fkey', 'funnel_entries', type_='foreignkey')
    op.drop_index(op.f('ix_funnel_entries_funnel_id'), table_name='funnel_entries')
    op.drop_column('funnel_entries', 'funnel_id')

    op.drop_index('uq_funnels_one_default', table_name='funnels', postgresql_where=sa.text('is_default'), sqlite_where=sa.text('is_default'))
    op.drop_index(op.f('ix_funnels_created_at'), table_name='funnels')
    op.drop_table('funnels')
