from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import xlrd


XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def clean_excel_text(value: str) -> str:
    return str(value or "").replace("\xa0", " ").strip()


def normalize_email(value: str) -> str:
    return clean_excel_text(value).lower()


def format_person_name(value: str) -> str:
    cleaned = clean_excel_text(value)
    if "," not in cleaned:
        return cleaned
    last_name, first_name = [part.strip() for part in cleaned.split(",", 1)]
    return clean_excel_text(f"{first_name} {last_name}")


def instructor_search_text(instructor: dict) -> str:
    return clean_excel_text(
        f"{instructor['name']} {instructor['raw_name']} {instructor['email']} "
        f"{instructor['role']} {instructor['idea_user']}"
    ).lower()


@lru_cache(maxsize=4)
def load_instructors_from_excel_cached(excel_path: str, mtime: float) -> tuple[dict, ...]:
    path = Path(excel_path)
    with ZipFile(path) as workbook_zip:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook_zip.namelist():
            root = ET.fromstring(workbook_zip.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", XLSX_NS):
                text = "".join(node.text or "" for node in item.iterfind(".//a:t", XLSX_NS))
                shared_strings.append(clean_excel_text(text))

        workbook = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
        rels = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
        relmap = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("p:Relationship", XLSX_NS)
        }
        first_sheet = workbook.find("a:sheets", XLSX_NS)[0]
        target = "xl/" + relmap[first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]].lstrip("/")
        sheet = ET.fromstring(workbook_zip.read(target))

    instructors: list[dict] = []
    for row in sheet.find("a:sheetData", XLSX_NS):
        cells: dict[str, str] = {}
        for cell in row.findall("a:c", XLSX_NS):
            ref = cell.attrib.get("r", "")
            column = re.sub(r"\d+", "", ref)
            cell_type = cell.attrib.get("t")
            value_node = cell.find("a:v", XLSX_NS)
            value = ""
            if value_node is not None and value_node.text is not None:
                raw_value = value_node.text
                if cell_type == "s" and raw_value.isdigit():
                    value = shared_strings[int(raw_value)]
                else:
                    value = clean_excel_text(raw_value)
            cells[column] = clean_excel_text(value)

        raw_name = cells.get("A", "")
        email = normalize_email(cells.get("G", ""))
        role = cells.get("C", "")
        idea_user = cells.get("H", "")
        if not raw_name or raw_name == "Empleado/a":
            continue
        display_name = format_person_name(raw_name)
        instructor = {
            "name": display_name,
            "raw_name": raw_name,
            "email": email,
            "role": role,
            "idea_user": idea_user,
        }
        instructor["search"] = instructor_search_text(instructor)
        instructors.append(instructor)

    instructors.sort(key=lambda item: item["name"].lower())
    return tuple(instructors)


def load_instructors_from_fenicia_xls(excel_path: Path) -> list[dict]:
    book = xlrd.open_workbook(str(excel_path))
    sheet = book.sheet_by_index(0)
    header_row = None
    headers: dict[str, int] = {}

    for row_index in range(min(sheet.nrows, 12)):
        row_values = [clean_excel_text(sheet.cell_value(row_index, column)) for column in range(sheet.ncols)]
        if "Empleado/a" in row_values and "Correo electrónico" in row_values:
            header_row = row_index
            headers = {value: index for index, value in enumerate(row_values) if value}
            break

    if header_row is None:
        raise ValueError("No se han encontrado las columnas Empleado/a y Correo electrónico.")

    name_column = headers["Empleado/a"]
    email_column = headers["Correo electrónico"]
    role_column = headers.get("Puesto")
    idea_column = headers.get("Usuario IdEA")

    instructors: list[dict] = []
    for row_index in range(header_row + 1, sheet.nrows):
        raw_name = clean_excel_text(sheet.cell_value(row_index, name_column))
        if not raw_name:
            continue
        display_name = format_person_name(raw_name)
        instructor = {
            "name": display_name,
            "raw_name": raw_name,
            "email": normalize_email(sheet.cell_value(row_index, email_column)),
            "role": clean_excel_text(sheet.cell_value(row_index, role_column)) if role_column is not None else "",
            "idea_user": clean_excel_text(sheet.cell_value(row_index, idea_column)) if idea_column is not None else "",
        }
        instructor["search"] = instructor_search_text(instructor)
        instructors.append(instructor)

    instructors.sort(key=lambda item: item["name"].lower())
    return instructors


def teacher_directory_issues(instructors: list[dict]) -> list[str]:
    issues: list[str] = []
    for instructor in instructors:
        email = instructor["email"]
        if not email:
            issues.append(f"{instructor['raw_name']}: sin correo")
        elif not email.endswith("@edumelilla.es"):
            issues.append(f"{instructor['raw_name']}: {email}")
    return issues


def load_instructors_from_excel(project_root: Path) -> list[dict]:
    fenicia_path = project_root / "RelPerCen.xls"
    if fenicia_path.exists():
        return load_instructors_from_fenicia_xls(fenicia_path)

    excel_path = project_root / "todosProfesores.xlsx"
    if not excel_path.exists():
        return []
    return list(load_instructors_from_excel_cached(str(excel_path), excel_path.stat().st_mtime))


def find_instructor(project_root: Path, name_or_email: str) -> dict | None:
    target_name = format_person_name(name_or_email)
    target_email = normalize_email(name_or_email)
    for instructor in load_instructors_from_excel(project_root):
        if instructor["name"] == target_name or instructor["raw_name"] == name_or_email:
            return instructor
        if target_email and instructor["email"] == target_email:
            return instructor
    return None
