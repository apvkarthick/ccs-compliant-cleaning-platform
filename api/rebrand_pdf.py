"""PDF SDS rebranding using PyMuPDF — text redaction + logo replacement."""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

from .rebrand import CCS, LOGO_PATH, _supplier_search_terms

_OLD_DOMAINS = ["cleanplus.com.au"]

# Labels to scan for in both inline and two-column table layouts
_SUPPLIER_LABELS = ["Supplier Name", "Company Name", "Supplier", "Manufacturer Name"]
_ADDRESS_LABELS = ["Address"]
_PHONE_LABELS = ["Telephone", "Phone", "Tel"]


def rebrand_pdf(pdf_bytes: bytes, sds_date: str | None = None) -> tuple[bytes, dict]:
    today = sds_date or date.today().strftime("%d/%m/%Y")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    old_supplier, old_address, old_phone = _detect_supplier_fields(doc)
    search_terms = _supplier_search_terms(old_supplier) if old_supplier else []
    changes: list[str] = []

    for page in doc:
        page_changes = _replace_text_on_page(page, search_terms, old_address, old_phone)
        changes.extend(page_changes)

    _replace_link_annotations(doc, changes)

    if LOGO_PATH.exists():
        if _replace_header_image(doc, LOGO_PATH.read_bytes()):
            changes.append("Logo replaced")

    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    doc.close()

    return out.getvalue(), {"changes": changes, "old_supplier": old_supplier}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_supplier_fields(doc: fitz.Document) -> tuple[str, str, str]:
    """Return (supplier_name, address, phone) detected from page 1."""
    if not doc.page_count:
        return "", "", ""

    page = doc[0]

    # Pass 1 — inline: label and value on the same line
    for line in page.get_text("text").splitlines():
        stripped = line.strip()
        for label in _SUPPLIER_LABELS:
            if re.match(re.escape(label), stripped, re.IGNORECASE):
                after = stripped[len(label):].strip().lstrip(":").strip()
                if after:
                    return after, "", ""

    # Pass 2 — spatial: two-column table where labels are in a left block
    # and values are in a right block at the same vertical band
    return _detect_fields_spatial(page)


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
) -> list[str]:
    changes: list[str] = []

    replacements: list[tuple[str, str]] = []

    for term in supplier_terms:
        replacements.append((term, CCS["supplier_name"]))

    if old_address:
        replacements.append((old_address, CCS["address"]))
    if old_phone:
        replacements.append((old_phone, CCS["telephone"]))

    # Hardcoded domain/email replacements for known old suppliers
    replacements += [
        ("www.cleanplus.com.au", CCS["website"]),
        ("cleanplus.com.au", CCS["website"]),
        ("info@cleanplus.com.au", CCS["email"]),
        ("sales@cleanplus.com.au", CCS["email"]),
    ]

    for old_text, new_text in replacements:
        if not old_text:
            continue
        hits = page.search_for(old_text)
        for rect in hits:
            page.add_redact_annot(rect, text=new_text, fontsize=0, align=fitz.TEXT_ALIGN_LEFT)
            changes.append(f"Replaced '{old_text[:40]}'")

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
            if not uri:
                continue
            new_uri = uri
            if any(d in uri.lower() for d in _OLD_DOMAINS):
                if "mailto:" in uri.lower():
                    new_uri = f"mailto:{CCS['email']}"
                else:
                    new_uri = f"http://{CCS['website']}/"
            if new_uri != uri:
                link["uri"] = new_uri
                page.update_link(link)
                changes.append(f"Updated link {uri[:40]}")


# ---------------------------------------------------------------------------
# Logo replacement
# ---------------------------------------------------------------------------

def _replace_header_image(doc: fitz.Document, logo_bytes: bytes) -> bool:
    """Replace the image in the top 35% of page 1 with the CCS logo."""
    if not doc.page_count:
        return False
    page = doc[0]
    page_height = page.rect.height

    # Map each xref to its on-page position using get_image_rects
    candidates = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
            for r in rects:
                y_center = (r.y0 + r.y1) / 2
                candidates.append((y_center, xref))
        except Exception:
            pass

    # Replace the topmost image that sits in the top 35% of the page
    candidates.sort(key=lambda c: c[0])
    for y_center, xref in candidates:
        if y_center < page_height * 0.35:
            try:
                page.replace_image(xref, stream=logo_bytes)
                return True
            except Exception:
                pass

    # Fallback: replace topmost image regardless of position
    if candidates:
        try:
            page.replace_image(candidates[0][1], stream=logo_bytes)
            return True
        except Exception:
            pass

    return False
