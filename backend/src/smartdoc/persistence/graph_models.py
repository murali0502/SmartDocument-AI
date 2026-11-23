from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from smartdoc.persistence.models import Base


class GraphVersion(Base):
    __tablename__ = "graph_versions"
    __table_args__ = (
        CheckConstraint("status IN ('ready', 'failed')", name="ck_graph_version_status"),
        Index("ix_graph_scope_sequence", "workspace_id", "scope", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(primary_key=True)
    id: Mapped[str] = mapped_column(String(36), unique=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime]
    sources: Mapped[list] = mapped_column(JSON)
    node_count: Mapped[int]
    edge_count: Mapped[int]
    error: Mapped[str | None] = mapped_column(String(40))


class GraphNodeRow(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("version_id", "ordinal", name="uq_graph_node_ordinal"),)

    version_id: Mapped[str] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ordinal: Mapped[int]
    kind: Mapped[str] = mapped_column(String(18))
    search_label: Mapped[str] = mapped_column(String(240))
    payload: Mapped[dict] = mapped_column(JSON)


class GraphMembership(Base):
    __tablename__ = "graph_node_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "node_id"],
            ["graph_nodes.version_id", "graph_nodes.id"],
            ondelete="CASCADE",
        ),
        Index("ix_graph_node_document", "version_id", "document_id"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class GraphEdgeRow(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "source_id"],
            ["graph_nodes.version_id", "graph_nodes.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["version_id", "target_id"],
            ["graph_nodes.version_id", "graph_nodes.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("version_id", "ordinal", name="uq_graph_edge_ordinal"),
        Index("ix_graph_source_ordinal", "version_id", "source_id", "ordinal"),
        Index("ix_graph_target_ordinal", "version_id", "target_id", "ordinal"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ordinal: Mapped[int]
    source_id: Mapped[str] = mapped_column(String(36))
    target_id: Mapped[str] = mapped_column(String(36))
    predicate: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(18))
    validation: Mapped[str] = mapped_column(String(24))
    method: Mapped[str] = mapped_column(String(40))
    traversable: Mapped[bool]
    payload: Mapped[dict] = mapped_column(JSON)


class GraphEvidence(Base):
    __tablename__ = "graph_edge_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "edge_id"],
            ["graph_edges.version_id", "graph_edges.id"],
            ondelete="CASCADE",
        ),
        Index("ix_graph_evidence_document", "version_id", "document_id"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON)
