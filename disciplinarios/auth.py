from __future__ import annotations

from datetime import datetime, timedelta, UTC
from email.message import EmailMessage
from functools import wraps
import hashlib
import os
import secrets
import smtplib

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from .db import get_db
from .directory import find_instructor, format_person_name, normalize_email

auth_bp = Blueprint("auth", __name__)

DEFAULT_ADMIN_EMAILS = (
    "josemanuel.rodriguez@edumelilla.es",
    "carlos.moya@edumelilla.es",
)

LOGIN_REQUEST_WINDOW_MINUTES = 15
LOGIN_REQUESTS_PER_EMAIL = 3
LOGIN_REQUESTS_PER_IP = 10
LOGIN_VERIFY_FAILURE_WINDOW_MINUTES = 15
LOGIN_VERIFY_FAILURES_PER_EMAIL = 5
LOGIN_VERIFY_FAILURES_PER_IP = 10
AUTH_EVENT_RETENTION_DAYS = 30
TOKEN_RETENTION_DAYS = 2

ACTIVE_INSTRUCTOR_STATUSES = (
    "iniciado",
    "notificado_inicio",
    "medidas_provisionales_propuesta",
    "medidas_provisionales",
    "citacion",
    "pliego_cargos",
    "audiencia",
    "notificado_propuesta_resolucion",
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def db_timestamp(value: datetime | None = None) -> str:
    return (value or utcnow()).strftime("%Y-%m-%d %H:%M:%S")


def auth_event_details(email: str, ip_address: str, note: str = "") -> str:
    details = [f"email={normalize_email(email)}", f"ip={ip_address or '-'}"]
    if note:
        details.append(f"note={note}")
    return "|".join(details)


def record_auth_event(action: str, email: str, ip_address: str, note: str = "") -> None:
    get_db().execute(
        """
        INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details, created_at)
        VALUES (NULL, ?, 'auth', NULL, ?, ?)
        """,
        (action, auth_event_details(email, ip_address, note), db_timestamp()),
    )


def recent_auth_event_count(action: str, *, email: str | None = None, ip_address: str | None = None, minutes: int) -> int:
    filters = ["entity_type = 'auth'", "action = ?", "created_at >= datetime('now', ?)"]
    params: list[str] = [action, f"-{minutes} minutes"]

    if email:
        filters.append("details LIKE ?")
        params.append(f"%email={normalize_email(email)}%")
    if ip_address:
        filters.append("details LIKE ?")
        params.append(f"%ip={ip_address}%")

    row = get_db().execute(
        f"SELECT COUNT(*) AS count FROM audit_logs WHERE {' AND '.join(filters)}",
        params,
    ).fetchone()
    return int(row["count"]) if row else 0


def recent_login_token_count(*, email: str | None = None, ip_address: str | None = None, minutes: int) -> int:
    filters = ["created_at >= datetime('now', ?)"]
    params: list[str] = [f"-{minutes} minutes"]

    if email:
        filters.append("email = ?")
        params.append(normalize_email(email))
    if ip_address:
        filters.append("requested_by_ip = ?")
        params.append(ip_address)

    row = get_db().execute(
        f"SELECT COUNT(*) AS count FROM login_tokens WHERE {' AND '.join(filters)}",
        params,
    ).fetchone()
    return int(row["count"]) if row else 0


def prune_auth_records() -> None:
    db = get_db()
    db.execute(
        "DELETE FROM login_tokens WHERE created_at < datetime('now', ?)",
        (f"-{TOKEN_RETENTION_DAYS} days",),
    )
    db.execute(
        """
        DELETE FROM audit_logs
        WHERE entity_type = 'auth'
          AND created_at < datetime('now', ?)
        """,
        (f"-{AUTH_EVENT_RETENTION_DAYS} days",),
    )


def request_rate_limited(email: str, ip_address: str) -> bool:
    return (
        recent_auth_event_count("login_request", email=email, minutes=LOGIN_REQUEST_WINDOW_MINUTES)
        >= LOGIN_REQUESTS_PER_EMAIL
        or recent_auth_event_count("login_request", ip_address=ip_address, minutes=LOGIN_REQUEST_WINDOW_MINUTES)
        >= LOGIN_REQUESTS_PER_IP
        or recent_login_token_count(email=email, minutes=LOGIN_REQUEST_WINDOW_MINUTES) >= LOGIN_REQUESTS_PER_EMAIL
        or recent_login_token_count(ip_address=ip_address, minutes=LOGIN_REQUEST_WINDOW_MINUTES) >= LOGIN_REQUESTS_PER_IP
    )


def verify_rate_limited(email: str, ip_address: str) -> bool:
    return (
        recent_auth_event_count(
            "login_verify_failed",
            email=email,
            minutes=LOGIN_VERIFY_FAILURE_WINDOW_MINUTES,
        )
        >= LOGIN_VERIFY_FAILURES_PER_EMAIL
        or recent_auth_event_count(
            "login_verify_failed",
            ip_address=ip_address,
            minutes=LOGIN_VERIFY_FAILURE_WINDOW_MINUTES,
        )
        >= LOGIN_VERIFY_FAILURES_PER_IP
    )


def send_email_message(to_email: str, subject: str, text_body: str) -> None:
    mail_host = current_app.config.get("MAIL_HOST", "").strip()
    mail_port = int(current_app.config.get("MAIL_PORT", 587))
    mail_username = current_app.config.get("MAIL_USERNAME", "").strip()
    mail_password = current_app.config.get("MAIL_PASSWORD", "").strip()
    mail_from = current_app.config.get("MAIL_FROM", "").strip() or mail_username or "no-reply@localhost"
    mail_use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))

    if not mail_host:
        print("\n=== EMAIL SIMULADO ===")
        print("PARA:", to_email)
        print("ASUNTO:", subject)
        print(text_body)
        print("======================\n")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = to_email
    message.set_content(text_body)

    try:
        with smtplib.SMTP(mail_host, mail_port, timeout=15) as smtp:
            if mail_use_tls:
                smtp.starttls()
            if mail_username:
                smtp.login(mail_username, mail_password)
            smtp.send_message(message)
    except Exception as exc:
        print("\n=== ERROR SMTP, EMAIL SIMULADO ===")
        print("ERROR:", repr(exc))
        print("PARA:", to_email)
        print("ASUNTO:", subject)
        print(text_body)
        print("=================================\n")


