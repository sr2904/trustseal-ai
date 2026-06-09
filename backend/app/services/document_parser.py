from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from html import unescape
from pathlib import Path
from xml.etree import ElementTree as ET

from fastapi import UploadFile

from app.models import ParsedDocument
from app.services.image_features import ImageFeatureExtractor
from app.services.ocr_service import OCRService


class DocumentParser:
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    TEXT_EXTENSIONS = {".txt", ".text", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".docx"}
    PDF_EXTENSIONS = {".pdf"}

    def __init__(self, ocr_service: OCRService, image_feature_extractor: ImageFeatureExtractor) -> None:
        self._ocr_service = ocr_service
        self._image_feature_extractor = image_feature_extractor

    async def parse_upload(self, file: UploadFile) -> ParsedDocument:
        file_bytes = await file.read()
        suffix = Path(file.filename or "").suffix.lower()
        content_type = (file.content_type or "").lower()

        if self._is_image(suffix, content_type):
            image = self._image_feature_extractor.load_image_bytes(file_bytes)
            return self._ocr_service.run(image)

        text = self._extract_text(file_bytes, suffix, content_type)
        if not text.strip():
            raise ValueError(
                f"No readable text could be extracted from '{file.filename or 'uploaded file'}'. "
                "Try a clearer file or convert it to a text-based PDF, image, or plain text file."
            )
        return self._ocr_service.parse_text_document(text)

    def _is_image(self, suffix: str, content_type: str) -> bool:
        return content_type.startswith("image/") or suffix in self.IMAGE_EXTENSIONS

    def _extract_text(self, file_bytes: bytes, suffix: str, content_type: str) -> str:
        if suffix in self.PDF_EXTENSIONS or content_type == "application/pdf":
            return self._extract_pdf_text(file_bytes)
        if suffix == ".json" or content_type == "application/json":
            return self._extract_json_text(file_bytes)
        if suffix == ".csv" or "csv" in content_type:
            return self._extract_csv_text(file_bytes)
        if suffix == ".docx" or content_type in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            return self._extract_docx_text(file_bytes)
        if suffix in {".html", ".htm", ".xml"} or content_type in {"text/html", "application/xml", "text/xml"}:
            return self._extract_markup_text(file_bytes)
        if suffix in self.TEXT_EXTENSIONS or content_type.startswith("text/"):
            return self._decode_text(file_bytes)
        raise ValueError(
            "Unsupported file type for comparison. Use an image, PDF, TXT, JSON, CSV, HTML, XML, or DOCX file."
        )

    def _extract_pdf_text(self, file_bytes: bytes) -> str:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as exc:
            raise ValueError(
                "PDF comparison support requires the 'pypdf' package. Run 'pip install -r backend/requirements.txt' after updating dependencies."
            ) from exc

        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            parts = [(page.extract_text() or "").strip() for page in reader.pages]
        except Exception as exc:
            raise ValueError("Unable to read PDF text. Use a text-based PDF or export it as an image.") from exc
        return "\n".join(part for part in parts if part)

    def _extract_json_text(self, file_bytes: bytes) -> str:
        try:
            payload = json.loads(self._decode_text(file_bytes))
        except json.JSONDecodeError as exc:
            raise ValueError("Uploaded JSON file is not valid JSON.") from exc

        lines: list[str] = []

        def walk(value: object, prefix: str = "") -> None:
            if isinstance(value, dict):
                for key, inner in value.items():
                    next_prefix = f"{prefix}{key}".strip()
                    walk(inner, f"{next_prefix}: ")
            elif isinstance(value, list):
                for item in value:
                    walk(item, prefix)
            elif value is not None:
                lines.append(f"{prefix}{value}".strip())

        walk(payload)
        return "\n".join(lines)

    def _extract_csv_text(self, file_bytes: bytes) -> str:
        decoded = self._decode_text(file_bytes)
        reader = csv.reader(io.StringIO(decoded))
        rows = []
        for row in reader:
            cleaned = [cell.strip() for cell in row if cell and cell.strip()]
            if cleaned:
                rows.append(" ".join(cleaned))
        return "\n".join(rows)

    def _extract_docx_text(self, file_bytes: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                xml_bytes = archive.read("word/document.xml")
        except Exception as exc:
            raise ValueError("Unable to read DOCX contents. Make sure the file is a valid .docx document.") from exc

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ValueError("DOCX text XML could not be parsed.") from exc

        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[str] = []
        for paragraph in root.findall(".//w:p", namespace):
            chunks = [node.text for node in paragraph.findall(".//w:t", namespace) if node.text]
            joined = "".join(chunks).strip()
            if joined:
                paragraphs.append(joined)
        return "\n".join(paragraphs)

    def _extract_markup_text(self, file_bytes: bytes) -> str:
        text = self._decode_text(file_bytes)
        without_tags = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", unescape(without_tags)).strip()

    def _decode_text(self, file_bytes: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("Unable to decode text from the uploaded file.")
