from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "offer_drafts",
        sa.Column("token", sa.String(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("tracker", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("catalog", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table("offer_drafts")