def upsert_user(email: str, role: str, display_name: str):
    db = get_db()
    normalized_email = normalize_email(email)
    existing = db.execute("SELECT id FROM users WHERE email = ?", (normalized_email,)).fetchone()
    if existing:
        db.execute(
            """
            UPDATE users
            SET display_name = ?, role = ?, is_active = 1
            WHERE email = ?
            """,
            (display_name, role, normalized_email),
        )
    else:
        db.execute(
            """
            INSERT INTO users (email, display_name, username, password_hash, role, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (normalized_email, display_name, normalized_email, "token-auth", role),
        )
    db.commit()
    return db.execute("SELECT id, email, display_name, role, is_active FROM users WHERE email = ?", (normalized_email,)).fetchone()


def instructor_has_active_cases(email: str) -> bool:
    normalized_email = normalize_email(email)
    if not normalized_email:
        return False
    placeholders = ", ".join("?" for _ in ACTIVE_INSTRUCTOR_STATUSES)
    row = get_db().execute(
        f"""
        SELECT COUNT(*) AS count
        FROM cases
        WHERE instructor_email = ?
          AND status IN ({placeholders})
        """,
        (normalized_email, *ACTIVE_INSTRUCTOR_STATUSES),
    ).fetchone()
    return bool(row and row["count"] > 0)


def resolve_access_profile(email: str):
    db = get_db()
    normalized_email = normalize_email(email)
    instructor = find_instructor(current_app.config["PROJECT_ROOT"], normalized_email)
    admin = db.execute(
        "SELECT email FROM allowed_admin_emails WHERE email = ?",
        (normalized_email,),
    ).fetchone()
    if admin:
        display_name = instructor["name"] if instructor else format_person_name(normalized_email.split("@", 1)[0].replace(".", " ")).title()
        return upsert_user(normalized_email, "admin", display_name.title())

    if instructor and instructor["email"] and instructor_has_active_cases(instructor["email"]):
        return upsert_user(instructor["email"], "instructor", instructor["name"])
    return None


@auth_bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return

    idle_minutes = int(current_app.config.get("SESSION_IDLE_MINUTES", 60))
    last_activity_at = session.get("last_activity_at")
    if last_activity_at:
        try:
            last_activity = datetime.fromisoformat(last_activity_at)
        except ValueError:
            session.clear()
            g.user = None
            return
        if last_activity + timedelta(minutes=idle_minutes) <= utcnow():
            session.clear()
            g.user = None
            return

    g.user = get_db().execute(
        "SELECT id, email, display_name, role, is_active FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if g.user is not None and not g.user["is_active"]:
        session.clear()
        g.user = None
    elif g.user is not None:
        session["last_activity_at"] = utcnow().isoformat()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(**kwargs):
        if g.user["role"] != "admin":
            flash("No tienes permisos para acceder a esta sección.", "error")
            return redirect(url_for("main.dashboard"))
        return view(**kwargs)

    return wrapped_view


def issue_login_token(email: str, requested_by_ip: str = "") -> None:
    db = get_db()
    raw_token = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = (utcnow() + timedelta(minutes=15)).isoformat()
    db.execute(
        """
        UPDATE login_tokens
        SET used_at = ?
        WHERE email = ? AND used_at IS NULL
        """,
        (db_timestamp(), normalize_email(email)),
    )
    db.execute(
        """
        INSERT INTO login_tokens (email, token_hash, expires_at, requested_by_ip)
        VALUES (?, ?, ?, ?)
        """,
        (normalize_email(email), token_hash(raw_token), expires_at, requested_by_ip),
    )
    db.commit()

    send_email_message(
        normalize_email(email),
        "Acceso a Expedientes disciplinarios",
        (
            "Se ha solicitado un acceso a Expedientes disciplinarios.\n\n"
            f"Tu código de acceso es: {raw_token}\n\n"
            "El código caduca en 15 minutos y solo se puede usar una vez."
        ),
    )


@auth_bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("main.dashboard"))

    prefilled_email = request.args.get("email", "").strip()
    if request.method == "POST":
        prune_auth_records()
        action = request.form.get("action", "request").strip()
        email = normalize_email(request.form["email"])
        ip_address = request.remote_addr or ""

        if action == "request":
            if request_rate_limited(email, ip_address):
                flash("Se han solicitado demasiados códigos. Espera unos minutos antes de volver a intentarlo.", "error")
                return redirect(url_for("auth.login", email=email))

            record_auth_event("login_request", email, ip_address)
            profile = resolve_access_profile(email)
            if profile:
                issue_login_token(email, ip_address)
            flash(
                "Si el correo está autorizado, se ha enviado un código de acceso de un solo uso.",
                "success",
            )
            return redirect(url_for("auth.login", email=email))

        raw_token = request.form.get("token", "").strip()
        if not raw_token:
            flash("Introduce el código de acceso.", "error")
            return redirect(url_for("auth.login", email=email))

        if verify_rate_limited(email, ip_address):
            flash("Demasiados intentos fallidos. Espera unos minutos o solicita un código nuevo.", "error")
            return redirect(url_for("auth.login", email=email))

        db = get_db()
        token_row = db.execute(
            """
            SELECT * FROM login_tokens
            WHERE email = ? AND token_hash = ? AND used_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (email, token_hash(raw_token)),
        ).fetchone()

        if token_row is None:
            record_auth_event("login_verify_failed", email, ip_address, "invalid_token")
            db.commit()
            flash("El código no es válido.", "error")
            return redirect(url_for("auth.login", email=email))

        expires_at = datetime.fromisoformat(token_row["expires_at"])
        if expires_at <= utcnow():
            record_auth_event("login_verify_failed", email, ip_address, "expired_token")
            db.commit()
            flash("El código ha caducado. Solicita uno nuevo.", "error")
            return redirect(url_for("auth.login", email=email))

        profile = resolve_access_profile(token_row["email"])
        if profile is None:
            record_auth_event("login_verify_failed", email, ip_address, "unauthorized_profile")
            db.commit()
            flash("El correo ya no tiene acceso autorizado.", "error")
            return redirect(url_for("auth.login"))

        db.execute(
            "UPDATE login_tokens SET used_at = ? WHERE id = ?",
            (utcnow().isoformat(), token_row["id"]),
        )
        db.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (utcnow().isoformat(), profile["id"]),
        )
        db.execute(
            "UPDATE login_tokens SET used_at = ? WHERE email = ? AND used_at IS NULL",
            (db_timestamp(), token_row["email"]),
        )
        record_auth_event("login_verify_success", token_row["email"], ip_address)
        db.commit()

        session.clear()
        session["user_id"] = profile["id"]
        session.permanent = True
        session["last_activity_at"] = utcnow().isoformat()
        return redirect(url_for("main.dashboard"))

    return render_template("login.html", email=prefilled_email)


@auth_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def ensure_access_setup():
    db = get_db()
    seeded_by = db.execute("SELECT id FROM users WHERE email = ?", (DEFAULT_ADMIN_EMAILS[0],)).fetchone()
    seeded_by_id = seeded_by["id"] if seeded_by else None
    for email in DEFAULT_ADMIN_EMAILS:
        db.execute(
            """
            INSERT INTO allowed_admin_emails (email, added_by_user_id)
            VALUES (?, ?)
            ON CONFLICT(email) DO NOTHING
            """,
            (normalize_email(email), seeded_by_id),
        )
        upsert_user(normalize_email(email), "admin", format_person_name(email.split("@", 1)[0].replace(".", " ")).title())
    db.commit()
