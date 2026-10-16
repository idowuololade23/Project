"""Baseline schema used by the original InsightLens MVP.

Revision ID: 0001_legacy_schema
Revises:
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_legacy_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("page_title", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_review", sa.Boolean(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("weaknesses", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("business_insight", sa.Text(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("positive_percent", sa.Float(), nullable=True),
        sa.Column("neutral_percent", sa.Float(), nullable=True),
        sa.Column("negative_percent", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_content_type", "analysis", ["content_type"])
    op.create_index("ix_analysis_created_at", "analysis", ["created_at"])
    op.create_index("ix_analysis_is_review", "analysis", ["is_review"])
    op.create_index("ix_analysis_source_url", "analysis", ["source_url"])
    op.create_table(
        "aspect_mention",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("aspect", sa.String(length=100), nullable=False),
        sa.Column("sentiment", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analysis.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_aspect_mention_analysis_id", "aspect_mention", ["analysis_id"]
    )


def downgrade():
    op.drop_index("ix_aspect_mention_analysis_id", table_name="aspect_mention")
    op.drop_table("aspect_mention")
    op.drop_index("ix_analysis_source_url", table_name="analysis")
    op.drop_index("ix_analysis_is_review", table_name="analysis")
    op.drop_index("ix_analysis_created_at", table_name="analysis")
    op.drop_index("ix_analysis_content_type", table_name="analysis")
    op.drop_table("analysis")
