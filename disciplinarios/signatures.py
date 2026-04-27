from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import tempfile

from docx import Document

from .documents import replace_markers_in_document


class SignatureIntegrationError(RuntimeError):
    pass


SIGNABLE_DOCS = {f"{number:02d}" for number in range(1, 13)}
DIRECTOR_SIGNED_DOCS = {"01", "02", "04", "10", "11", "12"}
def document_requires_signature(doc_number: str | None) -> bool:
    return bool(doc_number and doc_number in SIGNABLE_DOCS)


def infer_signer(case_row, doc_number: str, app_config) -> tuple[str, str, str]:
    if doc_number in DIRECTOR_SIGNED_DOCS:
        name = (app_config.get("SIGNATURE_ADMIN_NAME") or "José Manuel Rodríguez García").strip()
        email = (app_config.get("SIGNATURE_ADMIN_EMAIL") or "josemanuel.rodriguez@edumelilla.es").strip().lower()
        role = "director"
    else:
        name = (case_row["instructor_name"] or "").strip()
        email = (case_row["instructor_email"] or "").strip().lower()
        role = "instructor"

    if not name or not email:
        raise SignatureIntegrationError("No se ha podido determinar el firmante de este documento.")
    return name, email, role


def build_firma_visible_text(signer_name: str, signed_at: datetime) -> str:
    return f"{signer_name}\n{signed_at.strftime('%d/%m/%Y %H:%M')}"


def convert_docx_to_pdf(
    source_docx: Path,
    destination_dir: Path,
    soffice_binary: str = "soffice",
    extra_data: dict[str, str] | None = None,
) -> Path:
    if not source_docx.exists():
        raise SignatureIntegrationError("El documento fuente no existe.")

    destination_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docx2pdf-") as tmp_dir:
        tmp_input = Path(tmp_dir) / source_docx.name
        if extra_data:
            document = Document(str(source_docx))
            replace_markers_in_document(document, extra_data)
            document.save(str(tmp_input))
        else:
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


def build_signature_extra_params(
    signer_name: str,
    reference_text: str,
    signer_role: str,
) -> str:
    return (
        "signingReason=Documento firmado en Expedientes disciplinarios\n"
        f"layer4Text={reference_text}\n"
    )


def build_signed_pdf_path(unsigned_pdf: Path, signer_role: str) -> Path:
    suffix = "director" if signer_role == "director" else "instructor"
    signed_dir = unsigned_pdf.parent / "signed"
    signed_dir.mkdir(parents=True, exist_ok=True)
    return signed_dir / f"{unsigned_pdf.stem} - firmado-{suffix}.pdf"
