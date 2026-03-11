import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class OCRUnavailable(Exception):
    pass


class DocumentOCRService:
    @staticmethod
    def _load_ocr():
        try:
            import pytesseract  # noqa: F401
        except Exception as exc:
            raise OCRUnavailable("pytesseract not installed") from exc
        return pytesseract

    @staticmethod
    def _check_tesseract(pytesseract):
        try:
            _ = pytesseract.get_tesseract_version()
        except Exception as exc:
            raise OCRUnavailable("tesseract is not installed or not in PATH") from exc

    @staticmethod
    def extract_text(file_field):
        if not file_field:
            return ""

        path = Path(file_field.path)
        ext = path.suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".pdf"}:
            raise OCRUnavailable("Unsupported file type for OCR. Use PNG/JPG/PDF.")

        pytesseract = DocumentOCRService._load_ocr()
        DocumentOCRService._check_tesseract(pytesseract)

        from PIL import Image
        if ext == ".pdf":
            try:
                from pdf2image import convert_from_path
            except Exception as exc:
                raise OCRUnavailable("pdf2image not installed. Install pdf2image and poppler-utils for PDF OCR.") from exc

            try:
                pages = convert_from_path(str(path), dpi=200)
            except Exception as exc:
                raise OCRUnavailable("Failed to render PDF. Ensure poppler-utils is installed.") from exc

            text_chunks = []
            for page in pages:
                text_chunks.append(pytesseract.image_to_string(page))
            return "\n".join(text_chunks).strip()

        img = Image.open(path)
        text = pytesseract.image_to_string(img)
        return text or ""

    @staticmethod
    def extract_fields(text):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        joined = "\n".join(lines)

        def find_by_label(labels):
            for ln in lines:
                for label in labels:
                    if label.lower() in ln.lower():
                        parts = ln.split(":", 1)
                        if len(parts) == 2:
                            return parts[1].strip()
            return ""

        fields = {
            "owner_name": find_by_label(["Full Name", "Registered Owner", "Taxpayer Name", "Owner Name"]),
            "id_number": find_by_label(["ID Number", "National ID", "ID No"]),
            "kra_pin": find_by_label(["KRA PIN", "PIN"]),
            "title_number": find_by_label(["Title Number"]),
            "parcel_number": find_by_label(["Parcel Number", "Parcel No", "LR No"]),
            "search_ref": find_by_label(["Search Reference", "Search Ref", "Search No"]),
        }

        id_match = re.search(r"\b\d{7,9}\b", joined)
        if id_match and not fields["id_number"]:
            fields["id_number"] = id_match.group(0)

        kra_match = re.search(r"\b[A-Z]\d{9}[A-Z]\b", joined)
        if kra_match and not fields["kra_pin"]:
            fields["kra_pin"] = kra_match.group(0)

        title_match = re.search(r"\b[A-Z0-9]+/\d+/\d{2,4}\b", joined)
        if title_match and not fields["title_number"]:
            fields["title_number"] = title_match.group(0)

        parcel_match = re.search(r"\b[A-Z]+/[A-Z]+/\d+\b", joined)
        if parcel_match and not fields["parcel_number"]:
            fields["parcel_number"] = parcel_match.group(0)

        search_match = re.search(r"\bSR[O0]?\d{3,}\b", joined)
        if search_match and not fields["search_ref"]:
            fields["search_ref"] = search_match.group(0)

        if fields["search_ref"]:
            fields["search_ref"] = fields["search_ref"].replace("SRO", "SR0").replace("SR O", "SR0")

        return fields
