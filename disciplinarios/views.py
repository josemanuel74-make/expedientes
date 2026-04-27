from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
import io
from pathlib import Path
import re
import secrets
import shutil
import zipfile

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
import xlrd

from .auth import ACTIVE_INSTRUCTOR_STATUSES, admin_required, instructor_has_active_cases, login_required, send_email_message
from .db import get_db
from .directory import find_instructor, format_person_name, load_instructors_from_excel, normalize_email
from .documents import (
    FIELD_HELP_TEXTS,
    FIELD_LABELS,
    MONTH_NAMES,
    build_document_data,
    generate_document,
    merge_document_data,
    template_candidates,
    template_fields,
)
from .signatures import (
    SignatureIntegrationError,
    SIGNATURE_STYLE_OPTIONS,
    build_signature_extra_params,
    build_signed_pdf_path,
    convert_docx_to_pdf,
    document_requires_signature,
    infer_signer,
)

main_bp = Blueprint("main", __name__)

CASE_STATUSES = [
    ("iniciado", "01. Inicio de expediente"),
    ("notificado_inicio", "02. Notificación de inicio"),
    ("medidas_provisionales_propuesta", "03. Propuesta de medidas provisionales"),
    ("medidas_provisionales", "04. Medidas provisionales"),
    ("citacion", "05. Citación"),
    ("pliego_cargos", "06. Pliego de cargos"),
    ("audiencia", "07. Vista y audiencia"),
    ("notificado_propuesta_resolucion", "08. Notificación propuesta de resolución"),
    ("propuesta_resolucion", "09. Propuesta de resolución"),
    ("acuerdo_consejo_escolar", "10. Acuerdo Consejo Escolar"),
    ("notificado_familias", "11. Notificación familias"),
    ("notificado_inspeccion", "12. Notificación inspección"),
]

CORRECTION_TYPES = [
    ("", "Selecciona una corrección"),
    ("tareas_reparadoras", "Tareas reparadoras"),
    ("suspension_extraescolares", "Suspensión extraescolares"),
    ("cambio_grupo", "Cambio de grupo"),
    ("suspension_determinadas_clases", "Suspensión de determinadas clases"),
    ("suspension_asistencia_centro", "Suspensión de asistencia al centro"),
    ("cambio_centro", "Cambio de centro"),
]

DATE_FIELD_GROUPS = {
    "facts_date": {
        "label": "Fecha de los hechos",
        "day_field": "diaHechos",
        "month_field": "mesHechos",
    },
    "opening_date": {
        "label": "Fecha de apertura",
        "day_field": "fechaApertura",
        "month_field": "mesApertura",
    },
    "school_board_date": {
        "label": "Fecha del Consejo Escolar",
        "day_field": "diaConsejoEscolar",
        "month_field": "mesConsejoEscolar",
    },
    "hearing_date": {
        "label": "Fecha de vista y audiencia",
        "day_field": "diaVisita",
        "month_field": "mesVisita",
    },
}

NUMERIC_DOCUMENT_FIELDS = {
    "diasSuspension": {"label": "Días de suspensión", "min": 1},
    "diasExpulsionCautelar": {"label": "Días de expulsión cautelar", "min": 1, "max": 5},
}

DATETIME_FIELD_PATTERNS = {
    "fechaHoraCita": {
        "label": "Fecha y hora de la citación",
        "pattern": re.compile(r"^\d{2}/\d{2}/\d{4}\s+a\s+las\s+\d{2}:\d{2}$", re.IGNORECASE),
        "example": "27/04/2026 a las 13:30",
    }
}


def log_action(action: str, entity_type: str, entity_id: int | None = None, details: str = ""):
    db = get_db()
    db.execute(
        """
        INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (g.user["id"] if g.user else None, action, entity_type, entity_id, details),
    )
    db.commit()


def safe_filename(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9._ -]+', "-", value).strip() or "documento"


def current_user_is_admin() -> bool:
    return bool(g.user and g.user["role"] == "admin")


def current_user_email() -> str:
    return normalize_email(g.user["email"]) if g.user else ""


def user_can_access_case(case_row) -> bool:
    if case_row is None:
        return False
    if current_user_is_admin():
        return True
    return normalize_email(case_row["instructor_email"] or "") == current_user_email()


def resolve_instructor_assignment(project_root: Path, instructor_name: str) -> tuple[str, str]:
    instructor = find_instructor(project_root, instructor_name)
    if not instructor:
        return format_person_name(instructor_name), ""
    return instructor["name"], instructor["email"]


def send_instructor_assignment_email(instructor_name: str, instructor_email: str, case_number: str) -> None:
    if not instructor_email:
        return
    login_url = f"{current_app.config['APP_BASE_URL'].rstrip('/')}{url_for('auth.login', email=instructor_email)}"
    send_email_message(
        instructor_email,
        "Nombramiento como instructor de expediente disciplinario",
        (
            f"Se te ha designado instructor del expediente {case_number}.\n\n"
            f"Puedes comenzar la instrucción desde esta dirección:\n{login_url}\n\n"
            "Solicita un código de acceso con tu correo y, una vez dentro, solo verás los expedientes en los que has sido designado instructor."
        ),
    )


def send_instruction_completed_email(instructor_name: str, instructor_email: str, case_number: str, still_has_active_cases: bool) -> None:
    if not instructor_email:
        return

    if still_has_active_cases:
        access_note = (
            "Seguirás pudiendo entrar con tu correo y tu código de acceso porque todavía tienes otros expedientes en fase de instrucción."
        )
    else:
        access_note = (
            "A partir de este momento ya no podrás pedir nuevos códigos de acceso, porque no te queda ningún expediente en fase de instrucción."
        )

    send_email_message(
        instructor_email,
        "Fin de la fase de instrucción del expediente disciplinario",
        (
            f"La fase de instrucción del expediente {case_number} ha quedado finalizada.\n\n"
            "Antes de salir, revisa que toda tu parte esté completa y lista para dirección.\n\n"
            f"{access_note}"
        ),
    )


STATUS_LABELS = dict(CASE_STATUSES)
STATUS_LABELS.update(
    {
        "borrador": "01. Inicio de expediente",
        "cerrado": "12. Notificación inspección",
    }
)

FINAL_CASE_STATUS = "notificado_inspeccion"

TEMPLATE_STATUS_MAP = {
    "01": "iniciado",
    "02": "notificado_inicio",
    "03": "medidas_provisionales_propuesta",
    "04": "medidas_provisionales",
    "05": "citacion",
    "06": "pliego_cargos",
    "07": "audiencia",
    "08": "notificado_propuesta_resolucion",
    "09": "propuesta_resolucion",
    "10": "acuerdo_consejo_escolar",
    "11": "notificado_familias",
    "12": "notificado_inspeccion",
}

DOCUMENT_FLOW = {
    "01": {"prev": []},
    "02": {"prev": ["01"]},
    "03": {"prev": ["02"]},
    "04": {"prev": ["03"]},
    "05": {"prev": ["02", "04"]},
    "06": {"prev": ["05"]},
    "07": {"prev": ["06"]},
    "08": {"prev": ["07"]},
    "09": {"prev": ["08"]},
    "10": {"prev": ["09"]},
    "11": {"prev": ["10"]},
    "12": {"prev": ["10"]},
}

ROLE_ALLOWED_DOCS = {
    "admin": {f"{number:02d}" for number in range(1, 13)},
    "instructor": {"03", "05", "06", "07", "08", "09"},
}

AUDIT_ACTION_LABELS = {
    "create": "Alta",
    "update": "Edición",
    "generate": "Documento generado",
    "delete": "Borrado",
    "import": "Importación",
    "signature_request": "Firma solicitada",
    "sign": "Documento firmado",
}


def full_guardians_name(row_values: list[str]) -> str:
    first = " ".join(
        part
        for part in [row_values[23], row_values[21], row_values[22]]
        if part
    ).strip()
    second = " ".join(
        part
        for part in [row_values[31], row_values[28], row_values[29]]
        if part
    ).strip()

    if first and second:
        return f"{first} / {second}"
    return first or second or "Pendiente"


def infer_is_minor(raw_birth_date: str) -> int:
    try:
        birth = datetime.strptime(raw_birth_date, "%d/%m/%Y").date()
    except ValueError:
        return 1

    today = date.today()
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return 1 if years < 18 else 0


def import_students_from_excel(db, excel_path: Path) -> tuple[int, int]:
    book = xlrd.open_workbook(str(excel_path))
    sheet = book.sheet_by_index(0)
    imported = 0
    skipped = 0

    for row_index in range(5, sheet.nrows):
        values = [str(sheet.cell_value(row_index, column)).strip() for column in range(sheet.ncols)]
        if not values[0]:
            continue

        full_name = values[0]
        course_name = values[14]
        group_name = values[16]
        guardians_name = full_guardians_name(values)
        contact_phone = values[25] or values[33] or values[10] or values[9]
        contact_email = values[24] or values[30] or values[13] or values[12]
        is_minor = infer_is_minor(values[7])

        existing = db.execute(
            """
            SELECT id FROM students
            WHERE full_name = ? AND course_name = ? AND group_name = ?
            """,
            (full_name, course_name, group_name),
        ).fetchone()
        if existing:
            skipped += 1
            continue

        db.execute(
            """
            INSERT INTO students (
                full_name, course_name, group_name, guardians_name,
                contact_phone, contact_email, is_minor
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                full_name,
                course_name,
                group_name,
                guardians_name,
                contact_phone,
                contact_email,
                is_minor,
            ),
        )
        imported += 1

    db.commit()
    return imported, skipped


