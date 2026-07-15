import hashlib
import io
import zipfile
from pathlib import Path

import fitz
from docx import Document

from api.rebrand import rebrand_sds


def _solid_png(color: int) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), 0)
    pix.clear_with(color)
    return pix.tobytes("png")


def _make_docx_with_header_logo() -> bytes:
    doc = Document()
    section = doc.sections[0]
    header = section.header
    header_para = header.paragraphs[0]
    header_para.add_run().add_picture(io.BytesIO(_solid_png(0x3366CC)))

    doc.add_paragraph("Supplier Name CLEAN PLUS CHEMICALS PTY LTD")
    doc.add_paragraph("Address 12 OLD STREET")
    doc.add_paragraph("Telephone 1800 000 000")
    doc.add_paragraph("Revision Date: 01/01/2026")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _make_docx_with_body_logo() -> bytes:
    doc = Document()
    doc.add_picture(io.BytesIO(_solid_png(0x3366CC)))
    doc.add_paragraph("Supplier Name CLEAN PLUS CHEMICALS PTY LTD")
    doc.add_paragraph("Address 12 OLD STREET")
    doc.add_paragraph("Telephone 1800 000 000")
    doc.add_paragraph("Revision Date: 01/01/2026")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _asset_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _embedded_media_digest(docx_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zf:
        media_names = sorted(name for name in zf.namelist() if name.startswith("word/media/"))
        assert media_names, "expected at least one embedded media file"
        return hashlib.sha256(zf.read(media_names[0])).hexdigest()


def test_rebrand_docx_uses_shared_logo_for_cleanplus() -> None:
    src = _make_docx_with_header_logo()
    out_bytes, _summary = rebrand_sds(src, "08/07/2026", brand="cleanplus")

    assert _embedded_media_digest(out_bytes) == _asset_digest(
        Path(r"E:\claude\ccs-compliant-cleaning-platform\api\assets\other-replacement.jpg")
    )


def test_rebrand_docx_uses_solopak_logo_for_solopak() -> None:
    src = _make_docx_with_header_logo()
    out_bytes, _summary = rebrand_sds(src, "08/07/2026", brand="solopak")

    assert _embedded_media_digest(out_bytes) == _asset_digest(
        Path(r"E:\claude\ccs-compliant-cleaning-platform\api\assets\solopak-replacement.jpg")
    )


def test_rebrand_docx_replaces_body_logo_when_no_header_logo_exists() -> None:
    src = _make_docx_with_body_logo()
    out_bytes, _summary = rebrand_sds(src, "08/07/2026", brand="sampson")

    assert _embedded_media_digest(out_bytes) == _asset_digest(
        Path(r"E:\claude\ccs-compliant-cleaning-platform\api\assets\other-replacement.jpg")
    )
