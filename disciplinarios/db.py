import sqlite3
from pathlib import Path
import re

import click
from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    schema_path = Path(__file__).with_name("schema.sql")
    db.executescript(schema_path.read_text(encoding="utf-8"))
    migrate_db(db)
    db.commit()


def _table_columns(db, table_name: str) -> set[str]:
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def migrate_db(db):
    user_columns = _table_columns(db, "users")
    if "email" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "display_name" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
    if "is_active" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "last_login_at" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")

    case_columns = _table_columns(db, "cases")
    if "instructor_email" not in case_columns:
        db.execute("ALTER TABLE cases ADD COLUMN instructor_email TEXT")

    generated_document_columns = _table_columns(db, "generated_documents")
    if "doc_number" not in generated_document_columns:
        db.execute("ALTER TABLE generated_documents ADD COLUMN doc_number TEXT")
    if "version_number" not in generated_document_columns:
        db.execute("ALTER TABLE generated_documents ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1")
    if "is_latest" not in generated_document_columns:
        db.execute("ALTER TABLE generated_documents ADD COLUMN is_latest INTEGER NOT NULL DEFAULT 1")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS signature_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_document_id INTEGER NOT NULL UNIQUE,
            external_document_id TEXT,
            signer_name TEXT NOT NULL,
            signer_email TEXT NOT NULL,
            signer_role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_send',
            pdf_path TEXT,
            requested_by_user_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            completed_at TEXT,
            last_error TEXT,
            FOREIGN KEY (generated_document_id) REFERENCES generated_documents(id) ON DELETE CASCADE,
            FOREIGN KEY (requested_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    signature_request_columns = _table_columns(db, "signature_requests")
    if "signed_pdf_path" not in signature_request_columns:
        db.execute("ALTER TABLE signature_requests ADD COLUMN signed_pdf_path TEXT")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS allowed_admin_emails (
            email TEXT PRIMARY KEY,
            added_by_user_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (added_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS intermediate_store (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            payload TEXT NOT NULL
        )
        """
    )

    backfill_generated_document_versions(db)


def backfill_generated_document_versions(db):
    rows = db.execute(
        """
        SELECT id, case_id, template_name, created_at
        FROM generated_documents
        ORDER BY case_id, created_at, id
        """
    ).fetchall()
    grouped_versions: dict[tuple[int, str], int] = {}
    latest_by_group: dict[tuple[int, str], int] = {}

    for row in rows:
        match = re.match(r"^\s*(\d{2})\b", row["template_name"] or "")
        doc_number = match.group(1) if match else ""
        group_key = (row["case_id"], doc_number or row["template_name"])
        version_number = grouped_versions.get(group_key, 0) + 1
        grouped_versions[group_key] = version_number
        latest_by_group[group_key] = row["id"]
        db.execute(
            """
            UPDATE generated_documents
            SET doc_number = ?, version_number = ?, is_latest = 0
            WHERE id = ?
            """,
            (doc_number, version_number, row["id"]),
        )

    for document_id in latest_by_group.values():
        db.execute(
            "UPDATE generated_documents SET is_latest = 1 WHERE id = ?",
            (document_id,),
        )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS login_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            requested_by_ip TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_login_tokens_email_created_at
        ON login_tokens (email, created_at)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_login_tokens_ip_created_at
        ON login_tokens (requested_by_ip, created_at)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_action_created_at
        ON audit_logs (entity_type, action, created_at)
        """
    )


def backfill_instructor_emails(db):
    from .directory import find_instructor

    rows = db.execute(
        """
        SELECT id, instructor_name
        FROM cases
        WHERE instructor_name IS NOT NULL
          AND instructor_name != ''
          AND (instructor_email IS NULL OR instructor_email = '')
        """
    ).fetchall()
    for row in rows:
        instructor = find_instructor(current_app.config["PROJECT_ROOT"], row["instructor_name"])
        if instructor and instructor["email"]:
            db.execute(
                "UPDATE cases SET instructor_email = ? WHERE id = ?",
                (instructor["email"], row["id"]),
            )


@click.command("init-db")
def init_db_command():
    init_db()
    click.echo("Base de datos inicializada.")


def init_app(app):
    from .auth import ensure_access_setup

    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

    with app.app_context():
        init_db()
        backfill_instructor_emails(get_db())
        ensure_access_setup()
        get_db().commit()