def get_case(case_id: int):
    db = get_db()
    return db.execute(
        """
        SELECT cases.*, students.full_name, students.course_name, students.group_name, students.guardians_name
        FROM cases
        JOIN students ON students.id = cases.student_id
        WHERE cases.id = ?
        """,
        (case_id,),
    ).fetchone()


def get_case_field_overrides(case_id: int) -> dict[str, str]:
    db = get_db()
    rows = db.execute(
        "SELECT field_name, field_value FROM case_field_values WHERE case_id = ?",
        (case_id,),
    ).fetchall()
    return {row["field_name"]: row["field_value"] for row in rows}


def get_case_documents(case_id: int):
    rows = get_db().execute(
        """
        SELECT generated_documents.*, users.display_name, users.email,
               signature_requests.id AS signature_request_id,
               signature_requests.signer_name,
               signature_requests.signer_email,
               signature_requests.signer_role,
               signature_requests.status AS signature_status,
               signature_requests.pdf_path,
               signature_requests.signed_pdf_path,
               signature_requests.sent_at,
               signature_requests.completed_at,
               signature_requests.last_error
        FROM generated_documents
        LEFT JOIN users ON users.id = generated_documents.created_by_user_id
        LEFT JOIN signature_requests ON signature_requests.generated_document_id = generated_documents.id
        WHERE generated_documents.case_id = ?
        ORDER BY generated_documents.doc_number, generated_documents.version_number DESC, generated_documents.created_at DESC
        """,
        (case_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def next_document_version(case_id: int, doc_number: str | None, template_name: str) -> int:
    db = get_db()
    if doc_number:
        row = db.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) AS version_number
            FROM generated_documents
            WHERE case_id = ? AND doc_number = ?
            """,
            (case_id, doc_number),
        ).fetchone()
    else:
        row = db.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) AS version_number
            FROM generated_documents
            WHERE case_id = ? AND template_name = ?
            """,
            (case_id, template_name),
        ).fetchone()
    return int(row["version_number"] or 0) + 1


def signature_status_label(status: str | None) -> str:
    labels = {
        "pending_send": "Pendiente de preparar",
        "pending_signature": "Pendiente de firma",
        "signed": "Firmado",
        "failed": "Error de firma",
    }
    return labels.get(status or "", "Sin enviar")


def signature_enabled() -> bool:
    return True


def save_case_field_overrides(case_id: int, values: dict[str, str]) -> None:
    db = get_db()
    for field_name, field_value in values.items():
        if not str(field_value or "").strip():
            continue
        normalized_value = format_person_name(field_value) if field_name == "nombreInstructor" else field_value
        db.execute(
            """
            INSERT INTO case_field_values (case_id, field_name, field_value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(case_id, field_name)
            DO UPDATE SET field_value = excluded.field_value, updated_at = CURRENT_TIMESTAMP
            """,
            (case_id, field_name, normalized_value),
        )
    db.commit()


def build_date_helper_items(case, fields: list[str]) -> tuple[list[dict], set[str]]:
    helper_items: list[dict] = []
    covered_fields: set[str] = set()

    for case_field, config in DATE_FIELD_GROUPS.items():
        day_field = config["day_field"]
        month_field = config["month_field"]
        if day_field in fields and month_field in fields:
            helper_items.append(
                {
                    "name": case_field,
                    "label": config["label"],
                    "value": case[case_field] or "",
                }
            )
            covered_fields.add(day_field)
            covered_fields.add(month_field)

    return helper_items, covered_fields


