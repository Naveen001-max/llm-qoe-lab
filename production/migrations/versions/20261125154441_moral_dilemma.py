"""Add moral-dilemma consent and session state.

The initial migration builds tables from current SQLAlchemy metadata, which may
already include these models. Guard table and index creation so fresh installs
and databases created by the previous initial migration both upgrade safely.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261125154441"
down_revision = "0002_provider_model_metadata"
branch_labels = None
depends_on = None


def _table_names():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _ensure_index(table_name, index_name, columns):
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns)


def upgrade():
    if "experiment_consents" not in _table_names():
        op.create_table(
            "experiment_consents",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("experiment_id", sa.String(40), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("participant_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("consent_version", sa.String(40), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("experiment_id", "participant_id"),
        )
    _ensure_index("experiment_consents", "ix_experiment_consents_experiment_id", ["experiment_id"])
    _ensure_index("experiment_consents", "ix_experiment_consents_participant_id", ["participant_id"])

    if "moral_dilemma_sessions" not in _table_names():
        op.create_table(
            "moral_dilemma_sessions",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("experiment_id", sa.String(40), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assignment_id", sa.String(40), sa.ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("trace_id", sa.String(40), sa.ForeignKey("traces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("participant_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_version", sa.String(40), nullable=False),
            sa.Column("task_source_sha256", sa.String(64), nullable=False),
            sa.Column("active_stage", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(24), nullable=False, server_default="active"),
            sa.Column("transcript", sa.JSON(), nullable=False),
            sa.Column("final_reflection_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("assignment_id"),
            sa.UniqueConstraint("trace_id"),
        )
    _ensure_index("moral_dilemma_sessions", "ix_moral_dilemma_sessions_experiment_id", ["experiment_id"])
    _ensure_index("moral_dilemma_sessions", "ix_moral_dilemma_sessions_participant_id", ["participant_id"])
    _ensure_index("moral_dilemma_sessions", "ix_moral_dilemma_sessions_status", ["status"])


def downgrade():
    # These tables may have been created by 0001_initial via Base.metadata.
    # Do not drop shared schema objects during downgrade.
    pass
