import os
import sqlite3
from pathlib import Path
from typing import Any


CREATE_SQLITE_FAVORITES_TABLE = """CREATE TABLE IF NOT EXISTS favorites (
    discord_user_id TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    game_name TEXT NOT NULL,
    root_place_id TEXT,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_user_id, universe_id)
)"""

CREATE_POSTGRES_FAVORITES_TABLE = """CREATE TABLE IF NOT EXISTS favorites (
    discord_user_id TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    game_name TEXT NOT NULL,
    root_place_id TEXT,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_user_id, universe_id)
)"""


class FavoriteStore:
    """Stores Discord users' game favorites in Postgres or local SQLite."""

    def __init__(self) -> None:
        self.pool: Any | None = None
        self.sqlite: sqlite3.Connection | None = None
        database_url = os.getenv("DATABASE_URL", "").strip()

        if database_url:
            from psycopg_pool import ConnectionPool

            self.pool = ConnectionPool(
                conninfo=database_url,
                min_size=0,
                max_size=2,
                timeout=15,
                open=False,
            )
            self.pool.open(wait=True)
            with self.pool.connection() as connection:
                connection.execute(CREATE_POSTGRES_FAVORITES_TABLE)
            return

        database_path = os.getenv("FAVORITES_DB_PATH", "").strip()
        if not database_path:
            database_path = str(Path(__file__).with_name("favorites.sqlite3"))
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.sqlite = sqlite3.connect(database_path)
        self.sqlite.execute(CREATE_SQLITE_FAVORITES_TABLE)
        self.sqlite.commit()

    def add(
        self, discord_user_id: str, universe_id: str, game_name: str, root_place_id: str
    ) -> bool:
        values = (discord_user_id, universe_id, game_name, root_place_id)
        if self.pool:
            with self.pool.connection() as connection:
                result = connection.execute(
                    """INSERT INTO favorites
                    (discord_user_id, universe_id, game_name, root_place_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (discord_user_id, universe_id) DO NOTHING
                    RETURNING universe_id""",
                    values,
                ).fetchone()
                return result is not None

        assert self.sqlite is not None
        cursor = self.sqlite.execute(
            """INSERT OR IGNORE INTO favorites
            (discord_user_id, universe_id, game_name, root_place_id)
            VALUES (?, ?, ?, ?)""",
            values,
        )
        self.sqlite.commit()
        return cursor.rowcount > 0

    def remove(self, discord_user_id: str, universe_id: str) -> bool:
        if self.pool:
            with self.pool.connection() as connection:
                result = connection.execute(
                    "DELETE FROM favorites WHERE discord_user_id = %s AND universe_id = %s RETURNING universe_id",
                    (discord_user_id, universe_id),
                ).fetchone()
                return result is not None

        assert self.sqlite is not None
        cursor = self.sqlite.execute(
            "DELETE FROM favorites WHERE discord_user_id = ? AND universe_id = ?",
            (discord_user_id, universe_id),
        )
        self.sqlite.commit()
        return cursor.rowcount > 0

    def list_for_user(
        self, discord_user_id: str, limit: int = 25
    ) -> list[tuple[str, str, str | None]]:
        if self.pool:
            with self.pool.connection() as connection:
                rows = connection.execute(
                    """SELECT universe_id, game_name, root_place_id
                    FROM favorites WHERE discord_user_id = %s
                    ORDER BY added_at DESC LIMIT %s""",
                    (discord_user_id, limit),
                ).fetchall()
                return [tuple(row) for row in rows]

        assert self.sqlite is not None
        rows = self.sqlite.execute(
            """SELECT universe_id, game_name, root_place_id
            FROM favorites WHERE discord_user_id = ?
            ORDER BY added_at DESC LIMIT ?""",
            (discord_user_id, limit),
        ).fetchall()
        return rows

    def search_for_user(
        self, discord_user_id: str, query: str, limit: int = 25
    ) -> list[tuple[str, str]]:
        query = query.strip().casefold()
        rows = self.list_for_user(discord_user_id, limit=100)
        matches = [
            (universe_id, game_name)
            for universe_id, game_name, _ in rows
            if not query
            or query in game_name.casefold()
            or query in universe_id
        ]
        return matches[:limit]

    def close(self) -> None:
        if self.pool:
            self.pool.close()
            self.pool = None
        if self.sqlite:
            self.sqlite.close()
            self.sqlite = None
