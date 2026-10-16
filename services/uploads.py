import csv
import io
import zipfile
from xml.etree import ElementTree


REVIEW_COLUMNS = {
    "body",
    "comment",
    "comments",
    "content",
    "customer feedback",
    "customer review",
    "customer_review",
    "description",
    "feedback",
    "message",
    "review",
    "review body",
    "review title",
    "review text",
    "review_body",
    "review_title",
    "review_text",
    "reviewtext",
    "reviews",
    "text",
}
MAX_DOCX_XML_BYTES = 5_000_000
MAX_UPLOAD_BYTES = 1_000_000
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class UploadError(ValueError):
    pass


def _read_text(data, max_length):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadError("Text and CSV files must use UTF-8 encoding.") from None
    if len(text) > max_length:
        raise UploadError(f"The uploaded text is too long. Keep it under {max_length:,} characters.")
    return text.strip()


def _read_csv(data, max_length):
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadError("Text and CSV files must use UTF-8 encoding.") from None
    try:
        dialect = csv.Sniffer().sniff(decoded[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(decoded), dialect))
    if not rows:
        return ""

    header = [cell.strip().casefold() for cell in rows[0]]
    review_indexes = [
        index for index, name in enumerate(header) if name in REVIEW_COLUMNS
    ]
    content_rows = rows[1:] if review_indexes else rows
    extracted_rows = []
    for row in content_rows:
        cells = (
            [row[index] for index in review_indexes if index < len(row)]
            if review_indexes
            else row
        )
        line = " ".join(cell.strip() for cell in cells if cell.strip())
        if line:
            extracted_rows.append(line)
    text = "\n".join(extracted_rows)
    if len(text) > max_length:
        raise UploadError(f"The uploaded text is too long. Keep it under {max_length:,} characters.")
    return text


def _read_docx(data, max_length):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as document:
            try:
                document_xml = document.getinfo("word/document.xml")
            except KeyError:
                raise UploadError("That file is not a valid Word document (.docx).") from None
            if document_xml.file_size > MAX_DOCX_XML_BYTES:
                raise UploadError("The Word document is too large to process.")
            root = ElementTree.fromstring(document.read(document_xml))
    except (zipfile.BadZipFile, ElementTree.ParseError, RuntimeError):
        raise UploadError("That file is not a valid Word document (.docx).") from None
    paragraphs = []
    for paragraph in root.iter(f"{WORD_NAMESPACE}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_NAMESPACE}t" and node.text:
                parts.append(node.text)
            elif node.tag in {f"{WORD_NAMESPACE}tab", f"{WORD_NAMESPACE}br"}:
                parts.append(" ")
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    text = "\n".join(paragraphs)
    if len(text) > max_length:
        raise UploadError(f"The uploaded text is too long. Keep it under {max_length:,} characters.")
    return text


def extract_uploaded_text(filename, data, max_length=100_000):
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("That upload is too large. Please keep files under 1 MB.")
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if extension == "txt":
        return _read_text(data, max_length)
    if extension == "csv":
        return _read_csv(data, max_length)
    if extension == "docx":
        return _read_docx(data, max_length)
    raise UploadError("Upload a .txt, .csv, or .docx file.")
