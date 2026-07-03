"""PDF SDS rebranding using PyMuPDF — text redaction + logo replacement."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

from .rebrand import CCS, LOGO_PATH, _supplier_search_terms

_OLD_DOMAINS = ["cleanplus.com.au"]
_OLD_EMAIL_PATTERNS = ["@cleanplus"]


def rebrand_pdf(pdf_bytes: bytes, sds_date: str | None = None) -> tuple[bytes, dict]:
    today = sds_date or date.today().strftime("%d/%m/%Y")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    old_supplier = _detect_supplier_from_pdf(doc)
    search_terms = _supplier_search_terms(old_supplier) if old_supplier else []
    changes: list[str] = []

    for page in doc:
        page_changes = _replace_text_on_page(page, search_terms)
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

def _detect_supplier_from_pdf(doc: fitz.Document) -> str:
    if not doc.page_count:
        return ""
    text = doc[0].get_text("text")
    for line in text.splitlines():
        if "Supplier Name" in line:
            after = line[line.index("Supplier Name") + len("Supplier Name"):]
            after = after.lstrip(":\t ").strip()
            if after:
                return after
    return ""


# ---------------------------------------------------------------------------
# Text redaction
# ---------------------------------------------------------------------------

def _replace_text_on_page(page: fitz.Page, supplier_terms: list[str]) -> list[str]:
    changes: list[str] = []

    for term in supplier_terms:
        hits = page.search_for(term)
        for rect in hits:
            page.add_redact_annot(rect, text=CCS["supplier_name"], fontsize=0, align=fitz.TEXT_ALIGN_LEFT)
            changes.append(f"Replaced supplier name '{term}'")

    # Replace domain/email text occurrences
    for old_text, new_text in [
        ("www.cleanplus.com.au", CCS["website"]),
        ("cleanplus.com.au", CCS["website"]),
        ("info@cleanplus.com.au", CCS["email"]),
        ("sales@cleanplus.com.au", CCS["email"]),
    ]:
        hits = page.search_for(old_text)
        for rect in hits:
            page.add_redact_annot(rect, text=new_text, fontsize=0)
            changes.append(f"Replaced '{old_text}'")

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
    """Replace the first image in the top 35% of page 1 with the CCS logo."""
    if not doc.page_count:
        return False
    page = doc[0]
    page_height = page.rect.height

    img_info_list = page.get_image_info(hashes=False)
    # Sort by vertical position (top of bbox)
    img_info_list.sort(key=lambda x: x.get("bbox", (0, 0, 0, 0))[1])

    for info in img_info_list:
        bbox = info.get("bbox", (0, 0, page.rect.width, page_height))
        y_center = (bbox[1] + bbox[3]) / 2
        xref = info.get("xref", 0)
        if xref and y_center < page_height * 0.35:
            try:
                doc.replace_image(xref, stream=logo_bytes)
                return True
            except Exception:
                pass

    # Fallback: replace very first image anywhere on the page
    all_imgs = page.get_images(full=True)
    if all_imgs:
        try:
            doc.replace_image(all_imgs[0][0], stream=logo_bytes)
            return True
        except Exception:
            pass

    return False
