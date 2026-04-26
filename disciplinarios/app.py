import os
from pathlib import Path
from datetime import timedelta

from flask import Flask, request

from .auth import auth_bp
from .db import init_app
from .views import main_bp


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def create_app() -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    load_local_env(project_root / ".env")
    app_base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000")
    secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
    is_https = app_base_url.startswith("https://")

    if is_https and secret_key == "change-me-in-production":
        raise RuntimeError("SECRET_KEY debe configurarse antes de usar la aplicación en HTTPS/producción.")

    app = Flask(
        __name__,
        instance_path=str(project_root / "instance"),
        instance_relative_config=True,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )

    app.config.update(
        SECRET_KEY=secret_key,
        DATABASE=str(project_root / "instance" / "disciplinarios.sqlite3"),
        PROJECT_ROOT=project_root,
        GENERATED_DOCS_DIR=str(project_root / "generated_docs"),
        APP_BASE_URL=app_base_url,
        MAIL_HOST=os.environ.get("MAIL_HOST", ""),
        MAIL_PORT=int(os.environ.get("MAIL_PORT", "587")),
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME", ""),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD", ""),
        MAIL_FROM=os.environ.get("MAIL_FROM", ""),
        MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").lower() in {"1", "true", "yes", "on"},
        SIGNATURE_ADMIN_NAME=os.environ.get("SIGNATURE_ADMIN_NAME", "Dirección"),
        SIGNATURE_ADMIN_EMAIL=os.environ.get("SIGNATURE_ADMIN_EMAIL", ""),
        PORTAFIRMAS_BASE_DIR=os.environ.get("PORTAFIRMAS_BASE_DIR", ""),
        PORTAFIRMAS_DB=os.environ.get("PORTAFIRMAS_DB", ""),
        PORTAFIRMAS_UPLOADS_DIR=os.environ.get("PORTAFIRMAS_UPLOADS_DIR", ""),
        PORTAFIRMAS_BASE_URL=os.environ.get("PORTAFIRMAS_BASE_URL", ""),
        SOFFICE_BINARY=os.environ.get("SOFFICE_BINARY", "soffice"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.environ.get("SESSION_MAX_AGE_HOURS", "1"))),
        SESSION_IDLE_MINUTES=int(os.environ.get("SESSION_IDLE_MINUTES", "15")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_https,
    )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["GENERATED_DOCS_DIR"]).mkdir(parents=True, exist_ok=True)

    init_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; font-src 'self' data:; "
            "connect-src 'self' http://127.0.0.1:* https://127.0.0.1:* ws://127.0.0.1:* wss://127.0.0.1:* "
            "http://localhost:* https://localhost:* ws://localhost:* wss://localhost:*; "
            "form-action 'self'; base-uri 'self'; frame-ancestors 'self'",
        )
        if request.is_secure or app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            response.headers.setdefault("Pragma", "no-cache")
        return response

    return app
