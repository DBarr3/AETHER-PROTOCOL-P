"""
AetherCloud-L — Searchable File Index
Fast file search and metadata indexing.
Aether Systems LLC — Patent Pending
"""

import sqlite3
import time
import hashlib
from pathlib import Path
from typing import Optional


class VaultIndex:
    """
    Searchable file index backed by SQLite.
    Provides fast lookups by name, category, extension, and content hash.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the index table if it doesn't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS file_index (
                path        TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                extension   TEXT,
                category    TEXT,
                size        INTEGER,
                content_hash TEXT,
                modified    REAL,
                indexed_at  REAL,
                tags        TEXT DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_name ON file_index(name);
            CREATE INDEX IF NOT EXISTS idx_extension ON file_index(extension);
            CREATE INDEX IF NOT EXISTS idx_category ON file_index(category);
            CREATE INDEX IF NOT EXISTS idx_content_hash ON file_index(content_hash);
        """)
        self._conn.commit()

    def upsert(
        self,
        path: str,
        name: str,
        extension: str,
        size: int,
        content_hash: str,
        modified: float,
        category: Optional[str] = None,
        tags: str = "",
    ) -> None:
        """Insert or update a file in the index."""
        self._conn.execute(
            """
            INSERT INTO file_index (path, name, extension, category, size,
                                     content_hash, modified, indexed_at, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name=excluded.name,
                extension=excluded.extension,
                category=excluded.category,
                size=excluded.size,
                content_hash=excluded.content_hash,
                modified=excluded.modified,
                indexed_at=excluded.indexed_at,
                tags=excluded.tags
            """,
            (path, name, extension, category, size, content_hash,
             modified, time.time(), tags),
        )
        self._conn.commit()

    def remove(self, path: str) -> None:
        """Remove a file from the index."""
        self._conn.execute("DELETE FROM file_index WHERE path = ?", (path,))
        self._conn.commit()

    def search(
        self,
        query: Optional[str] = None,
        extension: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Search the file index."""
        conditions = []
        params = []

        if query:
            conditions.append("(name LIKE ? OR path LIKE ? OR tags LIKE ?)")
            q = f"%{query}%"
            params.extend([q, q, q])
        if extension:
            conditions.append("extension = ?")
            params.append(extension)
        if category:
            conditions.append("category = ?")
            params.append(category)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM file_index {where} ORDER BY modified DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get(self, path: str) -> Optional[dict]:
        """Get a single file's index entry."""
        row = self._conn.execute(
            "SELECT * FROM file_index WHERE path = ?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        """Return total number of indexed files."""
        row = self._conn.execute("SELECT COUNT(*) FROM file_index").fetchone()
        return row[0]

    def reindex(self, vault_root: str) -> int:
        """Reindex all files in the vault."""
        root = Path(vault_root)
        count = 0
        for f in root.rglob("*"):
            if f.is_file():
                stat = f.stat()
                h = hashlib.sha256()
                try:
                    with open(f, "rb") as fh:
                        for chunk in iter(lambda: fh.read(8192), b""):
                            h.update(chunk)
                except OSError:
                    continue
                self.upsert(
                    path=str(f.relative_to(root)),
                    name=f.name,
                    extension=f.suffix.lower(),
                    size=stat.st_size,
                    content_hash=h.hexdigest(),
                    modified=stat.st_mtime,
                )
                count += 1
        return count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