def validate_document_fields(
    fields: list[str],
    date_helper_items: list[dict],
    submitted_values: dict[str, str],
    submitted_dates: dict[str, str],
    covered_fields: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    covered_fields = covered_fields or set()

    for item in date_helper_items:
        effective_date = submitted_dates.get(item["name"], "").strip() or str(item.get("value", "")).strip()
        if not effective_date:
            errors.append(f"Falta rellenar {item['label']}.")

    for field_name in fields:
        if field_name in covered_fields:
            continue
        value = submitted_values.get(field_name, "").strip()
        label = FIELD_LABELS.get(field_name, field_name)
        if not value:
            errors.append(f"Falta rellenar {label}.")
            continue

        numeric_config = NUMERIC_DOCUMENT_FIELDS.get(field_name)
        if numeric_config:
            try:
                number = int(value)
            except ValueError:
                errors.append(f"{numeric_config['label']} debe ser un número entero.")
                continue
            if number < numeric_config["min"]:
                errors.append(f"{numeric_config['label']} debe ser mayor o igual que {numeric_config['min']}.")
            if "max" in numeric_config and number > numeric_config["max"]:
                errors.append(f"{numeric_config['label']} no puede ser mayor que {numeric_config['max']}.")

        datetime_config = DATETIME_FIELD_PATTERNS.get(field_name)
        if datetime_config and not datetime_config["pattern"].match(value):
            errors.append(
                f"{datetime_config['label']} debe tener este formato: {datetime_config['example']}."
            )

    return errors


def infer_status_from_template_name(template_name: str) -> str | None:
    match = re.match(r"^\s*(\d{2})\b", template_name)
    if not match:
        return None
    return TEMPLATE_STATUS_MAP.get(match.group(1))


def infer_doc_number_from_template_name(template_name: str) -> str | None:
    match = re.match(r"^\s*(\d{2})\b", template_name)
    if not match:
        return None
    return match.group(1)


def generated_doc_numbers(case_id: int) -> set[str]:
    db = get_db()
    rows = db.execute(
        "SELECT template_name FROM generated_documents WHERE case_id = ?",
        (case_id,),
    ).fetchall()
    numbers = set()
    for row in rows:
        doc_number = infer_doc_number_from_template_name(row["template_name"])
        if doc_number:
            numbers.add(doc_number)
    return numbers


def document_is_available(doc_number: str, generated_numbers: set[str]) -> bool:
    if doc_number not in DOCUMENT_FLOW:
        return True
    previous = DOCUMENT_FLOW[doc_number]["prev"]
    if not previous:
        return True
    return any(prev in generated_numbers for prev in previous)


def user_can_manage_doc_number(doc_number: str | None, case_row=None) -> bool:
    if not g.user or not doc_number:
        return False

    allowed_docs = set(ROLE_ALLOWED_DOCS.get(g.user["role"], set()))
    if (
        current_user_is_admin()
        and case_row is not None
        and normalize_email(case_row["instructor_email"] or "") == current_user_email()
    ):
        allowed_docs.update(ROLE_ALLOWED_DOCS["instructor"])

    return doc_number in allowed_docs


def instructor_phase_finished(status: str) -> bool:
    return status not in ACTIVE_INSTRUCTOR_STATUSES


def parse_iso_date(raw_value: str | None) -> date | None:
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError:
        return None


def build_case_alerts(case) -> list[dict]:
    today = date.today()
    alerts: list[dict] = []

    fact_known_date = parse_iso_date(case["fact_known_date"])
    opening_date = parse_iso_date(case["opening_date"])

    if fact_known_date:
        instruction_deadline = fact_known_date + timedelta(days=10)
        if case["status"] == "iniciado" and today > instruction_deadline:
            alerts.append(
                {
                    "level": "error",
                    "title": "Plazo de incoación vencido",
                    "body": f"Han pasado más de 10 días desde el conocimiento de los hechos. Fecha límite: {instruction_deadline.strftime('%d/%m/%Y')}.",
                }
            )
        elif case["status"] == "iniciado" and (instruction_deadline - today).days <= 2:
            alerts.append(
                {
                    "level": "warning",
                    "title": "Plazo de incoación próximo",
                    "body": f"Quedan {(instruction_deadline - today).days} día(s) para acordar la instrucción. Fecha límite: {instruction_deadline.strftime('%d/%m/%Y')}.",
                }
            )

    if opening_date:
        investigation_deadline = opening_date + timedelta(days=7)
        resolution_deadline = opening_date + timedelta(days=30)

        if case["status"] in ACTIVE_INSTRUCTOR_STATUSES and today > investigation_deadline:
            alerts.append(
                {
                    "level": "warning",
                    "title": "Instrucción fuera de plazo orientativo",
                    "body": f"Se han superado los 7 días de instrucción. Fecha de referencia: {investigation_deadline.strftime('%d/%m/%Y')}.",
                }
            )
        elif case["status"] in ACTIVE_INSTRUCTOR_STATUSES and (investigation_deadline - today).days <= 2:
            alerts.append(
                {
                    "level": "info",
                    "title": "Fin de instrucción próximo",
                    "body": f"El plazo orientativo de 7 días vence el {investigation_deadline.strftime('%d/%m/%Y')}.",
                }
            )

        if case["status"] != FINAL_CASE_STATUS and today > resolution_deadline:
            alerts.append(
                {
                    "level": "error",
                    "title": "Plazo máximo de resolución vencido",
                    "body": f"Se ha superado el mes máximo desde la iniciación. Fecha límite: {resolution_deadline.strftime('%d/%m/%Y')}.",
                }
            )
        elif case["status"] != FINAL_CASE_STATUS and (resolution_deadline - today).days <= 5:
            alerts.append(
                {
                    "level": "warning",
                    "title": "Plazo máximo de resolución próximo",
                    "body": f"Quedan {(resolution_deadline - today).days} día(s) para resolver. Fecha límite: {resolution_deadline.strftime('%d/%m/%Y')}.",
                }
            )

    return alerts


def get_case_timeline(case_id: int) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT audit_logs.*, users.display_name, users.email
        FROM audit_logs
        LEFT JOIN users ON users.id = audit_logs.user_id
        WHERE audit_logs.entity_id = ?
          AND audit_logs.entity_type IN ('case', 'document')
        ORDER BY audit_logs.created_at DESC, audit_logs.id DESC
        """,
        (case_id,),
    ).fetchall()
    items = []
    for row in rows:
        actor = row["display_name"] or row["email"] or "Sistema"
        label = AUDIT_ACTION_LABELS.get(row["action"], row["action"].capitalize())
        items.append(
            {
                "created_at": row["created_at"],
                "title": label,
                "actor": actor,
                "details": row["details"] or "",
            }
        )
    return items


def template_options(case_row, templates: list[Path]) -> list[dict]:
    case_id = case_row["id"]
    generated_numbers = generated_doc_numbers(case_id)
    options = []
    for template in templates:
        doc_number = infer_doc_number_from_template_name(template.name)
        flow_available = True if not doc_number else document_is_available(doc_number, generated_numbers)
        role_allowed = user_can_manage_doc_number(doc_number, case_row)
        available = flow_available and role_allowed
        already_done = True if doc_number and doc_number in generated_numbers else False
        options.append(
            {
                "name": template.name,
                "doc_number": doc_number,
                "available": available,
                "role_allowed": role_allowed,
                "flow_available": flow_available,
                "already_done": already_done,
            }
        )
    return options


def next_available_doc_numbers(case_row) -> set[str]:
    case_id = case_row["id"]
    generated_numbers = generated_doc_numbers(case_id)
    available = set()
    for doc_number in DOCUMENT_FLOW:
        if doc_number in generated_numbers:
            continue
        if document_is_available(doc_number, generated_numbers) and user_can_manage_doc_number(doc_number, case_row):
            available.add(doc_number)
    return available


def latest_documents_by_doc_number(case_id: int) -> list:
    return get_db().execute(
        """
        SELECT *
        FROM generated_documents
        WHERE case_id = ? AND is_latest = 1
        ORDER BY doc_number, version_number
        """,
        (case_id,),
    ).fetchall()


def get_signature_csrf_token() -> str:
    token = session.get("signature_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["signature_csrf_token"] = token
    return token


def signature_sign_url(document_id: int) -> str:
    return f"{current_app.config['APP_BASE_URL'].rstrip('/')}{url_for('main.signature_sign_page', document_id=document_id)}"


def send_signature_notification(signer_name: str, signer_email: str, document_label: str, document_id: int) -> None:
    send_email_message(
        signer_email,
        f"Documento pendiente de firma: {document_label}",
        (
            f"Tienes un documento pendiente de firma: {document_label}.\n\n"
            f"Accede a Expedientes disciplinarios para revisarlo y firmarlo:\n{signature_sign_url(document_id)}"
        ),
    )


def ensure_signature_request(case_row, document_row, requested_by_user_id: int | None) -> tuple[dict | None, str | None]:
    doc_number = document_row["doc_number"] or infer_doc_number_from_template_name(document_row["template_name"])
    if not document_requires_signature(doc_number):
        return None, None

    db = get_db()
    existing = db.execute(
        "SELECT * FROM signature_requests WHERE generated_document_id = ?",
        (document_row["id"],),
    ).fetchone()
    if existing:
        return dict(existing), None

    signer_name, signer_email, signer_role = infer_signer(case_row, doc_number or "", current_app.config)
    db.execute(
        """
        INSERT INTO signature_requests (
            generated_document_id, signer_name, signer_email, signer_role,
            status, requested_by_user_id, sent_at
        )
        VALUES (?, ?, ?, ?, 'pending_signature', ?, CURRENT_TIMESTAMP)
        """,
        (
            document_row["id"],
            signer_name,
            signer_email,
            signer_role,
            requested_by_user_id,
        ),
    )
    request_row = db.execute(
        "SELECT * FROM signature_requests WHERE generated_document_id = ?",
        (document_row["id"],),
    ).fetchone()
    db.commit()
    return dict(request_row), signer_email


def current_user_can_sign(document_row: dict) -> bool:
    return (
        bool(g.user)
        and bool(document_row.get("signature_request_id"))
        and bool(document_row.get("is_latest"))
        and normalize_email(document_row.get("signer_email") or "") == current_user_email()
        and (document_row.get("signature_status") or "") == "pending_signature"
    )


def get_signature_request_for_document(document_id: int):
    return get_db().execute(
        """
        SELECT signature_requests.*,
               signature_requests.status AS signature_status,
               generated_documents.case_id, generated_documents.template_name,
               generated_documents.doc_number, generated_documents.version_number,
               generated_documents.is_latest, generated_documents.output_path
        FROM signature_requests
        JOIN generated_documents ON generated_documents.id = signature_requests.generated_document_id
        WHERE generated_document_id = ?
        """,
        (document_id,),
    ).fetchone()


def build_unsigned_pdf(document_row, signature_row) -> Path:
    source_docx = Path(document_row["output_path"])
    unsigned_dir = source_docx.parent / "pdf"
    pdf_path = convert_docx_to_pdf(source_docx, unsigned_dir, current_app.config.get("SOFFICE_BINARY", "soffice"))
    if signature_row:
        get_db().execute(
            "UPDATE signature_requests SET pdf_path = ? WHERE id = ?",
            (str(pdf_path), signature_row["id"]),
        )
        get_db().commit()
    return pdf_path


def backfill_signature_requests_for_case(case_row) -> None:
    db = get_db()
    latest_documents = db.execute(
        """
        SELECT *
        FROM generated_documents
        WHERE case_id = ? AND is_latest = 1
        """,
        (case_row["id"],),
    ).fetchall()
    for document in latest_documents:
        try:
            ensure_signature_request(case_row, document, g.user["id"] if g.user else None)
        except SignatureIntegrationError:
            continue


@main_bp.get("/")
def index():
    if g.user:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.get("/dashboard")
@login_required
def dashboard():
    db = get_db()
    if current_user_is_admin():
        counts = {
            "students": db.execute("SELECT COUNT(*) AS count FROM students").fetchone()["count"],
            "cases": db.execute("SELECT COUNT(*) AS count FROM cases").fetchone()["count"],
            "open_cases": db.execute(
                "SELECT COUNT(*) AS count FROM cases WHERE status != ?",
                (FINAL_CASE_STATUS,),
            ).fetchone()["count"],
        }
        recent_cases = db.execute(
            """
            SELECT cases.id, cases.case_number, cases.status, students.full_name
            FROM cases
            JOIN students ON students.id = cases.student_id
            ORDER BY cases.created_at DESC
            LIMIT 5
            """
        ).fetchall()
    else:
        counts = {
            "students": 0,
            "cases": db.execute(
                "SELECT COUNT(*) AS count FROM cases WHERE instructor_email = ?",
                (current_user_email(),),
            ).fetchone()["count"],
            "open_cases": db.execute(
                "SELECT COUNT(*) AS count FROM cases WHERE instructor_email = ? AND status != ?",
                (current_user_email(), FINAL_CASE_STATUS),
            ).fetchone()["count"],
        }
        recent_cases = db.execute(
            """
            SELECT cases.id, cases.case_number, cases.status, students.full_name
            FROM cases
            JOIN students ON students.id = cases.student_id
            WHERE cases.instructor_email = ?
            ORDER BY cases.created_at DESC
            LIMIT 5
            """,
            (current_user_email(),),
        ).fetchall()
    return render_template(
        "dashboard.html",
        counts=counts,
        recent_cases=recent_cases,
        status_labels=STATUS_LABELS,
    )


@main_bp.get("/admin/access")
@admin_required
def admin_access():
    db = get_db()
    rows = db.execute(
        """
        SELECT allowed_admin_emails.email, allowed_admin_emails.created_at, users.display_name
        FROM allowed_admin_emails
        LEFT JOIN users ON users.email = allowed_admin_emails.email
        ORDER BY allowed_admin_emails.email
        """
    ).fetchall()
    return render_template("admin/access.html", admin_emails=rows)


@main_bp.post("/admin/access")
@admin_required
def admin_access_add():
    email = normalize_email(request.form.get("email", ""))
    if not email:
        flash("Indica un correo electrónico válido.", "error")
        return redirect(url_for("main.admin_access"))

    db = get_db()
    db.execute(
        """
        INSERT INTO allowed_admin_emails (email, added_by_user_id)
        VALUES (?, ?)
        ON CONFLICT(email) DO NOTHING
        """,
        (email, g.user["id"]),
    )
    db.commit()
    flash("Administrador añadido.", "success")
    return redirect(url_for("main.admin_access"))


@main_bp.post("/admin/access/<path:email>/delete")
@admin_required
def admin_access_delete(email: str):
    normalized = normalize_email(email)
    if normalized == current_user_email():
        flash("No puedes quitarte a ti mismo el acceso de administrador.", "error")
        return redirect(url_for("main.admin_access"))

    db = get_db()
    db.execute("DELETE FROM allowed_admin_emails WHERE email = ?", (normalized,))
    db.commit()
    flash("Administrador eliminado.", "success")
    return redirect(url_for("main.admin_access"))


@main_bp.get("/students")
@admin_required
def students():
    query = request.args.get("q", "").strip()
    db = get_db()
    if query:
        rows = db.execute(
            """
            SELECT * FROM students
            WHERE full_name LIKE ? OR course_name LIKE ? OR group_name LIKE ?
            ORDER BY full_name
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM students ORDER BY full_name").fetchall()
    excel_path = Path(current_app.config["PROJECT_ROOT"]) / "RegAlum (1).xls"
    return render_template("students/list.html", students=rows, query=query, excel_available=excel_path.exists())


@main_bp.post("/students/import")
@admin_required
def students_import():
    excel_path = Path(current_app.config["PROJECT_ROOT"]) / "RegAlum (1).xls"
    if not excel_path.exists():
        flash("No se ha encontrado el fichero RegAlum (1).xls en la carpeta del proyecto.", "error")
        return redirect(url_for("main.students"))

    db = get_db()
    imported, skipped = import_students_from_excel(db, excel_path)
    log_action("import", "student", None, f"Excel importado: {imported} nuevos, {skipped} omitidos")
    flash(f"Importación completada. Nuevos: {imported}. Omitidos por duplicado: {skipped}.", "success")
    return redirect(url_for("main.students"))


@main_bp.route("/students/new", methods=("GET", "POST"))
@admin_required
def student_create():
    if request.method == "POST":
        db = get_db()
        db.execute(
            """
            INSERT INTO students (
                full_name, course_name, group_name, guardians_name,
                contact_phone, contact_email, is_minor
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.form["full_name"].strip(),
                request.form["course_name"].strip(),
                request.form["group_name"].strip(),
                request.form["guardians_name"].strip(),
                request.form["contact_phone"].strip(),
                request.form["contact_email"].strip(),
                1 if request.form.get("is_minor") else 0,
            ),
        )
        db.commit()
        student_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        log_action("create", "student", student_id, "Alta de alumno")
        flash("Alumno creado.", "success")
        return redirect(url_for("main.students"))

    return render_template("students/form.html", student=None)


@main_bp.route("/students/<int:student_id>/edit", methods=("GET", "POST"))
@admin_required
def student_edit(student_id: int):
    db = get_db()
    student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if student is None:
        return redirect(url_for("main.students"))

    if request.method == "POST":
        db.execute(
            """
            UPDATE students
            SET full_name = ?, course_name = ?, group_name = ?, guardians_name = ?,
                contact_phone = ?, contact_email = ?, is_minor = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                request.form["full_name"].strip(),
                request.form["course_name"].strip(),
                request.form["group_name"].strip(),
                request.form["guardians_name"].strip(),
                request.form["contact_phone"].strip(),
                request.form["contact_email"].strip(),
                1 if request.form.get("is_minor") else 0,
                student_id,
            ),
        )
        db.commit()
        log_action("update", "student", student_id, "Edición de alumno")
        flash("Alumno actualizado.", "success")
        return redirect(url_for("main.students"))

    return render_template("students/form.html", student=student)


