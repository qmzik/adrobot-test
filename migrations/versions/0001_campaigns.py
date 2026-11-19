from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade():
    op.create_table(
        "campaigns",
        sa.Column("token", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("offer", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("campaign_id", sa.Integer()),
        sa.Column("geo_id", sa.Integer()),
        sa.Column("offers_id", sa.Integer()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String()),
    )


def downgrade():
    op.drop_table("campaigns")
