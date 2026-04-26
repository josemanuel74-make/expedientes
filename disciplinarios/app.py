import os
from pathlib import Path

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

    app = Flask(
        __name__,
        instance_path=str(project_root / "instance"),
        instance_relative_config=True,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "change-me-in-production"),
        DATABASE=str(project_root / "instance" / "disciplinarios.sqlite3"),
        PROJECT_ROOT=project_root,
        GENERATED_DOCS_DIR=str(project_root / "generated_docs"),
        APP_BASE_URL=os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000"),
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
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000").startswith("https://"),
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
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; form-action 'self'; base-uri 'self'; frame-ancestors 'self'",
        )
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    return app
