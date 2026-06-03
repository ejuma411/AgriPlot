import re
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys

logger = logging.getLogger(__name__)


class OCRUnavailable(Exception):
    pass


class DocumentOCRService:
    @staticmethod
    def _ensure_local_site_packages():
        """Allow the bundled virtualenv site-packages to be imported even if Django runs on system Python."""
        project_root = Path(__file__).resolve().parents[2]
        candidate_paths = [
            project_root / "env" / "lib" / "python3.13" / "site-packages",
            project_root / "env" / "lib64" / "python3.13" / "site-packages",
        ]
        for candidate in candidate_paths:
            if candidate.exists():
                candidate_str = str(candidate)
                if candidate_str not in sys.path:
                    sys.path.insert(0, candidate_str)

    @staticmethod
    def _load_ocr():
        try:
            DocumentOCRService._ensure_local_site_packages()
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
    def health_status():
        """Return a non-throwing readiness snapshot for OCR dependencies."""
        status = {
            "ready": False,
            "pytesseract_available": False,
            "tesseract_available": False,
            "pdftoppm_available": False,
            "tesseract_version": None,
            "error": None,
        }

        try:
            pytesseract = DocumentOCRService._load_ocr()
            status["pytesseract_available"] = True

            try:
                status["tesseract_version"] = str(pytesseract.get_tesseract_version())
                status["tesseract_available"] = True
            except Exception as exc:
                status["error"] = "tesseract is not installed or not in PATH"
                status["error_detail"] = str(exc)

            status["pdftoppm_available"] = bool(shutil.which("pdftoppm"))
            if not status["pdftoppm_available"] and not status["error"]:
                status["error"] = "pdftoppm is not installed or not in PATH"

            status["ready"] = (
                status["pytesseract_available"]
                and status["tesseract_available"]
                and status["pdftoppm_available"]
            )
        except Exception as exc:
            status["error"] = str(exc)

        return status

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
                pdftoppm = shutil.which("pdftoppm")
                if not pdftoppm:
                    raise OCRUnavailable("pdftoppm is not installed or not in PATH")

                with tempfile.TemporaryDirectory() as tmpdir:
                    prefix = os.path.join(tmpdir, "ocr_page")
                    subprocess.run(
                        [pdftoppm, "-png", "-r", "200", str(path), prefix],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    image_paths = sorted(Path(tmpdir).glob("ocr_page-*.png"))
                    if not image_paths:
                        raise OCRUnavailable("Failed to render PDF pages with pdftoppm")

                    text_chunks = []
                    for image_path in image_paths:
                        page = Image.open(image_path)
                        text_chunks.append(pytesseract.image_to_string(page))
                    return "\n".join(text_chunks).strip()
            except OCRUnavailable:
                raise
            except Exception as exc:
                raise OCRUnavailable("Failed to render PDF for OCR") from exc

        img = Image.open(path)
        text = pytesseract.image_to_string(img)
        return text or ""

    @staticmethod
    def extract_fields(text):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        joined = "\n".join(lines)

        def is_label_like(value, labels):
            value_lower = value.lower()
            value_norm = re.sub(r"[^a-z0-9]+", "", value_lower)
            generic_headings = {"owner", "parcel", "title"}
            if value_norm in {re.sub(r"[^a-z0-9]+", "", label.lower()) for label in labels}:
                return True
            if value_lower in {"owner", "parcel", "title", "kra pin", "number", "ref", "no", "name"}:
                return True
            if value_lower.startswith("registered owner") or value_lower.startswith("registered proprietor"):
                return True
            if value_lower.startswith("search reference"):
                return True
            if value_lower.startswith("id number") or value_lower.startswith("national id"):
                return True
            if value_lower.startswith("parcel number") or value_lower.startswith("parcel no") or value_lower.startswith("lr no"):
                return True
            if value_lower.startswith("title number"):
                return True
            if value_norm in generic_headings:
                return True
            return False

        def find_by_label(labels, allow_following_lines=True):
            for idx, ln in enumerate(lines):
                line_lower = ln.lower()
                for label in labels:
                    label_lower = label.lower()
                    if label_lower and (line_lower == label_lower or line_lower.startswith(label_lower)):
                        parts = ln.split(":", 1)
                        if len(parts) == 2 and parts[1].strip():
                            return parts[1].strip()

                        tail = ln[len(label):].strip(" :-")
                        if tail:
                            return tail

                        if allow_following_lines:
                            for next_line in lines[idx + 1 :]:
                                if next_line and not is_label_like(next_line, labels):
                                    return next_line
            return ""

        fields = {
            "owner_name": find_by_label([
                "Full Name",
                "Registered Owner",
                "Registered Owner Name",
                "Registered Proprietor",
                "Taxpayer Name",
                "Owner Name",
            ]),
            "id_number": find_by_label(["ID Number", "National ID", "ID No"]),
            "kra_pin": find_by_label(["KRA PIN", "PIN"], allow_following_lines=False),
            "title_number": find_by_label(["Title Number"]),
            "parcel_number": find_by_label([
                "Parcel Number",
                "Parcel No",
                "Parcel",
                "LR No",
                "Title Deed / Parcel Reference",
            ]),
            "search_ref": find_by_label([
                "Search Reference",
                "Search Reference Number",
                "Search Ref",
                "Search No",
            ]),
        }

        id_match = re.search(r"\b\d{7,9}\b", joined)
        if id_match and not fields["id_number"]:
            fields["id_number"] = id_match.group(0)

        kra_match = re.search(r"\b[A-Z]\d{9}[A-Z]\b", joined)
        if kra_match and not fields["kra_pin"]:
            fields["kra_pin"] = kra_match.group(0)

        parcel_match = re.search(r"\b[A-Z]+/[A-Z]+/\d+\b", joined)
        if parcel_match and not fields["parcel_number"]:
            fields["parcel_number"] = parcel_match.group(0)

        search_match = re.search(r"\bSR[O0]?\d{3,}\b", joined)
        if search_match and not fields["search_ref"]:
            fields["search_ref"] = search_match.group(0)

        if fields["search_ref"]:
            fields["search_ref"] = fields["search_ref"].replace("SRO", "SR0").replace("SR O", "SR0")

        if not fields["title_number"] and fields["parcel_number"]:
            fields["title_number"] = fields["parcel_number"]

        return fields
