"""The Alembic migrations make exactly the tables that models.py describes."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from stickyminutes import create_app, db
from stickyminutes.db import Base


def test_upgrade_on_an_empty_database_matches_the_models(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "fresh.sqlite"), "DATABASE_URL": None})
    with app.app_context():
        db.upgrade_db()
        db.upgrade_db()  # running it again changes nothing
        with db.engine().connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, Base.metadata)
            tables = set(inspect(connection).get_table_names())
    # Nothing left for "alembic revision --autogenerate" to write: the migrations and
    # the models agree. If this fails after changing models.py, make a new migration (AGENTS.md).
    assert differences == []
    assert set(Base.metadata.tables) | {"alembic_version"} == tables


def test_upgrade_db_command(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "cli.sqlite"), "DATABASE_URL": None})
    result = app.test_cli_runner().invoke(args=["upgrade-db"])
    assert result.exit_code == 0, result.output
    assert "up to date" in result.output


def test_bulk_deleted_parents_have_an_index_for_each_child():
    """Deleting a demo workspace cascades to every row under it. Each link to a parent that
    is deleted like that needs an index STARTING with the link's column, or the database reads
    the whole child table for every deleted parent (Tally Ho!'s lesson)."""
    for table in Base.metadata.tables.values():
        for key in table.foreign_keys:
            if key.ondelete not in ("CASCADE", "SET NULL"):
                continue
            column = key.parent
            covered = column.primary_key and list(table.primary_key.columns)[0] is column
            for index in table.indexes:
                if list(index.columns)[0] is column:
                    covered = True
            for constraint in table.constraints:
                columns = list(getattr(constraint, "columns", []))
                if columns and columns[0] is column and constraint.__class__.__name__ == "UniqueConstraint":
                    covered = True
            assert covered, f"{table.name}.{column.name} needs an index that starts with it"
