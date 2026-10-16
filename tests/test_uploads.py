import io
import zipfile

import pytest

from services.uploads import UploadError, extract_uploaded_text


def test_csv_uses_review_text_column_and_skips_other_fields():
    content = (
        b"review,rating\n"
        b'"The battery is excellent but the price is too high. I recommend this product.",5\n'
    )

    assert extract_uploaded_text("reviews.csv", content) == (
        "The battery is excellent but the price is too high. I recommend this product."
    )


def test_csv_without_review_header_keeps_all_nonempty_cells():
    content = b"Battery is excellent, but the price is too high.\n"

    assert extract_uploaded_text("reviews.csv", content) == (
        "Battery is excellent but the price is too high."
    )


def test_text_file_accepts_utf8_bom():
    assert extract_uploaded_text("reviews.txt", b"\xef\xbb\xbfA helpful review.") == (
        "A helpful review."
    )


def test_docx_extracts_paragraphs_and_line_breaks():
    document_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>The battery is excellent.</w:t></w:r></w:p>
      <w:p><w:r><w:t>The price is too high.</w:t></w:r></w:p></w:body>
    </w:document>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as document:
        document.writestr("word/document.xml", document_xml)

    assert extract_uploaded_text("reviews.docx", output.getvalue()) == (
        "The battery is excellent.\nThe price is too high."
    )


@pytest.mark.parametrize(
    ("filename", "data", "message"),
    [
        ("reviews.doc", b"legacy Word document", r"\.txt, \.csv, or \.docx"),
        ("reviews.txt", b"\xff", "UTF-8"),
        ("reviews.docx", b"not a zip", "valid Word document"),
    ],
)
def test_unsupported_or_invalid_files_report_clear_errors(filename, data, message):
    with pytest.raises(UploadError, match=message):
        extract_uploaded_text(filename, data)


def test_upload_rejects_extracted_content_over_character_limit():
    with pytest.raises(UploadError, match="too long"):
        extract_uploaded_text("reviews.txt", b"long enough", max_length=5)