@main_bp.post("/students/<int:student_id>/delete")
@admin_required
def student_delete(student_id: int):
    db = get_db()
    student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if student is None:
        flash("El alumno no existe.", "error")
        return redirect(url_for("main.students"))

    linked_case = db.execute(
        "SELECT id, case_number FROM cases WHERE student_id = ? LIMIT 1",
        (student_id,),
    ).fetchone()
    if linked_case:
        flash(
            f"No se puede borrar el alumno porque está asociado al expediente {linked_case['case_number']}.",
            "error",
        )
        return redirect(url_for("main.student_edit", student_id=student_id))

    db.execute("DELETE FROM students WHERE id = ?", (student_id,))
    db.commit()
    log_action("delete", "student", student_id, student["full_name"])
    flash("Alumno borrado.", "success")
    return redirect(url_for("main.students"))


@main_bp.get("/cases")
@login_required
def cases():
    db = get_db()
    if current_user_is_admin():
        rows = db.execute(
            """
            SELECT cases.*, students.full_name
            FROM cases
            JOIN students ON students.id = cases.student_id
            ORDER BY cases.created_at DESC
            """
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT cases.*, students.full_name
            FROM cases
            JOIN students ON students.id = cases.student_id
            WHERE cases.instructor_email = ?
            ORDER BY cases.created_at DESC
            """,
            (current_user_email(),),
        ).fetchall()
    return render_template("cases/list.html", cases=rows, status_labels=STATUS_LABELS)


@main_bp.route("/cases/new", methods=("GET", "POST"))
@admin_required
def case_create():
    db = get_db()
    students = db.execute("SELECT id, full_name FROM students ORDER BY full_name").fetchall()
    instructors = load_instructors_from_excel(Path(current_app.config["PROJECT_ROOT"]))

    if request.method == "POST":
        instructor_name, instructor_email = resolve_instructor_assignment(
            Path(current_app.config["PROJECT_ROOT"]),
            request.form["instructor_name"].strip(),
        )
        db.execute(
            """
            INSERT INTO cases (
                case_number, student_id, status, fact_known_date, opening_date, facts_date,
                facts_summary, conduct_type, instructor_name, instructor_email, precautionary_days,
                suspension_days, correction_type, proposed_measure, school_work_plan,
                hearing_held, hearing_date, inspection_start_at, inspection_resolution_at,
                school_board_date, school_board_result, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.form["case_number"].strip(),
                request.form["student_id"],
                request.form["status"] or "iniciado",
                request.form["fact_known_date"],
                request.form["opening_date"] or None,
                request.form["facts_date"],
                request.form["facts_summary"].strip(),
                "",
                instructor_name,
                instructor_email,
                0,
                0,
                "",
                "",
                "",
                1 if request.form.get("hearing_held") else 0,
                None,
                None,
                None,
                None,
                "",
                request.form["notes"].strip(),
            ),
        )
        db.commit()
        case_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        if instructor_email:
            send_instructor_assignment_email(instructor_name, instructor_email, request.form["case_number"].strip())
        log_action("create", "case", case_id, "Alta de expediente")
        flash("Expediente creado.", "success")
        return redirect(url_for("main.cases"))

    return render_template(
        "cases/form.html",
        case=None,
        students=students,
        instructors=instructors,
        statuses=CASE_STATUSES,
        correction_types=CORRECTION_TYPES,
    )


