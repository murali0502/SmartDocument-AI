"""Store collection graph revisions, nodes, edges and source evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0006_knowledge_graph"
down_revision = "0005_ncm_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_versions",
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("id", sa.String(36), unique=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(40)),
        sa.CheckConstraint("status IN ('ready', 'failed')", name="ck_graph_version_status"),
    )
    op.create_index(
        "ix_graph_scope_sequence", "graph_versions", ["workspace_id", "scope", "sequence"]
    )
    op.create_table(
        "graph_nodes",
        sa.Column(
            "version_id",
            sa.String(36),
            sa.ForeignKey("graph_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(18), nullable=False),
        sa.Column("search_label", sa.String(240), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_graph_node_ordinal"),
    )
    op.create_table(
        "graph_node_documents",
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column("node_id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(
            ["version_id", "node_id"],
            ["graph_nodes.version_id", "graph_nodes.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_graph_node_document", "graph_node_documents", ["version_id", "document_id"])
    op.create_table(
        "graph_edges",
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("predicate", sa.String(24), nullable=False),
        sa.Column("kind", sa.String(18), nullable=False),
        sa.Column("validation", sa.String(24), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("traversable", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id", "source_id"],
            ["graph_nodes.version_id", "graph_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "target_id"],
            ["graph_nodes.version_id", "graph_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_graph_edge_ordinal"),
    )
    op.create_index(
        "ix_graph_source_ordinal", "graph_edges", ["version_id", "source_id", "ordinal"]
    )
    op.create_index(
        "ix_graph_target_ordinal", "graph_edges", ["version_id", "target_id", "ordinal"]
    )
    op.create_table(
        "graph_edge_evidence",
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column("edge_id", sa.String(36), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id", "edge_id"],
            ["graph_edges.version_id", "graph_edges.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_graph_evidence_document", "graph_edge_evidence", ["version_id", "document_id"]
    )


def downgrade() -> None:
    op.drop_table("graph_edge_evidence")
    op.drop_table("graph_edges")
    op.drop_table("graph_node_documents")
    op.drop_table("graph_nodes")
    op.drop_table("graph_versions")
