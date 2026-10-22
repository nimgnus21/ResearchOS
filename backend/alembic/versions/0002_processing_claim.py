"""Track when processing started so stale jobs can be recovered without double-processing.

Revision ID: 0002_processing_claim
"""
from alembic import op

revision = "0002_processing_claim"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE documents ADD COLUMN processing_started_at timestamptz")


def downgrade():
    op.execute("ALTER TABLE documents DROP COLUMN processing_started_at")
