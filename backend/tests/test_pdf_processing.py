import pymupdf
import pytest

from backend import pdf_processing
from backend.pdf_processing import MAX_UPLOAD_BYTES, PDFError, PREVIEW_CHARACTERS, extract_pdf


def test_extracts_original_page_numbers_including_blank_pages(make_pdf):
    result = extract_pdf(make_pdf(("First page research", "", "Third page conclusion")))
    assert result["page_count"] == 3
    assert result["pages"] == [
        {"page_number": 1, "text": "First page research"},
        {"page_number": 2, "text": ""},
        {"page_number": 3, "text": "Third page conclusion"},
    ]
    assert result["character_count"] == len("First page researchThird page conclusion")
    assert "Page 1\nFirst page research" in result["preview"]
    assert "Page 3\nThird page conclusion" in result["preview"]


@pytest.mark.parametrize("data,status", [(b"", 400), (b"not a PDF", 415),
    (b"%PDF-1.7\ncorrupted\n%%EOF", 422), (b"%PDF-1.7\ntruncated", 422)])
def test_invalid_content_is_rejected_safely(data, status):
    with pytest.raises(PDFError) as caught:
        extract_pdf(data)
    assert caught.value.status_code == status
    assert "Traceback" not in str(caught.value)


def test_blank_pdf_explains_ocr_limitation(make_pdf):
    with pytest.raises(PDFError, match="OCR"):
        extract_pdf(make_pdf(("",)))


def test_image_only_pdf_explains_ocr_limitation():
    with pymupdf.open() as document:
        page = document.new_page()
        image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
        image.clear_with(255)
        page.insert_image(pymupdf.Rect(72, 72, 200, 200), pixmap=image)
        data = document.tobytes()
    with pytest.raises(PDFError, match="selectable text"):
        extract_pdf(data)


def test_encrypted_pdf_explains_password_requirement(make_pdf):
    with pytest.raises(PDFError, match="password-protected"):
        extract_pdf(make_pdf(password="secret"))


def test_actual_20_mib_limit_is_enforced():
    with pytest.raises(PDFError) as caught:
        extract_pdf(b"x" * (MAX_UPLOAD_BYTES + 1))
    assert caught.value.status_code == 413


def test_truncated_real_pdf_is_rejected(make_pdf):
    data = make_pdf()
    with pytest.raises(PDFError, match="corrupted"):
        extract_pdf(data[:data.rfind(b"%%EOF")])


def test_parser_repaired_document_is_rejected(make_pdf):
    # Corrupt the xref pointer while leaving a plausible signature and EOF.
    import re
    data = re.sub(rb"startxref\s+\d+", b"startxref\n1", make_pdf())
    with pytest.raises(PDFError, match="damaged"):
        extract_pdf(data)


def test_page_extraction_failure_logs_page_and_type_without_exception_text(make_pdf, monkeypatch, caplog):
    opened_documents = []

    def fail(page, *args, **kwargs):
        opened_documents.append(page.parent)
        raise RuntimeError("private parser data")

    data = make_pdf()
    monkeypatch.setattr(pymupdf.Page, "get_text", fail)
    with pytest.raises(PDFError, match="could not be read") as caught:
        extract_pdf(data)
    assert "page=1, error_type=RuntimeError" in caplog.text
    assert "private parser data" not in caplog.text + str(caught.value)
    assert opened_documents[0].is_closed


def test_page_limit_bounds_memory(make_pdf, monkeypatch):
    monkeypatch.setattr(pdf_processing, "MAX_PAGES", 1)
    with pytest.raises(PDFError) as caught:
        extract_pdf(make_pdf(("One", "Two")))
    assert caught.value.status_code == 413


def test_character_limit_bounds_memory(make_pdf, monkeypatch):
    monkeypatch.setattr(pdf_processing, "MAX_TEXT_CHARACTERS", 5)
    with pytest.raises(PDFError) as caught:
        extract_pdf(make_pdf())
    assert caught.value.status_code == 413


def test_preview_is_bounded_but_stored_pages_are_complete(make_pdf):
    data = make_pdf(tuple(f"Page {number}: " + "research " * 12 for number in range(30)))
    result = extract_pdf(data)
    assert len(result["preview"]) <= PREVIEW_CHARACTERS
    assert len(result["pages"]) == 30
    assert result["character_count"] == sum(len(page["text"]) for page in result["pages"])