@main_bp.route("/cases/<int:case_id>/edit", methods=("GET", "POST"))
@admin_required
def case_edit(case_id: int):
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    students = db.execute("SELECT id, full_name FROM students ORDER BY full_name").fetchall()
    instructors = load_instructors_from_excel(Path(current_app.config["PROJECT_ROOT"]))
    if case is None:
        return redirect(url_for("main.cases"))

    if request.method == "POST":
        instructor_name, instructor_email = resolve_instructor_assignment(
            Path(current_app.config["PROJECT_ROOT"]),
            request.form["instructor_name"].strip(),
        )
        instructor_changed = (
            instructor_name != (case["instructor_name"] or "")
            or normalize_email(instructor_email) != normalize_email(case["instructor_email"] or "")
        )
        db.execute(
            """
            UPDATE cases
            SET case_number = ?, student_id = ?, status = ?, fact_known_date = ?,
                opening_date = ?, facts_date = ?, facts_summary = ?, conduct_type = ?,
                instructor_name = ?, instructor_email = ?, precautionary_days = ?, suspension_days = ?,
                correction_type = ?, proposed_measure = ?, school_work_plan = ?,
                hearing_held = ?, hearing_date = ?, inspection_start_at = ?,
                inspection_resolution_at = ?, school_board_date = ?,
                school_board_result = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                request.form["case_number"].strip(),
                request.form["student_id"],
                request.form["status"] or "iniciado",
                request.form["fact_known_date"],
                request.form["opening_date"] or None,
                request.form["facts_date"],
                request.form["facts_summary"].strip(),
                case["conduct_type"],
                instructor_name,
                instructor_email,
                case["precautionary_days"],
                case["suspension_days"],
                case["correction_type"],
                case["proposed_measure"],
                case["school_work_plan"],
                case["hearing_held"],
                case["hearing_date"],
                case["inspection_start_at"],
                case["inspection_resolution_at"],
                case["school_board_date"],
                case["school_board_result"],
                request.form["notes"].strip(),
                case_id,
            ),
        )
        db.commit()
        if instructor_changed and instructor_email:
            send_instructor_assignment_email(instructor_name, instructor_email, request.form["case_number"].strip())
        log_action("update", "case", case_id, "Edición de expediente")
        flash("Expediente actualizado.", "success")
        return redirect(url_for("main.case_detail", case_id=case_id))

    return render_template(
        "cases/form.html",
        case=case,
        students=students,
        instructors=instructors,
        statuses=CASE_STATUSES,
        correction_types=CORRECTION_TYPES,
    )


@main_bp.post("/cases/<int:case_id>/delete")
@admin_required
def case_delete(case_id: int):
    db = get_db()
    case = db.execute("SELECT id, case_number FROM cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        flash("El expediente no existe.", "error")
        return redirect(url_for("main.cases"))

    documents = db.execute(
        """
        SELECT generated_documents.output_path, signature_requests.pdf_path, signature_requests.signed_pdf_path
        FROM generated_documents
        LEFT JOIN signature_requests ON signature_requests.generated_document_id = generated_documents.id
        WHERE generated_documents.case_id = ?
        """,
        (case_id,),
    ).fetchall()
    for document in documents:
        for key in ("output_path", "pdf_path", "signed_pdf_path"):
            if document[key]:
                path = Path(document[key])
                if path.exists():
                    path.unlink()

    case_folder = Path(current_app.config["GENERATED_DOCS_DIR"]) / f"case-{case_id}"
    if case_folder.exists():
        shutil.rmtree(case_folder, ignore_errors=True)

    db.execute("DELETE FROM cases WHERE id = ?", (case_id,))
    db.commit()
    log_action("delete", "case", case_id, case["case_number"])
    flash("Expediente borrado.", "success")
    return redirect(url_for("main.cases"))


@main_bp.get("/cases/<int:case_id>")
@login_required
def case_detail(case_id: int):
    db = get_db()
    case = get_case(case_id)
    if not user_can_access_case(case):
        flash("No tienes permiso para ver este expediente.", "error")
        return redirect(url_for("main.cases"))
    backfill_signature_requests_for_case(case)
    documents = get_case_documents(case_id)
    templates = template_candidates(Path(current_app.config["PROJECT_ROOT"]))
    template_items = template_options(case, templates)
    next_docs = next_available_doc_numbers(case)
    return render_template(
        "cases/detail.html",
        case=case,
        documents=documents,
        template_items=template_items,
        next_docs=next_docs,
        alerts=build_case_alerts(case),
        timeline_items=get_case_timeline(case_id),
        signature_enabled=signature_enabled(),
        current_user_email=current_user_email(),
        current_user_can_sign=current_user_can_sign,
        signature_status_label=signature_status_label,
        status_labels=STATUS_LABELS,
    )


@main_bp.get("/cases/<int:case_id>/documents/new")
@login_required
def case_document_form(case_id: int):
    template_name = request.args.get("template_name", "").strip()
    project_root = Path(current_app.config["PROJECT_ROOT"])
    template_path = project_root / template_name
    if not template_name or not template_path.exists():
        flash("Selecciona una plantilla válida.", "error")
        return redirect(url_for("main.case_detail", case_id=case_id))

    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        flash("El expediente no existe.", "error")
        return redirect(url_for("main.cases"))
    if not user_can_access_case(case):
        flash("No tienes permiso para preparar documentos de este expediente.", "error")
        return redirect(url_for("main.cases"))
    doc_number = infer_doc_number_from_template_name(template_name)
    if doc_number and not user_can_manage_doc_number(doc_number, case):
        flash("No tienes permiso para preparar ese documento.", "error")
        return redirect(url_for("main.case_detail", case_id=case_id))
    if doc_number and not document_is_available(doc_number, generated_doc_numbers(case_id)):
        flash("Ese documento todavía no se puede generar porque falta un paso anterior.", "error")
        return redirect(url_for("main.case_detail", case_id=case_id))
    student = db.execute("SELECT * FROM students WHERE id = ?", (case["student_id"],)).fetchone()
    base_data = build_document_data(case, student)
    overrides = get_case_field_overrides(case_id)
    merged = merge_document_data(base_data, overrides)
    fields = template_fields(template_path)
    date_helper_items, covered_fields = build_date_helper_items(case, fields)
    field_items = [
        {
            "name": field_name,
            "label": FIELD_LABELS.get(field_name, field_name),
            "value": merged.get(field_name, ""),
            "help_text": FIELD_HELP_TEXTS.get(field_name, ""),
            "required": True,
        }
        for field_name in fields
        if field_name not in covered_fields
        and not (field_name == "nombreInstructor" and str(merged.get(field_name, "")).strip())
    ]
    instructors = load_instructors_from_excel(project_root)

    return render_template(
        "cases/document_form.html",
        case=get_case(case_id),
        template_name=template_name,
        field_items=field_items,
        date_helper_items=date_helper_items,
        instructors=instructors,
    )


@main_bp.post("/cases/<int:case_id>/generate")
@login_required
def case_generate_document(case_id: int):
    template_name = request.form["template_name"]
    project_root = Path(current_app.config["PROJECT_ROOT"])
    template_path = project_root / template_name
    if not template_path.exists():
        flash("La plantilla seleccionada no existe.", "error")
        return redirect(url_for("main.case_detail", case_id=case_id))

    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        flash("El expediente no existe.", "error")
        return redirect(url_for("main.cases"))
    if not user_can_access_case(case):
        flash("No tienes permiso para generar documentos de este expediente.", "error")
        return redirect(url_for("main.cases"))
    doc_number = infer_doc_number_from_template_name(template_name)
    if doc_number and not user_can_manage_doc_number(doc_number, case):
        flash("No tienes permiso para generar ese documento.", "error")
        return redirect(url_for("main.case_detail", case_id=case_id))
    if doc_number and not document_is_available(doc_number, generated_doc_numbers(case_id)):
        flash("Ese documento todavía no se puede generar porque falta un paso anterior.", "error")
        return redirect(url_for("main.case_detail", case_id=case_id))
    student = db.execute("SELECT * FROM students WHERE id = ?", (case["student_id"],)).fetchone()
    base_data = build_document_data(case, student)
    existing_values = merge_document_data(base_data, get_case_field_overrides(case_id))
    fields = template_fields(template_path)
    date_helper_items, covered_fields = build_date_helper_items(case, fields)
    submitted_dates = {
        item["name"]: request.form.get(item["name"], "").strip()
        for item in date_helper_items
    }
    raw_submitted_values = {
        field_name: request.form.get(field_name, "").strip()
        for field_name in fields
    }
    submitted_values = {
        field_name: raw_submitted_values.get(field_name, "").strip() or str(existing_values.get(field_name, "")).strip()
        for field_name in fields
    }
    validation_errors = validate_document_fields(fields, date_helper_items, submitted_values, submitted_dates, covered_fields)
    if validation_errors:
        for error in validation_errors:
            flash(error, "error")

        field_items = [
            {
                "name": field_name,
                "label": FIELD_LABELS.get(field_name, field_name),
                "value": submitted_values.get(field_name, ""),
                "help_text": FIELD_HELP_TEXTS.get(field_name, ""),
                "required": True,
            }
            for field_name in fields
            if field_name not in covered_fields
            and not (field_name == "nombreInstructor" and str(submitted_values.get(field_name, "")).strip())
        ]
        populated_date_helper_items = [
            {**item, "value": submitted_dates.get(item["name"], "").strip() or item.get("value", "")}
            for item in date_helper_items
        ]
        instructors = load_instructors_from_excel(project_root)
        return render_template(
            "cases/document_form.html",
            case=get_case(case_id),
            template_name=template_name,
            field_items=field_items,
            date_helper_items=populated_date_helper_items,
            instructors=instructors,
        )

    case_updates = {}
    form_values = submitted_values.copy()

    for case_field, config in DATE_FIELD_GROUPS.items():
        day_field = config["day_field"]
        month_field = config["month_field"]
        date_value = submitted_dates.get(case_field, "")
        if date_value and day_field in fields and month_field in fields:
            try:
                parsed = datetime.strptime(date_value, "%Y-%m-%d")
            except ValueError:
                continue
            case_updates[case_field] = date_value
            form_values[day_field] = str(parsed.day)
            form_values[month_field] = MONTH_NAMES.get(parsed.month, "")

    save_case_field_overrides(case_id, submitted_values)
    if case_updates:
        set_clause = ", ".join(f"{field} = ?" for field in case_updates)
        values = list(case_updates.values()) + [case_id]
        db.execute(
            f"UPDATE cases SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        updated_case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        case = updated_case
        base_data = build_document_data(case, student)

    data = merge_document_data(base_data, {**get_case_field_overrides(case_id), **form_values})

    if "nombreInstructor" in submitted_values and submitted_values["nombreInstructor"] != (case["instructor_name"] or ""):
        normalized_instructor, normalized_instructor_email = resolve_instructor_assignment(
            project_root,
            submitted_values["nombreInstructor"],
        )
        db.execute(
            "UPDATE cases SET instructor_name = ?, instructor_email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (normalized_instructor, normalized_instructor_email, case_id),
        )
        if normalized_instructor_email:
            send_instructor_assignment_email(normalized_instructor, normalized_instructor_email, case["case_number"])
    if "hechos" in submitted_values and submitted_values["hechos"] and submitted_values["hechos"] != (case["facts_summary"] or ""):
        db.execute(
            "UPDATE cases SET facts_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (submitted_values["hechos"], case_id),
        )
    if "calificacionHechos" in submitted_values:
        db.execute(
            "UPDATE cases SET conduct_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (submitted_values["calificacionHechos"], case_id),
        )
    if "propuesta" in submitted_values:
        db.execute(
            "UPDATE cases SET proposed_measure = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (submitted_values["propuesta"], case_id),
        )
    if "diasSuspension" in submitted_values:
        try:
            suspension_days = int(submitted_values["diasSuspension"] or 0)
        except ValueError:
            suspension_days = 0
        db.execute(
            "UPDATE cases SET suspension_days = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (suspension_days, case_id),
        )
    if "diasExpulsionCautelar" in submitted_values:
        try:
            precautionary_days = int(submitted_values["diasExpulsionCautelar"] or 0)
        except ValueError:
            precautionary_days = 0
        precautionary_days = min(precautionary_days, 5)
        db.execute(
            "UPDATE cases SET precautionary_days = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (precautionary_days, case_id),
        )

    output_dir = Path(current_app.config["GENERATED_DOCS_DIR"]) / f"case-{case_id}"
    version_number = next_document_version(case_id, doc_number, template_name)
    version_suffix = f" - v{version_number:02d}"
    output_name = f"{safe_filename(template_path.stem)} - {safe_filename(case['case_number'])}{version_suffix}.docx"
    output_path = output_dir / output_name
    generate_document(template_path, output_path, data)

    if doc_number:
        db.execute(
            "UPDATE generated_documents SET is_latest = 0 WHERE case_id = ? AND doc_number = ?",
            (case_id, doc_number),
        )
    insert_cursor = db.execute(
        """
        INSERT INTO generated_documents (case_id, template_name, doc_number, version_number, is_latest, output_path, created_by_user_id)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (case_id, template_name, doc_number, version_number, str(output_path), g.user["id"]),
    )
    generated_document_id = insert_cursor.lastrowid
    inferred_status = infer_status_from_template_name(template_name)
    if inferred_status:
        db.execute(
            "UPDATE cases SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (inferred_status, case_id),
        )
    db.commit()
    generated_document = db.execute("SELECT * FROM generated_documents WHERE id = ?", (generated_document_id,)).fetchone()
    signature_request = None
    signature_email = None
    try:
        signature_request, signature_email = ensure_signature_request(case, generated_document, g.user["id"])
    except SignatureIntegrationError as exc:
        flash(f"Documento generado, pero no se ha podido preparar la firma: {exc}", "warning")
    else:
        if signature_request and signature_email:
            send_signature_notification(
                signature_request["signer_name"],
                signature_request["signer_email"],
                generated_document["template_name"],
                generated_document["id"],
            )
            flash(
                f"Se ha avisado a {signature_request['signer_name']} para que firme {generated_document['template_name']}.",
                "info",
            )
            log_action("signature_request", "document", case_id, generated_document["template_name"])
    if inferred_status == "propuesta_resolucion":
        refreshed_case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        instructor_email = normalize_email(refreshed_case["instructor_email"] or "")
        instructor_name = refreshed_case["instructor_name"] or ""
        still_has_active_cases = instructor_has_active_cases(instructor_email) if instructor_email else False
        if instructor_email and instructor_phase_finished(refreshed_case["status"]):
            send_instruction_completed_email(
                instructor_name,
                instructor_email,
                refreshed_case["case_number"],
                still_has_active_cases,
            )
        flash(
            "Documento 09 generado. La fase de instrucción queda lista para pasar a dirección. Revisa que todo esté completo y avisa en oficina para que coordinen la cita con la familia y el director.",
            "warning",
        )
        if instructor_email and not still_has_active_cases:
            flash(
                f"El instructor {instructor_name or instructor_email} ya no podrá volver a pedir códigos de acceso si no se le asigna otro expediente en fase de instrucción.",
                "warning",
            )
    log_action("generate", "document", case_id, template_name)
    flash("Documento generado.", "success")
    return redirect(url_for("main.case_detail", case_id=case_id))


