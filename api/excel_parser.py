from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

from openpyxl import load_workbook


PRODUCT_START_ROW = 16
PRODUCT_END_ROW = 120


def parse_chemical_register(
    workbook_bytes: bytes,
    *,
    source_files: list[str] | None = None,
    public_base_url: str = "",
) -> dict[str, Any]:
    workbook = load_workbook(BytesIO(workbook_bytes), data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    files = source_files or []

    products = []
    for row_number in range(PRODUCT_START_ROW, PRODUCT_END_ROW + 1):
        code = _clean(sheet.cell(row=row_number, column=1).value)
        name = _clean(sheet.cell(row=row_number, column=2).value)
        if not code or not name:
            continue
        if _looks_like_header_or_category(code, name):
            continue
        if not _is_selected(sheet.cell(row=row_number, column=14).value):
            continue

        sds_file = _match_sds_file(code, files)
        risk_file = _match_risk_file(code, files)

        products.append(
            {
                "row": row_number,
                "code": code,
                "name": name,
                "hazardous": _clean(sheet.cell(row=row_number, column=3).value),
                "un_number": _clean(sheet.cell(row=row_number, column=4).value),
                "max_quantity": _clean(sheet.cell(row=row_number, column=5).value),
                "risk_required": _truthy_label(sheet.cell(row=row_number, column=6).value),
                "hazchem": _clean(sheet.cell(row=row_number, column=7).value),
                "class": _clean(sheet.cell(row=row_number, column=8).value),
                "packing_group": _clean(sheet.cell(row=row_number, column=9).value),
                "use": _clean(sheet.cell(row=row_number, column=10).value),
                "sds_expiry": _clean(sheet.cell(row=row_number, column=11).value),
                "sds": _document_result(sds_file, public_base_url),
                "risk_assessment": _document_result(risk_file, public_base_url),
            }
        )

    missing_documents = [
        {
            "code": product["code"],
            "name": product["name"],
            "missing": [
                label
                for label, key in [("SDS", "sds"), ("Risk Assessment", "risk_assessment")]
                if not product[key]["matched"] and (key == "sds" or product["risk_required"])
            ],
        }
        for product in products
    ]

    return {
        "customer": {
            "company": _clean(sheet["C8"].value),
            "contact_name": _clean(sheet["C10"].value),
            "phone": _clean(sheet["C12"].value),
            "email": _find_email(sheet),
        },
        "register": {
            "title": _clean(sheet["B7"].value) or "Chemical Register",
            "date": _clean(sheet["C9"].value),
            "sheet": sheet.title,
            "product_count": len(products),
        },
        "products": products,
        "missing_documents": [item for item in missing_documents if item["missing"]],
    }


def list_source_documents(source_dir: Path) -> list[str]:
    if not source_dir.exists():
        return []
    return sorted(path.name for path in source_dir.iterdir() if path.is_file())


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _looks_like_header_or_category(code: str, name: str) -> bool:
    lowered = f"{code} {name}".lower()
    return "product code" in lowered or code.lower().endswith("range")


def _is_selected(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().lower() in {"1", "yes", "y", "true", "selected", "x"}


def _truthy_label(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return str(value).strip().lower() in {"yes", "y", "true", "required", "available", "1"}


def _document_result(filename: str | None, public_base_url: str) -> dict[str, Any]:
    if not filename:
        return {"matched": False, "filename": None, "url": None}
    base = public_base_url.rstrip("/")
    quoted = quote(filename)
    return {
        "matched": True,
        "filename": filename,
        "url": f"{base}/api/documents/source/{quoted}" if base else f"/api/documents/source/{quoted}",
    }


def _match_sds_file(code: str, files: list[str]) -> str | None:
    aliases = _code_aliases(code)
    return _first_matching_file(files, aliases, risk=False)


def _match_risk_file(code: str, files: list[str]) -> str | None:
    aliases = [f"risk_{alias}" for alias in _code_aliases(code)]
    return _first_matching_file(files, aliases, risk=True)


def _code_aliases(code: str) -> list[str]:
    normalized = _normalize(code)
    aliases = [normalized]
    if normalized.endswith("f"):
        aliases.append(normalized[:-1])
    return aliases


def _first_matching_file(files: list[str], aliases: list[str], *, risk: bool) -> str | None:
    for filename in files:
        normalized = _normalize(filename)
        is_risk_file = normalized.startswith("risk_")
        if risk != is_risk_file:
            continue
        if any(normalized.startswith(alias) for alias in aliases):
            return filename
    return None


def _normalize(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def _find_email(sheet: Any) -> str:
    for row in sheet.iter_rows(min_row=1, max_row=25, values_only=True):
        for value in row:
            text = _clean(value)
            if "@" in text and "." in text:
                return text
    return ""
