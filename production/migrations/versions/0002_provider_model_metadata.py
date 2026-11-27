
from alembic import op
import sqlalchemy as sa


revision = "0002_provider_model_metadata"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    table_name = "model_snapshots"

    if table_name not in inspector.get_table_names():
        raise RuntimeError(
            "model_snapshots table does not exist. "
            "Run the initial migration before this migration."
        )

    existing_columns = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }

    # Add provider metadata when the database does not already have it.
    if "provider" not in existing_columns:
        op.add_column(
            table_name,
            sa.Column(
                "provider",
                sa.String(length=32),
                nullable=False,
                server_default="vllm",
            ),
        )

    if "model_id" not in existing_columns:
        op.add_column(
            table_name,
            sa.Column(
                "model_id",
                sa.String(length=240),
                nullable=False,
                server_default="unknown",
            ),
        )

    # Preserve useful model identifiers for records created before
    # provider-neutral metadata was introduced.
    op.execute(
        sa.text(
            """
            UPDATE model_snapshots
            SET model_id = repository
            WHERE model_id = 'unknown'
              AND repository IS NOT NULL
              AND repository <> ''
            """
        )
    )

    # Remove database-level defaults. New records should obtain their
    # defaults from the SQLAlchemy model definition.
    inspector = sa.inspect(connection)
    columns = {
        column["name"]: column
        for column in inspector.get_columns(table_name)
    }

    for column_name in ("provider", "model_id"):
        column = columns.get(column_name)

        if column and column.get("default") is not None:
            op.alter_column(
                table_name,
                column_name,
                server_default=None,
            )


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    table_name = "model_snapshots"

    if table_name not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }

    # Drop only columns introduced by this migration.
    if "model_id" in existing_columns:
        op.drop_column(table_name, "model_id")

    if "provider" in existing_columns:
        op.drop_column(table_name, "provider")