@main_bp.post("/documents/<int:document_id>/send-for-signature")
@login_required
def send_document_for_signature(document_id: int):
    flash("La firma ya se prepara automáticamente al generar el documento.", "info")
    return redirect(request.referrer or url_for("main.cases"))


@main_bp.get("/cases/<int:case_id>/export")
@login_required
def export_case_zip(case_id: int):
    case = get_case(case_id)
    if not user_can_access_case(case):
        flash("No tienes permiso para exportar este expediente.", "error")
        return redirect(url_for("main.cases"))

    latest_documents = get_case_documents(case_id)
    latest_documents = [document for document in latest_documents if document["is_latest"]]
    if not latest_documents:
        flash("Todavía no hay documentos generados para exportar.", "error")
        return redirect(url_for("main.case_detail", case_id=case_id))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for document in latest_documents:
            file_path = Path(document["output_path"])
            if file_path.exists():
                archive.write(file_path, arcname=file_path.name)
            if document.get("signed_pdf_path"):
                signed_path = Path(document["signed_pdf_path"])
                if signed_path.exists():
                    archive.write(signed_path, arcname=signed_path.name)

    buffer.seek(0)
    zip_name = f"expediente-{safe_filename(case['case_number'])}.zip"
    return send_file(buffer, as_attachment=True, download_name=zip_name, mimetype="application/zip")


