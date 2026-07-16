"""PDF SDS rebranding using PyMuPDF — text redaction + logo replacement."""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

from .rebrand import CCS, _BRAND_LOGOS, _supplier_search_terms

_OLD_DOMAINS = ["cleanplus.com.au"]

# Labels to scan for in both inline and two-column table layouts
_SUPPLIER_LABELS = ["Supplier Name", "Company Name", "Supplier", "Manufacturer Name"]
_ADDRESS_LABELS = ["Address"]
_PHONE_LABELS = ["Emergency Telephone", "Telephone", "Phone", "Tel"]
_CCS_BODY_SUPPLIER_NAME = "Compliant Cleaning Supplies"
_PAGE1_SUPPLIER_Y_RATIO = 0.50
_OTHER_PAGE_SUPPLIER_Y_RATIO = 0.22
_HEADER_LOGO_Y_RATIO = 0.35
_HEADER_LOGO_RIGHT_X_RATIO = 0.45


def _detect_sds_date(doc: fitz.Document) -> str:
    """Extract the SDS date value from page 1."""
    if not doc.page_count:
        return ""
    text = doc[0].get_text("text")
    m = re.search(
        r'(?:SDS\s*Date|Issue\s*Date|Date\s*of\s*Issue|Revision\s*Date)[:\t\s\n]+(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        text, re.IGNORECASE,
    )
    return m.group(1) if m else ""


def rebrand_pdf(pdf_bytes: bytes, sds_date: str | None = None, brand: str = "spill_crew") -> tuple[bytes, dict]:
    today = sds_date or date.today().strftime("%d/%m/%Y")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    old_supplier, old_address, old_phone, old_emergency_phone = _detect_supplier_fields(doc)
    old_sds_date = _detect_sds_date(doc)
    search_terms = _supplier_search_terms(old_supplier) if old_supplier else []
    changes: list[str] = []

    for page_idx, page in enumerate(doc):
        page_changes = _replace_text_on_page(
            page, search_terms, old_address, old_phone, old_emergency_phone, old_sds_date, today,
            page_index=page_idx,
        )
        changes.extend(page_changes)

    _replace_link_annotations(doc, changes)

    logo_path = _BRAND_LOGOS.get(brand)
    if logo_path and logo_path.exists():
        logo_changes = _replace_header_images(
            doc,
            logo_path.read_bytes(),
            insert_if_missing=(brand == "solopak"),
        )
        if logo_changes:
            changes.append(f"Logo replaced on {logo_changes} page(s)")

    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    doc.close()

    return out.getvalue(), {"changes": changes, "old_supplier": old_supplier}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_supplier_fields(doc: fitz.Document) -> tuple[str, str, str, str]:
    """Return (supplier_name, address, phone, emergency_phone) detected from page 1."""
    if not doc.page_count:
        return "", "", "", ""

    page = doc[0]
    lines = page.get_text("text").splitlines()

    # Pass 1 — scan all lines; detect inline supplier and next-line phone/address
    supplier = address = phone = emergency_phone = ""
    for i, line in enumerate(lines):
        stripped = line.strip()

        if not supplier:
            for label in _SUPPLIER_LABELS:
                if re.match(re.escape(label), stripped, re.IGNORECASE):
                    after = stripped[len(label):].strip().lstrip(":").strip()
                    if after:
                        supplier = after
                        break

        if not phone or not emergency_phone:
            for label in _PHONE_LABELS:
                if re.match(re.escape(label), stripped, re.IGNORECASE):
                    after = stripped[len(label):].strip().lstrip(":").strip()
                    if after:
                        if label.lower().startswith("emergency"):
                            emergency_phone = after
                        else:
                            phone = after
                    else:
                        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                        if nxt:
                            if label.lower().startswith("emergency"):
                                emergency_phone = nxt
                            else:
                                phone = nxt
                    break

        if not address:
            for label in _ADDRESS_LABELS:
                if re.match(re.escape(label) + r'\s*:?\s*$', stripped, re.IGNORECASE):
                    after = stripped[len(label):].strip().lstrip(":").strip()
                    if after:
                        address = after
                    else:
                        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                        if nxt:
                            address = nxt
                    break

    if supplier:
        return supplier, address, phone, emergency_phone

    # Pass 2 — spatial: two-column table where labels are in a left block
    # and values are in a right block at the same vertical band
    supplier, address, phone = _detect_fields_spatial(page)
    return supplier, address, phone, emergency_phone


