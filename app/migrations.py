"""Additive schema upgrades for existing SQLite databases.

`Base.metadata.create_all()` creates missing tables but never changes
existing ones. Columns added after the first release are added here, so an
existing database keeps working without a migration tool.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# (table, column, column definition)
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "token_version", "INTEGER NOT NULL DEFAULT 0"),
]


def upgrade(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, definition in _ADDED_COLUMNS:
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