@main_bp.get("/documents/<int:document_id>/download")
@login_required
def download_document(document_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM generated_documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        return redirect(url_for("main.dashboard"))
    case = db.execute("SELECT * FROM cases WHERE id = ?", (row["case_id"],)).fetchone()
    if not user_can_access_case(case):
        flash("No tienes permiso para descargar este documento.", "error")
        return redirect(url_for("main.cases"))
    return send_file(row["output_path"], as_attachment=True)


@main_bp.get("/documents/<int:document_id>/sign")
@login_required
def signature_sign_page(document_id: int):
    document = get_signature_request_for_document(document_id)
    if document is None:
        flash("El documento no tiene una firma pendiente asociada.", "error")
        return redirect(url_for("main.dashboard"))

    case = get_case(document["case_id"])
    if not user_can_access_case(case):
        flash("No tienes permiso para acceder a este expediente.", "error")
        return redirect(url_for("main.cases"))

    if normalize_email(document["signer_email"]) != current_user_email():
        flash("Este documento no te corresponde para firma.", "error")
        return redirect(url_for("main.case_detail", case_id=document["case_id"]))

    if not document["is_latest"]:
        flash("Solo se puede firmar la última versión de cada documento.", "error")
        return redirect(url_for("main.case_detail", case_id=document["case_id"]))

    if (document["signature_status"] or "") == "signed":
        flash("Ese documento ya está firmado.", "info")
        return redirect(url_for("main.case_detail", case_id=document["case_id"]))

    return render_template(
        "signatures/sign.html",
        case=case,
        document=document,
        csrf_token=get_signature_csrf_token(),
        signature_style_options=SIGNATURE_STYLE_OPTIONS,
    )


@main_bp.get("/documents/<int:document_id>/signature-preview")
@login_required
def signature_preview(document_id: int):
    document = get_signature_request_for_document(document_id)
    if document is None:
        return redirect(url_for("main.dashboard"))

    case = get_case(document["case_id"])
    if not user_can_access_case(case):
        flash("No tienes permiso para ver esta vista previa.", "error")
        return redirect(url_for("main.cases"))

    if (document["signature_status"] or "") == "signed" and document["signed_pdf_path"]:
        preview_path = Path(document["signed_pdf_path"])
    else:
        try:
            preview_path = build_unsigned_pdf(document, document)
        except SignatureIntegrationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("main.case_detail", case_id=document["case_id"]))

    return send_file(preview_path, mimetype="application/pdf")


