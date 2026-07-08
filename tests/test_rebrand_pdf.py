import hashlib
import io

import fitz

from api.rebrand_pdf import rebrand_pdf

def _solid_png(color: int) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), 0)
    pix.clear_with(color)
    return pix.tobytes("png")


def _make_pdf_with_supplier_body_and_two_logos() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page()
    red_png = _solid_png(0xFF0000)
    blue_png = _solid_png(0x0000FF)

    p1.insert_text((60, 60), "Supplier Name CLEAN PLUS CHEMICALS PTY LTD", fontsize=11)
    p1.insert_text((60, 80), "Address 12 OLD STREET", fontsize=11)
    p1.insert_text((60, 100), "Telephone 1800 000 000", fontsize=11)
    p1.insert_image(fitz.Rect(430, 35, 560, 95), stream=red_png)

    p2 = doc.new_page()
    p2.insert_text((60, 60), "CLEAN PLUS CHEMICALS PTY LTD", fontsize=11)
    p2.insert_text(
        (60, 640),
        "This report has been compiled by CLEAN PLUS CHEMICALS and should remain readable.",
        fontsize=11,
    )
    p2.insert_image(fitz.Rect(430, 35, 560, 95), stream=blue_png)

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _top_image_digest(doc: fitz.Document, page_index: int) -> str:
    page = doc[page_index]
    candidates = []
    for img in page.get_images(full=True):
        xref = img[0]
        for rect in page.get_image_rects(xref):
            y_center = (rect.y0 + rect.y1) / 2
            candidates.append((y_center, xref))
    candidates.sort(key=lambda item: item[0])
    xref = candidates[0][1]
    img_bytes = doc.extract_image(xref)["image"]
    return hashlib.sha256(img_bytes).hexdigest()


def test_rebrand_pdf_does_not_replace_supplier_name_in_page2_body_text() -> None:
    src = _make_pdf_with_supplier_body_and_two_logos()
    out_bytes, _summary = rebrand_pdf(src, "08/07/2026")
    out = fitz.open(stream=out_bytes, filetype="pdf")

    page2_text = out[1].get_text("text")
    out.close()

    assert "compiled by CLEAN PLUS CHEMICALS" in page2_text
    assert "compiled by Compliant Cleaning Supplies" not in page2_text


def test_rebrand_pdf_replaces_header_logo_on_all_pages() -> None:
    src = _make_pdf_with_supplier_body_and_two_logos()
    out_bytes, _summary = rebrand_pdf(src, "08/07/2026")
    out = fitz.open(stream=out_bytes, filetype="pdf")

    digest_p1 = _top_image_digest(out, 0)
    digest_p2 = _top_image_digest(out, 1)
    out.close()

    assert digest_p1 == digest_p2