def _detect_fields_spatial(page: fitz.Page) -> tuple[str, str, str]:
    page_width = page.rect.width
    blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,block_type)

    for block in blocks:
        x0, y0, x1, y1, text = block[:5]
        # Only look at left-side label blocks (left 45% of page)
        if x0 > page_width * 0.45:
            continue

        lines = text.splitlines()
        non_empty = [l.strip() for l in lines if l.strip()]

        supplier_idx = address_idx = phone_idx = -1
        for i, line in enumerate(non_empty):
            for lbl in _SUPPLIER_LABELS:
                if re.match(re.escape(lbl), line, re.IGNORECASE):
                    supplier_idx = i
            for lbl in _ADDRESS_LABELS:
                if re.match(re.escape(lbl), line, re.IGNORECASE):
                    address_idx = i
            for lbl in _PHONE_LABELS:
                if re.match(re.escape(lbl), line, re.IGNORECASE):
                    phone_idx = i

        if supplier_idx == -1:
            continue

        # Find the matching right-side value block at the same y-band
        by_center = (y0 + y1) / 2
        right_blocks = [
            b for b in blocks
            if b[0] > x1 + 5 and abs((b[1] + b[3]) / 2 - by_center) < 40
        ]
        if not right_blocks:
            continue
        # Pick the closest one to the right
        right_blocks.sort(key=lambda b: b[0])
        rtext = right_blocks[0][4]
        rlines = [l.strip() for l in rtext.splitlines() if l.strip()]

        def get_rline(idx: int) -> str:
            return rlines[idx] if 0 <= idx < len(rlines) else ""

        supplier = get_rline(supplier_idx)
        address = get_rline(address_idx) if address_idx != -1 else ""
        phone = get_rline(phone_idx) if phone_idx != -1 else ""
        if supplier:
            return supplier, address, phone

    return "", "", ""


# ---------------------------------------------------------------------------
# Text redaction
# ---------------------------------------------------------------------------

def _replace_text_on_page(
    page: fitz.Page,
    supplier_terms: list[str],
    old_address: str,
    old_phone: str,
    old_emergency_phone: str,
    old_date: str = "",
    new_date: str = "",
    page_index: int = 0,
) -> list[str]:
    changes: list[str] = []
    page_height = page.rect.height
    page_width = page.rect.width
    # Keep supplier-name replacements in header space to avoid body-text artifacts.
    header_ratio = _PAGE1_SUPPLIER_Y_RATIO if page_index == 0 else _OTHER_PAGE_SUPPLIER_Y_RATIO
    header_y_max = page_height * header_ratio

    # Header-restricted replacements (supplier name, address, phone)
    header_replacements: list[tuple[str, str]] = []
    for term in supplier_terms:
        header_replacements.append((term, CCS["supplier_name"]))
    if old_address:
        header_replacements.append((old_address, CCS["address"]))
    if old_phone:
        header_replacements.append((old_phone, CCS["telephone"]))

    # All-page replacements (date, URLs, emails)
    full_replacements: list[tuple[str, str]] = []
    if old_date and new_date:
        full_replacements.append((old_date, new_date))
        for label in ("Issue Date", "Date of Issue", "SDS Date", "Revision Date"):
            full_replacements.append((f"{label}: {old_date}", f"{label}: {new_date}"))
    if old_emergency_phone:
        full_replacements.append((old_emergency_phone, f"Poisons Information Centre (National) {CCS['emergency']}"))
        full_replacements.append((
            f"Emergency Telephone: {old_emergency_phone}",
            f"Emergency Telephone: Poisons Information Centre (National) {CCS['emergency']}",
        ))
    page_text = page.get_text("text")
    for url in re.findall(r'https?://[^\s<>"\']+|www\.[^\s<>"\']+', page_text, re.IGNORECASE):
        if "compliantcs.com.au" not in url.lower():
            full_replacements.append((url, CCS["website"]))
    for email in re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', page_text):
        if "compliantcs.com.au" not in email.lower():
            full_replacements.append((email, CCS["email"]))

    def _redact(
        old_text: str,
        new_text: str,
        y_max: float,
        y_min: float = 0.0,
        min_ratio: float = 1.0,
        max_ratio: float = 1.45,
        width_pad: float = 1.08,
    ) -> None:
        if not old_text:
            return
        for rect in page.search_for(old_text):
            if rect.y0 > y_max or rect.y0 < y_min:
                continue
            char_ratio = len(new_text) / max(len(old_text), 1)
            safe_ratio = min(max(char_ratio, min_ratio), max_ratio)
            expanded = fitz.Rect(
                rect.x0, rect.y0,
                min(rect.x0 + rect.width * safe_ratio * width_pad, page_width - 4),
                rect.y1,
            )
            page.add_redact_annot(expanded, text=new_text, fontsize=9, align=fitz.TEXT_ALIGN_LEFT)
            changes.append(f"Replaced '{old_text[:40]}'")

    for old_text, new_text in header_replacements:
        _redact(old_text, new_text, header_y_max)
    # Keep body paragraph replacements, but use a shorter supplier string to reduce visual artifacts.
    for term in supplier_terms:
        _redact(
            term,
            _CCS_BODY_SUPPLIER_NAME,
            page_height,
            y_min=header_y_max,
            min_ratio=0.9,
            max_ratio=1.0,
            width_pad=1.0,
        )
    for old_text, new_text in full_replacements:
        _redact(old_text, new_text, page_height)

    if changes:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    return changes