@main_bp.get("/api/signatures/<int:document_id>/prepare")
@login_required
def prepare_signature(document_id: int):
    document = get_signature_request_for_document(document_id)
    if document is None:
        return jsonify({"error": "El documento no tiene firma pendiente."}), 404

    if normalize_email(document["signer_email"]) != current_user_email():
        return jsonify({"error": "No autorizado."}), 403

    if not document["is_latest"]:
        return jsonify({"error": "Solo se puede firmar la última versión."}), 409

    if (document["signature_status"] or "") != "pending_signature":
        return jsonify({"error": "La firma ya no está pendiente."}), 409

    style_key = request.args.get("style", "institucional").strip().lower()
    if style_key not in SIGNATURE_STYLE_OPTIONS:
        return jsonify({"error": "El estilo de firma solicitado no es válido."}), 400

    try:
        pdf_path = build_unsigned_pdf(document, document)
        pdf_base64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
    except SignatureIntegrationError as exc:
        return jsonify({"error": str(exc)}), 400

    detail_url = signature_sign_url(document_id)
    extra_params = build_signature_extra_params(
        document["signer_name"],
        detail_url,
        document["signer_role"],
        style_key,
    )
    return jsonify(
        {
            "status": "success",
            "pdf_base64": pdf_base64,
            "extra_params": extra_params,
            "style": style_key,
        }
    )


@main_bp.post("/api/signatures/<int:document_id>/save")
@login_required
def save_signature(document_id: int):
    document = get_signature_request_for_document(document_id)
    if document is None:
        return jsonify({"error": "El documento no tiene firma pendiente."}), 404

    if normalize_email(document["signer_email"]) != current_user_email():
        return jsonify({"error": "No autorizado."}), 403

    if not document["is_latest"]:
        return jsonify({"error": "Solo se puede firmar la última versión."}), 409

    expected_token = session.get("signature_csrf_token", "")
    received_token = request.headers.get("X-CSRF-Token", "")
    if not expected_token or not received_token or received_token != expected_token:
        return jsonify({"error": "CSRF token inválido."}), 403

    if (document["signature_status"] or "") == "signed":
        return jsonify({"error": "El documento ya está firmado."}), 409

    payload = request.get_json(silent=True) or {}
    signed_b64 = payload.get("signed_b64", "")
    if not signed_b64:
        return jsonify({"error": "No se ha recibido el PDF firmado."}), 400

    try:
        signed_bytes = base64.b64decode(signed_b64, validate=True)
    except Exception:
        return jsonify({"error": "La firma recibida no es válida."}), 400

    if not signed_bytes.startswith(b"%PDF"):
        return jsonify({"error": "El documento firmado no es un PDF válido."}), 400

    unsigned_pdf = Path(document["pdf_path"]) if document["pdf_path"] else build_unsigned_pdf(document, document)
    signed_path = build_signed_pdf_path(unsigned_pdf, document["signer_role"])
    signed_path.write_bytes(signed_bytes)

    db = get_db()
    db.execute(
        """
        UPDATE signature_requests
        SET status = 'signed',
            signed_pdf_path = ?,
            completed_at = CURRENT_TIMESTAMP,
            last_error = NULL
        WHERE id = ?
        """,
        (str(signed_path), document["id"]),
    )
    db.commit()
    log_action("sign", "document", document["case_id"], document["template_name"])
    return jsonify({"status": "success"})


@main_bp.get("/signatures/<int:document_id>/download")
@login_required
def download_signed_document(document_id: int):
    document = get_signature_request_for_document(document_id)
    if document is None or not document["signed_pdf_path"]:
        flash("No existe un PDF firmado para este documento.", "error")
        return redirect(url_for("main.dashboard"))

    case = get_case(document["case_id"])
    if not user_can_access_case(case):
        flash("No tienes permiso para descargar este PDF firmado.", "error")
        return redirect(url_for("main.cases"))

    return send_file(document["signed_pdf_path"], as_attachment=True)


@main_bp.route("/storage", methods=("GET", "POST"))
@main_bp.route("/retriever", methods=("GET", "POST"))
def autofirma_bridge():
    operation = request.values.get("op", "")
    item_id = request.values.get("id", "")

    if operation == "put":
        payload = request.values.get("dat", "")
        if not item_id or not payload:
            return ("err-01:=Missing parameters", 400, {"Content-Type": "text/plain; charset=utf-8"})
        db = get_db()
        db.execute(
            """
            INSERT INTO intermediate_store (id, payload, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, created_at = CURRENT_TIMESTAMP
            """,
            (item_id, payload),
        )
        db.commit()
        return ("OK", 200, {"Content-Type": "text/plain; charset=utf-8"})

    if operation == "get":
        if not item_id:
            return ("err-01:=Missing id", 400, {"Content-Type": "text/plain; charset=utf-8"})
        row = get_db().execute("SELECT payload FROM intermediate_store WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return ("err-06:=No data", 200, {"Content-Type": "text/plain; charset=utf-8"})
        return (row["payload"], 200, {"Content-Type": "text/plain; charset=utf-8"})

    return ("OK", 200, {"Content-Type": "text/plain; charset=utf-8"})


@main_bp.post("/documents/<int:document_id>/delete")
@admin_required
def delete_document(document_id: int):
    db = get_db()
    row = db.execute(
        """
        SELECT generated_documents.*, signature_requests.pdf_path, signature_requests.signed_pdf_path
        FROM generated_documents
        LEFT JOIN signature_requests ON signature_requests.generated_document_id = generated_documents.id
        WHERE generated_documents.id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        flash("El documento no existe.", "error")
        return redirect(url_for("main.dashboard"))

    for key in ("output_path", "pdf_path", "signed_pdf_path"):
        if row[key]:
            path = Path(row[key])
            if path.exists():
                path.unlink()

    parent = Path(row["output_path"]).parent
    if parent.exists():
        shutil.rmtree(parent / "signed", ignore_errors=True)
        try:
            (parent / "pdf").rmdir()
        except OSError:
            pass
        try:
            parent.rmdir()
        except OSError:
            pass

    db.execute("DELETE FROM generated_documents WHERE id = ?", (document_id,))
    db.commit()
    log_action("delete", "document", row["case_id"], row["template_name"])
    flash("Documento borrado.", "success")
    return redirect(url_for("main.case_detail", case_id=row["case_id"]))
