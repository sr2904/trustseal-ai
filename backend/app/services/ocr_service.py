from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings
from app.models import OCRField, ParsedDocument


@dataclass
class OCRLine:
    text: str
    confidence: float


class OCRService:
    REQUIRED_FIELDS = [
        "first_name",
        "last_name",
        "dob",
        "id_number",
        "expiration",
        "address",
        "license_class",
        "issuing_state",
    ]

    STATE_NAME_TO_CODE = {
        "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
        "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
        "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
        "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
        "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
        "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
        "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC",
        "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
        "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
        "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
        "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    }
    ID_KEYWORDS = {"DRIVER LICENSE", "DRIVER'S LICENSE", "LICENSE", "DOB", "EXP", "DLN", "CLASS"}
    NAME_LABELS = {
        "first_name": ["FIRST NAME", "GIVEN NAME"],
        "last_name": ["LAST NAME", "SURNAME", "FAMILY NAME"],
        "full_name": ["BORROWER NAME", "APPLICANT NAME", "CUSTOMER NAME", "SIGNER NAME", "OWNER NAME", "NAME"],
    }
    ADDRESS_LABELS = ["PROPERTY ADDRESS", "RESIDENCE ADDRESS", "MAILING ADDRESS", "SERVICE ADDRESS", "ADDRESS"]

    def __init__(self) -> None:
        self._reader = None
        self._provider = "regex_only"
        self._provider_initialized = False
        self._provider_error: str | None = None

    def _init_provider(self) -> None:
        if self._provider_initialized:
            return
        self._provider_initialized = True

        if settings.enable_easyocr:
            try:
                import easyocr  # type: ignore
                self._reader = easyocr.Reader(["en", "ko"], gpu=False)
                self._provider = "easyocr"
                self._provider_error = None
                return
            except Exception as exc:
                self._provider_error = (
                    "Image OCR could not start. EasyOCR may still need its model files, "
                    "or local SSL/model-download setup may be incomplete. "
                    f"Underlying error: {exc}"
                )

        if settings.enable_paddleocr:
            try:
                from paddleocr import PaddleOCR  # type: ignore
                self._reader = PaddleOCR(use_angle_cls=True, lang="korean")
                self._provider = "paddleocr"
                self._provider_error = None
                return
            except Exception as exc:
                if not self._provider_error:
                    self._provider_error = (
                        "Image OCR could not start. PaddleOCR is unavailable in the current environment. "
                        f"Underlying error: {exc}"
                    )

    @property
    def provider(self) -> str:
        if not self._provider_initialized:
            self._init_provider()
        return self._provider

    def run(self, image: np.ndarray) -> ParsedDocument:
        lines = self._read_text(image)
        text_lines = [self._clean_spaces(line.text) for line in lines if line.text.strip()]
        raw_text = "\n".join(text_lines)
        fields = self._extract_structured_fields(raw_text, text_lines)
        self._recover_missing_fields_from_image(image, fields)
        return ParsedDocument(raw_text=raw_text, fields=fields, text_lines=text_lines)

    def parse_text_document(self, text: str) -> ParsedDocument:
        text_lines = self._segment_text_document_lines(text)
        raw_text = "\n".join(text_lines)
        fields = self._extract_structured_fields(raw_text, text_lines)
        return ParsedDocument(raw_text=raw_text, fields=fields, text_lines=text_lines)

    def _segment_text_document_lines(self, text: str) -> list[str]:
        normalized = text.replace("\r", "\n")
        raw_lines = [self._clean_spaces(line) for line in normalized.splitlines() if line.strip()]
        if len(raw_lines) > 1:
            return raw_lines

        collapsed = self._clean_spaces(text)
        if not collapsed:
            return []

        split_patterns = [
            "UNIFORM RESIDENTIAL LOAN APPLICATION",
            "BORROWER NAME:",
            "DATE OF BIRTH:",
            "DOB:",
            "PROPERTY ADDRESS:",
            "RESIDENCE ADDRESS:",
            "MAILING ADDRESS:",
            "ID NUMBER:",
            "EXPIRATION DATE:",
            "ACCOUNT NUMBER:",
        ]

        segmented = collapsed
        for pattern in split_patterns:
            segmented = re.sub(rf"\s*({re.escape(pattern)})\s*", rf"\n\1 ", segmented, flags=re.IGNORECASE)

        lines = [self._clean_spaces(line) for line in segmented.splitlines() if line.strip()]
        return lines or [collapsed]

    def _read_text(self, image: np.ndarray) -> list[OCRLine]:
        if not self._provider_initialized:
            self._init_provider()

        if self._provider == "easyocr" and self._reader is not None:
            result = self._reader.readtext(image)
            return [OCRLine(text=item[1], confidence=float(item[2])) for item in result]

        if self._provider == "paddleocr" and self._reader is not None:
            result = self._reader.ocr(image, cls=True)
            lines: list[OCRLine] = []
            for block in result or []:
                for item in block:
                    text = item[1][0]
                    conf = float(item[1][1])
                    lines.append(OCRLine(text=text, confidence=conf))
            return lines

        _ = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        raise ValueError(
            self._provider_error
            or "Image OCR is not configured. Enable and initialize an OCR provider before analyzing images."
        )

    def _extract_structured_fields(self, raw_text: str, text_lines: list[str]) -> dict[str, OCRField]:
        normalized = raw_text.replace("\u200b", " ")
        is_korean_doc = bool(re.search(r"[가-힣]", normalized))
        if is_korean_doc:
            parsed = self._extract_korean_id(normalized, text_lines)
        elif self._looks_like_identity_document(normalized):
            parsed = self._extract_us_like_id(normalized, text_lines)
        else:
            parsed = self._extract_generic_text_fields(normalized, text_lines)

        fields: dict[str, OCRField] = {}
        for key in self.REQUIRED_FIELDS:
            value = parsed.get(key)
            confidence = 0.0
            if value:
                confidence = 0.88
                if key in {"address", "license_class", "issuing_state"}:
                    confidence = 0.8
            fields[key] = OCRField(value=value, confidence=confidence, source="ocr_parser")
        return fields

    def _looks_like_identity_document(self, text: str) -> bool:
        upper = text.upper()
        return sum(1 for token in self.ID_KEYWORDS if token in upper) >= 2

    def _extract_generic_text_fields(self, text: str, lines: list[str]) -> dict[str, str | None]:
        upper_lines = [self._to_upper_ascii(line) for line in lines]
        full_upper = "\n".join(upper_lines)

        first_name = self._extract_labeled_value(upper_lines, self.NAME_LABELS["first_name"])
        last_name = self._extract_labeled_value(upper_lines, self.NAME_LABELS["last_name"])

        if not (first_name and last_name):
            full_name = self._extract_labeled_value(upper_lines, self.NAME_LABELS["full_name"])
            parsed_first, parsed_last = self._split_generic_full_name(full_name)
            first_name = first_name or parsed_first
            last_name = last_name or parsed_last

        dob = self._extract_labeled_date(
            upper_lines,
            ["DATE OF BIRTH", "DOB", "BIRTH DATE"],
        )
        expiration = self._extract_labeled_date(
            upper_lines,
            ["EXPIRATION DATE", "EXPIRATION", "EXPIRES", "EXP"],
        )
        id_number = self._extract_labeled_value(
            upper_lines,
            ["ID NUMBER", "ID NO", "LICENSE NUMBER", "LICENSE NO", "DLN"],
        )
        address = self._extract_labeled_address(upper_lines)
        issuing_state = self._find_state(full_upper) if address else None

        return {
            "first_name": first_name,
            "last_name": last_name,
            "dob": dob,
            "id_number": id_number,
            "expiration": expiration,
            "address": address,
            "license_class": None,
            "issuing_state": issuing_state,
        }

    def _extract_us_like_id(self, text: str, lines: list[str]) -> dict[str, str | None]:
        upper_lines = [self._to_upper_ascii(line) for line in lines]
        full_upper = "\n".join(upper_lines)

        id_number = None
        expiration = None
        dob = None
        issuing_state = self._find_state(full_upper)
        first_name = None
        last_name = None
        address = None
        license_class = None

        for idx, line in enumerate(upper_lines):
            compact = re.sub(r"\s+", " ", line).strip()

            if not id_number:
                m = re.search(r"\b(?:4D\s*DLN|DLN|DL|LIC(?:ENSE)?\s*NO\.?|ID\s*NO\.?)\s*([A-Z]\d{7,12}|[A-Z0-9-]{6,20})\b", compact)
                if m:
                    id_number = m.group(1)

            if not expiration:
                m = re.search(r"\b(?:4B\s*)?EXP\b\s*([0-9./-]{6,12})", compact)
                if m:
                    expiration = self._normalize_date(m.group(1))

            if not dob:
                m = re.search(r"\b(?:3\s*)?DOB\b\s*([0-9./-]{6,12})", compact)
                if m:
                    dob = self._normalize_date(m.group(1))

            if not license_class:
                candidate = self._extract_license_class_from_context(upper_lines, idx)
                if candidate:
                    license_class = candidate

            # Explicit line labels
            if not last_name:
                m = re.search(r"(?:^|\b)1[\s:.-]+([A-Z][A-Z'\-]{1,30})(?:\b|$)", compact)
                if m and self._is_viable_name_token(m.group(1)):
                    last_name = m.group(1)
            if not first_name:
                m = re.search(r"(?:^|\b)2[\s:.-]+([A-Z][A-Z'\-]{1,30})(?:\b|$)", compact)
                if m and self._is_viable_name_token(m.group(1)):
                    first_name = m.group(1)

            # Same-line merge: "1 SAMPLE 2 DRIVER"
            if not (first_name and last_name):
                m = re.search(r"\b1[\s:.-]+([A-Z][A-Z'\-]{1,30})\b.*?\b2[\s:.-]+([A-Z][A-Z'\-]{1,30})\b", compact)
                if m:
                    if self._is_viable_name_token(m.group(1)):
                        last_name = last_name or m.group(1)
                    if self._is_viable_name_token(m.group(2)):
                        first_name = first_name or m.group(2)

        if not (first_name and last_name):
            explicit_last, explicit_first = self._extract_numbered_name_fields(upper_lines)
            last_name = last_name or explicit_last
            first_name = first_name or explicit_first

        if not (first_name and last_name):
            inferred_last, inferred_first = self._infer_name_from_region(upper_lines)
            last_name = last_name or inferred_last
            first_name = first_name or inferred_first

        if not (first_name and last_name):
            standalone_last, standalone_first = self._infer_name_from_standalone_lines(upper_lines)
            last_name = last_name or standalone_last
            first_name = first_name or standalone_first

        if not (first_name and last_name):
            sig_first, sig_last = self._infer_name_from_signature(upper_lines)
            if sig_first and sig_last:
                first_name = first_name or sig_first
                last_name = last_name or sig_last

        if not id_number:
            id_number = self._find_id_number(full_upper)
        if not expiration:
            expiration = self._find_likely_expiration(full_upper)
        if not dob:
            dob = self._find_likely_birth_date(full_upper)
        if not license_class:
            license_class = self._find_license_class(full_upper)

        address = self._find_address(upper_lines)

        return {
            "first_name": first_name,
            "last_name": last_name,
            "dob": dob,
            "id_number": id_number,
            "expiration": expiration,
            "address": address,
            "license_class": license_class,
            "issuing_state": issuing_state,
        }

    def _infer_name_from_region(self, upper_lines: list[str]) -> tuple[str | None, str | None]:
        stop = self._name_stopwords()
        candidates: list[str] = []

        # Focus on the center portion of the license where the labeled names usually live.
        start_anchor = 0
        end_anchor = len(upper_lines)

        for idx, line in enumerate(upper_lines):
            if any(token in line for token in ["ISS", "DOB", "EXP"]):
                start_anchor = max(0, idx - 1)
                break

        for idx, line in enumerate(upper_lines):
            if any(token in line for token in ["CLASS", "SEX", "HGT", "EYES", "WGT", "ENDORSEMENTS", "RESTRICTIONS"]):
                end_anchor = idx
                break

        for line in upper_lines[start_anchor:end_anchor]:
            compact = re.sub(r"\s+", " ", line).strip()
            compact = re.sub(r"^[12]\s+", "", compact)

            if any(token in compact for token in ["DOB", "EXP", "ISS", "CLASS", "SEX", "HGT", "EYES", "WGT", "ENDORSEMENTS", "RESTRICTIONS", "ARIZONA", "LICENSE"]):
                continue
            if re.search(r"\d", compact):
                continue
            if not self._looks_like_person_name(compact):
                continue
            if compact in stop or not self._is_viable_name_token(compact):
                continue
            candidates.append(compact)

        deduped: list[str] = []
        for item in candidates:
            if item not in deduped:
                deduped.append(item)

        if len(deduped) >= 2:
            return deduped[0], deduped[1]
        return None, None

    def _infer_name_from_signature(self, upper_lines: list[str]) -> tuple[str | None, str | None]:
        stop = self._name_stopwords()
        for line in upper_lines:
            compact = re.sub(r"\s+", " ", line).strip()
            if any(token in compact for token in ["LICENSE", "ARIZONA", "DOB", "EXP", "ISS", "CLASS", "ENDORSEMENTS", "RESTRICTIONS"]):
                continue
            if re.search(r"\d", compact):
                continue
            words = [w for w in compact.split() if self._looks_like_person_name(w) and self._is_viable_name_token(w) and w not in stop]
            if len(words) == 2:
                # Signature style is usually "first last"
                return words[0], words[1]
        return None, None

    def _infer_name_from_standalone_lines(self, upper_lines: list[str]) -> tuple[str | None, str | None]:
        address_idx = None
        for idx, line in enumerate(upper_lines):
            cleaned = re.sub(r"^(8\s+)", "", line).strip()
            if re.search(r"\b\d{1,6}\s+[A-Z0-9 .'-]+\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|DR|DRIVE|LN|LANE|WAY|CT|COURT)\b", cleaned):
                address_idx = idx
                break

        if address_idx is None:
            return None, None

        candidates: list[str] = []
        for idx in range(max(0, address_idx - 5), address_idx):
            compact = re.sub(r"\s+", " ", upper_lines[idx]).strip()
            if self._is_viable_name_token(compact):
                candidates.append(compact)

        deduped: list[str] = []
        for item in candidates:
            if item not in deduped:
                deduped.append(item)

        if len(deduped) >= 2:
            return deduped[-2], deduped[-1]
        return None, None

    def _extract_numbered_name_fields(self, upper_lines: list[str]) -> tuple[str | None, str | None]:
        last_name = None
        first_name = None

        for idx, line in enumerate(upper_lines):
            compact = re.sub(r"\s+", " ", line).strip()

            if last_name is None and re.fullmatch(r"1", compact) and idx + 1 < len(upper_lines):
                candidate = re.sub(r"\s+", " ", upper_lines[idx + 1]).strip()
                if self._is_viable_name_token(candidate):
                    last_name = candidate
            if first_name is None and re.fullmatch(r"2", compact) and idx + 1 < len(upper_lines):
                candidate = re.sub(r"\s+", " ", upper_lines[idx + 1]).strip()
                if self._is_viable_name_token(candidate):
                    first_name = candidate

            if last_name is None:
                m = re.search(r"(?:^|\b)1[\s:.-]+([A-Z][A-Z'\-]{1,30})(?:\b|$)", compact)
                if m and self._is_viable_name_token(m.group(1)):
                    last_name = m.group(1)
            if first_name is None:
                m = re.search(r"(?:^|\b)2[\s:.-]+([A-Z][A-Z'\-]{1,30})(?:\b|$)", compact)
                if m and self._is_viable_name_token(m.group(1)):
                    first_name = m.group(1)

        return last_name, first_name

    def _extract_license_class_from_line(self, line: str) -> str | None:
        normalized = re.sub(r"\s+", " ", line).strip()

        # Best case: "9 CLASS D" or "CLASS D"
        m = re.search(r"\b(?:9\s+)?CLASS\s+([A-Z0-9]{1,2})\b", normalized)
        if m and self._is_valid_license_class(m.group(1)):
            return m.group(1)

        # OCR merge like "9 CLASS D 9A ENDORSEMENTS"
        m = re.search(r"\b9\s+CLASS\s+([A-Z0-9]{1,2})\b.*?(?:9A\s+ENDORSEMENTS|ENDORSEMENTS)", normalized)
        if m and self._is_valid_license_class(m.group(1)):
            return m.group(1)

        return None

    def _extract_license_class_from_context(self, lines: list[str], idx: int) -> str | None:
        current = re.sub(r"\s+", " ", lines[idx]).strip()
        # direct line match first
        direct = self._extract_license_class_from_line(current)
        if direct:
            return direct

        # If OCR split the field label and the value across nearby lines, inspect a small window.
        if "CLASS" not in current and not current.startswith("9"):
            return None

        window: list[str] = []
        for j in range(max(0, idx - 1), min(len(lines), idx + 3)):
            window.append(re.sub(r"\s+", " ", lines[j]).strip())
        joined = " | ".join(window)

        # Strong preference for single-character US classes.
        for pattern in [
            r"\bCLASS\s+([A-Z])\b",
            r"\b9\s+CLASS\s+([A-Z])\b",
            r"\b9\s+CLASS\b[^A-Z0-9]*([A-Z])\b",
        ]:
            m = re.search(pattern, joined)
            if m and self._is_valid_license_class(m.group(1)):
                return m.group(1)

        # Look for a standalone class value on adjacent lines near a CLASS label.
        if "CLASS" in joined:
            for token in re.findall(r"\b([A-Z0-9]{1,2})\b", joined):
                if self._is_valid_license_class(token) and token not in {"DL", "LN", "EXP", "DOB", "ISS", "AZ", "ST"}:
                    # avoid endorsement code 9A and field labels
                    if re.fullmatch(r"\d[A-Z]", token):
                        continue
                    return token
        return None

    def _is_valid_license_class(self, value: str) -> bool:
        value = (value or "").strip().upper()
        if value in {"", "NONE", "ENDORSEMENTS", "RESTRICTIONS", "CLASS"}:
            return False
        if re.fullmatch(r"\d[A-Z]", value):
            return False
        return bool(re.fullmatch(r"[A-Z0-9]{1,2}", value))

    def _name_stopwords(self) -> set[str]:
        return {
            "ARIZONA", "USA", "LICENSE", "DONOR", "VETERAN",
            "RESTRICTIONS", "ENDORSEMENTS", "CLASS", "SEX", "HGT", "EYES",
            "WGT", "PHOENIX", "UNDER", "UNTIL", "NONE", "DRIVERLICENSE",
            "DLN", "DOB", "EXP", "ISS", "AD",
        }

    def _is_viable_name_token(self, value: str) -> bool:
        token = (value or "").strip().upper()
        if len(token) < 3:
            return False
        return self._looks_like_person_name(token) and token not in self._name_stopwords()

    def _extract_korean_id(self, text: str, lines: list[str]) -> dict[str, str | None]:
        normalized_lines = [self._clean_spaces(line) for line in lines]

        id_number = None
        for line in normalized_lines:
            m = re.search(r"\b\d{2}-\d{2}-\d{6,8}-\d{2}\b", line)
            if m:
                id_number = m.group(0)
                break

        full_name = None
        for line in normalized_lines:
            if re.fullmatch(r"[가-힣]{2,5}", line):
                full_name = line
                break

        last_name = full_name[0] if full_name else None
        first_name = full_name[1:] if full_name and len(full_name) > 1 else None

        dob = None
        rrn_match = re.search(r"\b(\d{6})[- ]?[1-4]\d{6}\b", text)
        if rrn_match:
            dob = self._normalize_korean_short_date(rrn_match.group(1))

        all_dates = [self._normalize_date(v) for v in re.findall(r"\b20\d{2}[./-]\d{2}[./-]\d{2}\b", text)]
        expiration = max(all_dates) if all_dates else None

        address_parts: list[str] = []
        for line in normalized_lines:
            if any(token in line for token in ["경기도", "서울", "부산", "인천", "대구", "광주", "대전", "울산", "세종", "제주"]):
                address_parts.append(line)
            elif address_parts and re.search(r"[가-힣]", line) and not re.search(r"\d{4}[./-]\d{2}[./-]\d{2}", line):
                if len(line) <= 25:
                    address_parts.append(line)
        address = " ".join(dict.fromkeys(address_parts)) or None

        license_class = "1종보통" if re.search(r"1종보통", text) else None
        issuing_state = "KR"
        if address and "경기도" in address:
            issuing_state = "KR-GG"

        return {
            "first_name": first_name,
            "last_name": last_name,
            "dob": dob,
            "id_number": id_number,
            "expiration": expiration,
            "address": address,
            "license_class": license_class,
            "issuing_state": issuing_state,
        }

    def _extract_labeled_value(self, upper_lines: list[str], labels: list[str]) -> str | None:
        for idx, line in enumerate(upper_lines):
            compact = re.sub(r"\s+", " ", line).strip()
            for label in labels:
                if label not in compact:
                    continue
                candidate = compact.split(label, 1)[-1].strip(" :.-")
                if candidate:
                    return candidate
                if idx + 1 < len(upper_lines):
                    next_line = upper_lines[idx + 1].strip()
                    if next_line:
                        return next_line
        return None

    def _extract_labeled_date(self, upper_lines: list[str], labels: list[str]) -> str | None:
        value = self._extract_labeled_value(upper_lines, labels)
        if not value:
            return None
        match = re.search(r"([0-9]{1,4}[./-][0-9]{1,2}[./-][0-9]{2,4})", value)
        return self._normalize_date(match.group(1)) if match else None

    def _extract_labeled_address(self, upper_lines: list[str]) -> str | None:
        for idx, line in enumerate(upper_lines):
            compact = re.sub(r"\s+", " ", line).strip()
            for label in self.ADDRESS_LABELS:
                if label not in compact:
                    continue

                candidate = compact.split(label, 1)[-1].strip(" :.-")
                parts = [candidate] if candidate else []
                for offset in (1, 2):
                    if idx + offset < len(upper_lines):
                        next_line = upper_lines[idx + offset].strip()
                        if next_line:
                            parts.append(next_line)
                cleaned = [part for part in parts if part]
                if cleaned:
                    return ", ".join(cleaned[:2])
        return self._find_address(upper_lines)

    def _split_generic_full_name(self, value: str | None) -> tuple[str | None, str | None]:
        if not value:
            return None, None
        tokens = [
            token for token in re.findall(r"[A-Z][A-Z'\-]{1,30}", value.upper())
            if token not in {"BORROWER", "APPLICANT", "CUSTOMER", "SIGNER", "OWNER", "NAME"}
        ]
        if len(tokens) < 2:
            return None, None
        return tokens[0], tokens[-1]

    def _find_address(self, upper_lines: list[str]) -> str | None:
        for idx, line in enumerate(upper_lines):
            cleaned = re.sub(r"^(8\s+)", "", line).strip()
            cleaned = re.sub(r"^(?:ADDRESS|PROPERTY ADDRESS|RESIDENCE ADDRESS|MAILING ADDRESS)\s*[:.-]?\s*", "", cleaned).strip()
            if re.search(r"\b\d{1,6}\s+[A-Z0-9 .'-]+\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|DR|DRIVE|LN|LANE|WAY|CT|COURT)\b", cleaned):
                parts = [self._clean_spaces(cleaned)]
                if idx + 1 < len(upper_lines):
                    next_line = re.sub(r"^(8\s+)", "", upper_lines[idx + 1]).strip()
                    next_line = re.sub(r"^(?:ADDRESS|PROPERTY ADDRESS|RESIDENCE ADDRESS|MAILING ADDRESS)\s*[:.-]?\s*", "", next_line).strip()
                    next_line = re.sub(r"^[A-Z]\s+", "", next_line).strip()
                    if re.search(r"\b[A-Z .'-]+,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", next_line):
                        parts.append(self._clean_spaces(next_line))
                return ", ".join(parts)

        for idx, line in enumerate(upper_lines):
            normalized_line = re.sub(r"^(?:ADDRESS|PROPERTY ADDRESS|RESIDENCE ADDRESS|MAILING ADDRESS)\s*[:.-]?\s*", "", line).strip()
            if re.search(r"\b[A-Z .'-]+,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", normalized_line) and idx > 0:
                prev_line = re.sub(r"^(8\s+)", "", upper_lines[idx - 1]).strip()
                prev_line = re.sub(r"^(?:ADDRESS|PROPERTY ADDRESS|RESIDENCE ADDRESS|MAILING ADDRESS)\s*[:.-]?\s*", "", prev_line).strip()
                if re.search(r"\d{1,6}", prev_line):
                    return f"{self._clean_spaces(prev_line)}, {self._clean_spaces(normalized_line)}"

        return None

    def _find_license_class(self, text: str) -> str | None:
        for line in text.splitlines():
            candidate = self._extract_license_class_from_line(line)
            if candidate:
                return candidate
        m = re.search(r"\b(?:9\s+)?CLASS\s+([A-Z0-9]{1,2})\b", text)
        if m and self._is_valid_license_class(m.group(1)):
            return m.group(1)
        return None

    def _recover_missing_fields_from_image(self, image: np.ndarray, fields: dict[str, OCRField]) -> None:
        if self._provider != "easyocr" or self._reader is None:
            return

        if not fields["license_class"].value:
            recovered_class = self._recover_license_class_from_image(image)
            if recovered_class:
                fields["license_class"] = OCRField(value=recovered_class, confidence=0.7, source="ocr_image_fallback")

    def _recover_license_class_from_image(self, image: np.ndarray) -> str | None:
        h, w = image.shape[:2]
        crop = image[int(h * 0.55):int(h * 0.9), int(w * 0.35):int(w * 0.82)]
        if crop.size == 0:
            return None

        enlarged = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        try:
            result = self._reader.readtext(
                enlarged,
                detail=0,
                paragraph=False,
                allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            )
        except Exception:
            return None

        tokens = [self._to_upper_ascii(item) for item in result if str(item).strip()]
        for idx, token in enumerate(tokens):
            compact = token.replace(" ", "")
            if "CLASS" not in compact:
                continue

            direct = self._extract_license_class_from_line(token)
            if direct:
                return direct

            m = re.search(r"CLASS([A-Z])\b", compact)
            if m and self._is_valid_license_class(m.group(1)):
                return m.group(1)

            for next_token in tokens[idx + 1:idx + 4]:
                next_compact = next_token.replace(" ", "")
                if "ENDORSEMENT" in next_compact or "RESTRICTION" in next_compact:
                    continue
                if self._is_valid_license_class(next_compact):
                    return next_compact

        return None

    def _looks_like_person_name(self, value: str) -> bool:
        return bool(re.fullmatch(r"[A-Z][A-Z'\-]{1,30}", value or ""))

    def _find_likely_expiration(self, text: str) -> str | None:
        dates = [d for d in (self._normalize_date(v) for v in re.findall(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{2,4}\b", text)) if d]
        return max(dates) if dates else None

    def _find_likely_birth_date(self, text: str) -> str | None:
        rrn_match = re.search(r"\b(\d{6})[- ]?[1-4]\d{6}\b", text)
        if rrn_match:
            return self._normalize_korean_short_date(rrn_match.group(1))
        dates = [d for d in (self._normalize_date(v) for v in re.findall(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{2,4}\b", text)) if d]
        return min(dates) if dates else None

    def _find_id_number(self, text: str) -> str | None:
        patterns = [
            r"\b\d{2}-\d{2}-\d{5,8}-\d{2}\b",
            r"\b[A-Z]\d{7,12}\b",
        ]
        blocked = {"DRIVER", "LICENSE", "ARIZONA", "USA"}
        for pattern in patterns:
            for match in re.findall(pattern, text, re.IGNORECASE):
                if match.upper() not in blocked:
                    return match
        return None

    def _find_state(self, text: str) -> str | None:
        for full_name, code in self.STATE_NAME_TO_CODE.items():
            if full_name in text:
                return code
        match = re.search(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b", text)
        if match:
            return match.group(1)
        return None

    def _normalize_date(self, value: str) -> str | None:
        value = value.replace(".", "-").replace("/", "-")
        parts = [p for p in value.split("-") if p]
        if len(parts) != 3:
            return None

        if len(parts[0]) == 4:
            year, month, day = parts[0], parts[1], parts[2]
        elif len(parts[2]) == 4:
            year, month, day = parts[2], parts[0], parts[1]
        elif len(parts[0]) == 2 and len(parts[2]) == 2:
            year_num = int(parts[0])
            year = str(1900 + year_num if year_num >= 30 else 2000 + year_num)
            month, day = parts[1], parts[2]
        else:
            return None

        try:
            month_num = int(month)
            day_num = int(day)
            year_num = int(year)
        except ValueError:
            return None

        if not (1 <= month_num <= 12 and 1 <= day_num <= 31 and 1900 <= year_num <= 2100):
            return None
        return f"{year_num:04d}-{month_num:02d}-{day_num:02d}"

    def _normalize_korean_short_date(self, value: str) -> str:
        year = int(value[:2])
        month = int(value[2:4])
        day = int(value[4:6])
        year_full = 1900 + year if year >= 30 else 2000 + year
        return f"{year_full:04d}-{month:02d}-{day:02d}"

    def _to_upper_ascii(self, value: str) -> str:
        return self._clean_spaces(value).upper()

    def _clean_spaces(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()
