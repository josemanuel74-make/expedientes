from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import uuid


class SignatureIntegrationError(RuntimeError):
    pass


@dataclass
class PortafirmasRequest:
    external_document_id: str
    pdf_path: Path
    signer_name: str
    signer_email: str
    signer_role: str


def infer_signer(case_row, doc_number: str, app_config) -> tuple[str, str, str]:
    if doc_number in {"01", "10", "11", "12"}:
        name = (app_config.get("SIGNATURE_ADMIN_NAME") or "").strip()
        email = (app_config.get("SIGNATURE_ADMIN_EMAIL") or "").strip().lower()
        role = "admin"
    else:
        name = (case_row["instructor_name"] or "").strip()
        email = (case_row["instructor_email"] or "").strip().lower()
        role = "instructor"

    if not name or not email:
        raise SignatureIntegrationError("No se ha podido determinar el firmante de este documento.")
    return name, email, role


def convert_docx_to_pdf(source_docx: Path, destination_dir: Path, soffice_binary: str = "soffice") -> Path:
    if not source_docx.exists():
        raise SignatureIntegrationError("El documento fuente no existe.")

    destination_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docx2pdf-") as tmp_dir:
        tmp_input = Path(tmp_dir) / source_docx.name
        shutil.copy2(source_docx, tmp_input)
        command = [
            soffice_binary,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(destination_dir),
            str(tmp_input),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
        except FileNotFoundError as exc:
            raise SignatureIntegrationError("LibreOffice no está instalado o no se encuentra el comando soffice.") from exc
        except subprocess.TimeoutExpired as exc:
            raise SignatureIntegrationError("La conversión a PDF ha tardado demasiado.") from exc

        output_pdf = destination_dir / f"{tmp_input.stem}.pdf"
        if completed.returncode != 0 or not output_pdf.exists():
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise SignatureIntegrationError(f"No se ha podido convertir el documento a PDF. {stderr}".strip())
        return output_pdf


def get_portafirmas_paths(app_config) -> tuple[Path, Path]:
    base_dir_value = (app_config.get("PORTAFIRMAS_BASE_DIR") or "").strip()
    db_value = (app_config.get("PORTAFIRMAS_DB") or "").strip()
    uploads_value = (app_config.get("PORTAFIRMAS_UPLOADS_DIR") or "").strip()

    if base_dir_value:
        base_dir = Path(base_dir_value)
        db_path = Path(db_value) if db_value else base_dir / "portafirmas.db"
        uploads_dir = Path(uploads_value) if uploads_value else base_dir / "uploads"
    else:
        raise SignatureIntegrationError("La integración con portafirmas no está configurada en este entorno.")

    if not db_path.exists():
        raise SignatureIntegrationError("No se encuentra la base de datos del portafirmas.")
    if not uploads_dir.exists():
        raise SignatureIntegrationError("No se encuentra la carpeta de subida del portafirmas.")

    return db_path, uploads_dir


def enqueue_portafirmas_request(app_config, source_docx: Path, display_name: str, signer_name: str, signer_email: str, signer_role: str) -> PortafirmasRequest:
    db_path, uploads_dir = get_portafirmas_paths(app_config)
    generated_dir = source_docx.parent / "pdf"
    pdf_path = convert_docx_to_pdf(source_docx, generated_dir, app_config.get("SOFFICE_BINARY", "soffice"))

    external_document_id = str(uuid.uuid4())
    stored_filename = f"{external_document_id}_{display_name}"
    upload_target = uploads_dir / stored_filename
    shutil.copy2(pdf_path, upload_target)

    signature_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO documents (id, filename, total_signatures)
            VALUES (?, ?, ?)
            """,
            (external_document_id, display_name, 1),
        )
        conn.execute(
            """
            INSERT INTO signatures (id, document_id, user_name, user_email, status)
            VALUES (?, ?, ?, ?, 'PENDING')
            """,
            (signature_id, external_document_id, signer_name, signer_email),
        )
        conn.commit()

    return PortafirmasRequest(
        external_document_id=external_document_id,
        pdf_path=pdf_path,
        signer_name=signer_name,
        signer_email=signer_email,
        signer_role=signer_role,
    )


def fetch_portafirmas_status(app_config, external_document_id: str) -> str:
    if not external_document_id:
        return "not_sent"

    db_path, _uploads_dir = get_portafirmas_paths(app_config)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT status
            FROM signatures
            WHERE document_id = ?
            """,
            (external_document_id,),
        ).fetchall()

    if not rows:
        return "missing"

    statuses = {str(row["status"] or "").upper() for row in rows}
    if statuses == {"SIGNED"}:
        return "signed"
    if "PENDING" in statuses:
        return "pending_signature"
    return "unknown"