# ---------------------------------------------------------------------------
# Hyperlink annotations
# ---------------------------------------------------------------------------

def _replace_link_annotations(doc: fitz.Document, changes: list[str]) -> None:
    for page in doc:
        for link in page.get_links():
            uri = link.get("uri", "")
            if not uri or "compliantcs.com.au" in uri.lower():
                continue
            new_uri = uri
            if uri.lower().startswith("mailto:"):
                new_uri = f"mailto:{CCS['email']}"
            elif uri.startswith(("http://", "https://")):
                new_uri = CCS["website"]
            if new_uri != uri:
                link["uri"] = new_uri
                page.update_link(link)
                changes.append(f"Updated link {uri[:40]}")


# ---------------------------------------------------------------------------
# Logo replacement
# ---------------------------------------------------------------------------

def _replace_header_images(doc: fitz.Document, logo_bytes: bytes, insert_if_missing: bool = False) -> int:
    """Replace one header logo per page, preferring top-right candidates."""
    replaced = 0
    for page in doc:
        xref = _select_header_logo_xref(page, allow_fallback=not insert_if_missing)
        if xref is None:
            if insert_if_missing:
                _insert_header_logo(page, logo_bytes)
                replaced += 1
            continue
        try:
            page.replace_image(xref, stream=logo_bytes)
            replaced += 1
        except Exception:
            pass
    return replaced


def _select_header_logo_xref(page: fitz.Page, allow_fallback: bool = True) -> int | None:
    page_height = page.rect.height
    page_width = page.rect.width
    ranked: dict[int, tuple[int, float, float]] = {}

    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue

        for rect in rects:
            y_center = (rect.y0 + rect.y1) / 2
            in_header = y_center < page_height * _HEADER_LOGO_Y_RATIO
            if not in_header:
                continue
            right_side = 0 if rect.x0 > page_width * _HEADER_LOGO_RIGHT_X_RATIO else 1
            rank = (right_side, y_center, -rect.x0)
            if xref not in ranked or rank < ranked[xref]:
                ranked[xref] = rank

    if ranked:
        return min(ranked.items(), key=lambda item: item[1])[0]

    # Fallback: topmost image on page.
    fallback: list[tuple[float, int]] = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for rect in rects:
            y_center = (rect.y0 + rect.y1) / 2
            fallback.append((y_center, xref))
    if not allow_fallback or not fallback:
        return None
    fallback.sort(key=lambda item: item[0])
    return fallback[0][1]


def _insert_header_logo(page: fitz.Page, logo_bytes: bytes) -> None:
    rect = fitz.Rect(page.rect.width - 180, 18, page.rect.width - 18, 74)
    try:
        page.insert_image(rect, stream=logo_bytes, keep_proportion=True)
    except Exception:
        pass
