import sqlite3
from pathlib import Path


DATABASE_PATH = Path("data/applications.db")


def get_connection():
    """Create and return a connection to the SQLite database."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    return connection


def initialize_database():
    """Create the applications table if it doesn't already exist."""

    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                position TEXT NOT NULL,
                locations TEXT,
                apply_url TEXT NOT NULL,
                date_posted INTEGER,
                status TEXT NOT NULL DEFAULT 'new',
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
def save_internships(internships):
    """Add internships that aren't already in the database."""

    added = 0

    with get_connection() as connection:
        for internship in internships:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO applications (
                    id,
                    company,
                    position,
                    locations,
                    apply_url,
                    date_posted
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    internship["id"],
                    internship["company_name"],
                    internship["title"],
                    ", ".join(internship.get("locations", [])),
                    internship["url"],
                    internship.get("date_posted"),
                ),
            )

            if cursor.rowcount > 0:
                added += 1

    return added

def update_status(application_id, status):
    """Update an application's status (e.g. 'new' -> 'filled')."""

    with get_connection() as connection:
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

    with get_connection() as connection:
        if status:
            rows = connection.execute(
                """
                SELECT *
                FROM applications
                WHERE status = ?
                ORDER BY first_seen DESC
                """,
                (status,),
            ).fetchall()

        else:
            rows = connection.execute(
                """
                SELECT *
                FROM applications
                ORDER BY first_seen DESC
                """
            ).fetchall()

    return rows