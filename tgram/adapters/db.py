import sqlite3
from pathlib import Path
import sqlite_vec

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def get_connection(db_path: Path | str, load_vec: bool = False) -> sqlite3.Connection:
    """Return a SQLite connection configured with production WAL and concurrency pragmas."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row

    # Concurrency and performance pragmas
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")  # wait up to 10s on lock contention
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -64000;")   # 64 MB page cache

    if load_vec:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

    return conn


def ensure_schema(db_path: Path | str) -> int:
    """Run pending SQLite migrations idempotently based on schema_version.

    Returns the number of newly applied migrations.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with get_connection(db_path) as conn:
        # 1. Ensure schema_version table exists
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );"""
        )

        # 2. Check applied versions
        applied_versions = {
            r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()
        }

        # Backward compatibility for legacy databases where 004/005 were applied before schema_version logging
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "embeddings" in tables:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(embeddings)").fetchall()}
            if "chunk_idx" in cols:
                for v in (4, 5):
                    if v not in applied_versions:
                        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (v,))
                        applied_versions.add(v)

        # 3. Discover and sort migration scripts
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        applied_count = 0

        for sql_file in migration_files:
            # Extract numeric version from filename (e.g. '001_initial_schema.sql' -> 1)
            prefix = sql_file.name.split("_")[0]
            if not prefix.isdigit():
                continue
            version = int(prefix)

            if version in applied_versions:
                continue

            # Special safeguard for 005 if already applied in previous session
            if sql_file.name == "005_embeddings_chunked.sql" and "embeddings" in tables:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(embeddings)").fetchall()}
                if "chunk_idx" in cols:
                    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (version,))
                    applied_versions.add(version)
                    continue

            # Execute migration in transaction
            sql = sql_file.read_text()
            conn.executescript(sql)
            conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (version,))
            applied_versions.add(version)
            applied_count += 1

        return applied_count
