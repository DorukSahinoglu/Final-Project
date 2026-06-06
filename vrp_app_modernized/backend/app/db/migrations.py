from __future__ import annotations

from sqlalchemy import text


def ensure_sqlite_compat_columns(engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    _ensure_columns(
        engine,
        "addresses",
        {
            "notes": "TEXT",
        },
    )
    _ensure_columns(
        engine,
        "fleet_units",
        {
            "max_route_distance_km": "FLOAT",
            "max_route_time_min": "FLOAT",
        },
    )


def _ensure_columns(engine, table_name: str, columns: dict[str, str]) -> None:
    with engine.begin() as connection:
        existing = {
            row[1]
            for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        }
        for column_name, column_type in columns.items():
            if column_name in existing:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
