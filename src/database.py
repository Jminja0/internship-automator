import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

# Anchored to the project, not the working directory, so the tool behaves the
# same no matter where it is launched from.
DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "applications.db"


def get_connection():
    """Create and return a connection to the SQLite database."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    return connection


@contextmanager
def transaction():
    """Commit on success, roll back on error, and always close the connection.

    (`with sqlite3.connect(...)` only manages the transaction; it never
    closes the connection.)
    """
    with closing(get_connection()) as connection:
        with connection:
            yield connection


def initialize_database():
    """Create the applications table if it doesn't already exist."""

    with transaction() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                position TEXT NOT NULL,
                locations TEXT,
                apply_url TEXT NOT NULL,
                date_posted INTEGER,
                source TEXT,
                source_job_id TEXT,
                posted_at TEXT,
                source_updated_at TEXT,
                last_seen TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'new',
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(applications)")
        }
        migrations = {
            "source": "TEXT",
            "source_job_id": "TEXT",
            "posted_at": "TEXT",
            "source_updated_at": "TEXT",
            "last_seen": "TIMESTAMP",
        }
        for column, column_type in migrations.items():
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE applications ADD COLUMN {column} {column_type}"
                )
        # `apply` and `resync` both query by status.
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_status "
            "ON applications(status)"
        )


def get_first_seen_map():
    """Return {job id: first_seen} for every stored job."""

    with closing(get_connection()) as connection:
        rows = connection.execute("SELECT id, first_seen FROM applications")
        return {row["id"]: row["first_seen"] for row in rows}


def save_internships(internships):
    """Insert new jobs and refresh source metadata without resetting status.

    Returns the number of jobs that were not already in the database.
    """

    if not internships:
        return 0

    with transaction() as connection:
        # One query up front instead of a SELECT per job.
        existing_ids = {
            row["id"] for row in connection.execute("SELECT id FROM applications")
        }
        added = sum(1 for job in internships if job["id"] not in existing_ids)

        connection.executemany(
            """
            INSERT INTO applications (
                id,
                company,
                position,
                locations,
                apply_url,
                date_posted,
                source,
                source_job_id,
                posted_at,
                source_updated_at,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                company = excluded.company,
                position = excluded.position,
                locations = excluded.locations,
                apply_url = excluded.apply_url,
                date_posted = excluded.date_posted,
                source = excluded.source,
                source_job_id = excluded.source_job_id,
                posted_at = excluded.posted_at,
                source_updated_at = excluded.source_updated_at,
                last_seen = CURRENT_TIMESTAMP
            """,
            [
                (
                    job["id"],
                    job["company_name"],
                    job["title"],
                    ", ".join(job.get("locations", [])),
                    job["url"],
                    job.get("date_posted"),
                    job.get("source"),
                    job.get("source_job_id"),
                    job.get("posted_at"),
                    job.get("source_updated_at"),
                )
                for job in internships
            ],
        )

    return added


def update_status(application_id, status):
    """Update an application's status (e.g. 'new' -> 'filled')."""

    with transaction() as connection:
        connection.execute(
            """
            UPDATE applications
            SET status = ?, last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, application_id),
        )


def get_applications(status=None):
    """Return applications, optionally filtered by status."""

    query = "SELECT * FROM applications"
    params = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY first_seen DESC"

    with closing(get_connection()) as connection:
        return connection.execute(query, params).fetchall()
