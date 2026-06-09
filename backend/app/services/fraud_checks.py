from __future__ import annotations

import re
from datetime import date, datetime

from app.models import ComplianceFlag, FraudSignal, ImageMetrics, ParsedDocument


class FraudAnalyzer:
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

    ID_KEYWORDS = [
        "DRIVER LICENSE", "DRIVER", "LICENSE", "DL", "DOB", "EXP", "CLASS",
        "운전면허", "면허증", "1종보통",
    ]
    STATE_ID_PATTERNS = {
        "AZ": r"[A-Z]\d{8}",
        "KR": r"\d{2}-\d{2}-\d{6,8}-\d{2}",
        "KR-GG": r"\d{2}-\d{2}-\d{6,8}-\d{2}",
    }

    def analyze(
        self,
        metrics: ImageMetrics,
        parsed_document: ParsedDocument,
        ocr_provider: str,
    ) -> tuple[str, float, list[FraudSignal], list[ComplianceFlag], str, str, dict]:
        signals: list[FraudSignal] = []
        compliance: list[ComplianceFlag] = []

        field_hits = sum(1 for key in self.REQUIRED_FIELDS if parsed_document.fields.get(key) and parsed_document.fields[key].value)
        completeness = field_hits / len(self.REQUIRED_FIELDS)
        keyword_hits = sum(1 for kw in self.ID_KEYWORDS if kw.lower() in parsed_document.raw_text.lower())
        keyword_score = min(keyword_hits / 4.0, 1.0)
        debug = {
            "ocr_provider": ocr_provider,
            "field_hits": field_hits,
            "field_completeness": round(completeness, 3),
            "keyword_score": round(keyword_score, 3),
        }

        screen_score = 0.05
        print_score = 0.05
        genuine_score = 0.05
        unknown_score = 0.05

        if metrics.face_count == 0:
            unknown_score += 0.30
            signals.append(FraudSignal(
                name="no_face_region_detected",
                level="warning",
                score=0.30,
                explanation="No clear face region was detected. Many driver licenses contain a portrait, so this weakens authenticity confidence.",
            ))
        else:
            genuine_score += 0.18

        if 1.3 <= metrics.aspect_ratio <= 1.9:
            genuine_score += 0.10
        else:
            unknown_score += 0.18
            signals.append(FraudSignal(
                name="non_card_aspect_ratio",
                level="warning",
                score=0.18,
                explanation="Image aspect ratio does not strongly resemble a single card-like ID capture.",
            ))

        if metrics.glare_ratio > 0.08:
            screen_score += 0.30
            signals.append(FraudSignal(
                name="screen_glare_pattern",
                level="warning",
                score=metrics.glare_ratio,
                explanation="High glare and bright reflection suggest the document may have been shown from a screen.",
            ))

        if metrics.brightness > 165 and metrics.contrast < 65:
            screen_score += 0.18
        if metrics.edge_density > 0.09 and metrics.glare_ratio > 0.03:
            screen_score += 0.10

        if metrics.blur_score < 95:
            print_score += 0.16
            signals.append(FraudSignal(
                name="soft_print_like_edges",
                level="warning",
                score=0.16,
                explanation="Very soft edges reduce confidence and can indicate a printout or low-fidelity recapture.",
            ))
        if metrics.saturation < 55 and metrics.glare_ratio < 0.03:
            print_score += 0.18
        if metrics.contrast < 55 and metrics.blur_score < 120:
            print_score += 0.10

        if completeness >= 0.75:
            genuine_score += 0.30
        elif completeness >= 0.50:
            genuine_score += 0.18
        elif completeness < 0.25:
            unknown_score += 0.22
            signals.append(FraudSignal(
                name="low_field_extraction_completeness",
                level="warning",
                score=1.0 - completeness,
                explanation="Too few required ID fields were extracted for a strong authenticity claim.",
            ))

        if keyword_score >= 0.5:
            genuine_score += 0.15
        elif keyword_score == 0:
            unknown_score += 0.18
            signals.append(FraudSignal(
                name="missing_id_keywords",
                level="warning",
                score=0.18,
                explanation="OCR text does not strongly resemble an ID document. Missing core markers like DOB, EXP, license, or local equivalents.",
            ))

        self._add_level1_consistency_checks(parsed_document, signals, debug)

        id_number = parsed_document.fields.get("id_number")
        if not id_number or not id_number.value:
            unknown_score += 0.15
            signals.append(FraudSignal(
                name="missing_id_number",
                level="critical",
                score=0.15,
                explanation="A recognizable document number was not extracted, which is a major authenticity and usability concern.",
            ))

        expiration_value = parsed_document.fields.get("expiration")
        expiration_date = self._safe_date(expiration_value.value if expiration_value else None)
        if expiration_date:
            days_left = (expiration_date - date.today()).days
            debug["days_to_expiration"] = days_left
            if days_left < 0:
                compliance.append(ComplianceFlag(
                    rule="Expiration standard",
                    severity="fail",
                    message="ID appears expired. Most notary workflows require a current ID or one within the allowed grace period.",
                    citation="NIST IAL2: expired IDs are an automatic fail for remote notarization; many states require the ID to be current or within a limited grace period.",
                ))
            elif days_left <= 30:
                compliance.append(ComplianceFlag(
                    rule="Expiration warning",
                    severity="warning",
                    message=f"ID expires in {days_left} days. Surface this clearly as expiring soon, not an automatic fail.",
                    citation="Expiration standard: surface near-term expiration as a warning. Challenge edge case: 12 days to expiration should not hard fail by itself.",
                ))
            else:
                compliance.append(ComplianceFlag(
                    rule="Expiration check",
                    severity="pass",
                    message="ID does not appear close to expiration based on the extracted date.",
                    citation="Expiration standard: current IDs are generally acceptable, subject to state-specific notary rules.",
                ))
        else:
            compliance.append(ComplianceFlag(
                rule="Expiration extraction",
                severity="warning",
                message="Expiration date could not be confidently extracted. Ask the reviewer to verify it manually.",
                citation="MISMO standard: the notary record should capture the ID type and expiration date in the closing package.",
            ))

        scores = {
            "genuine": genuine_score,
            "screen": screen_score,
            "print": print_score,
            "unknown": unknown_score,
        }
        total = sum(scores.values()) or 1.0
        probabilities = {k: v / total for k, v in scores.items()}
        authenticity_label = max(probabilities, key=probabilities.get)
        authenticity_confidence = round(probabilities[authenticity_label], 3)
        debug["scores"] = {k: round(v, 3) for k, v in probabilities.items()}

        if authenticity_label in {"screen", "print", "unknown"} or any(flag.severity == "fail" for flag in compliance):
            final_risk = "high"
            recommendation = "Flag for manual review before notarization. Ask for a better capture or original physical document."
        elif any(flag.severity == "warning" for flag in compliance) or len(signals) >= 2:
            final_risk = "medium"
            recommendation = "Proceed with caution. Review extracted fields and ask for a cleaner image if needed."
        else:
            final_risk = "low"
            recommendation = "Low immediate risk based on current checks, but keep a human reviewer in the loop."

        summary = self._build_summary(authenticity_label, authenticity_confidence, signals, compliance)
        return authenticity_label, authenticity_confidence, signals, compliance, final_risk, recommendation, debug

    def _safe_date(self, value: str | None) -> date | None:
        if not value:
            return None
        for fmt in ["%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y"]:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _add_level1_consistency_checks(
        self,
        parsed_document: ParsedDocument,
        signals: list[FraudSignal],
        debug: dict,
    ) -> None:
        raw_text = parsed_document.raw_text.upper()
        issuing_state = (parsed_document.fields.get("issuing_state").value if parsed_document.fields.get("issuing_state") else None) or self._infer_state_from_text(raw_text)
        id_number = parsed_document.fields.get("id_number").value if parsed_document.fields.get("id_number") else None

        if issuing_state and id_number:
            pattern = self.STATE_ID_PATTERNS.get(issuing_state)
            if pattern and not self._matches_pattern(id_number, pattern):
                signals.append(FraudSignal(
                    name="state_id_format_violation",
                    level="warning",
                    score=0.22,
                    explanation=f"Document number does not match the expected {issuing_state} format. This is a structural authenticity warning.",
                ))
                debug["state_id_format_violation"] = {"issuing_state": issuing_state, "id_number": id_number}

        short_year_patterns = [
            r"(?:DOB|DATE OF BIRTH)\s*[:#]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2}\b",
            r"(?:EXP|EXPIRES|EXPIRATION DATE)\s*[:#]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2}\b",
        ]
        if any(re.search(pattern, raw_text) for pattern in short_year_patterns):
            signals.append(FraudSignal(
                name="date_format_violation",
                level="warning",
                score=0.18,
                explanation="DOB or expiration appears with a 2-digit year in raw OCR text. That is a format-pattern warning for authenticity review.",
            ))
            debug["date_format_violation"] = True

    def _infer_state_from_text(self, text: str) -> str | None:
        for name, code in {
            "ARIZONA": "AZ",
            "FLORIDA": "FL",
            "TEXAS": "TX",
        }.items():
            if name in text:
                return code
        if any(token in text for token in ["운전면허", "면허증", "1종보통"]):
            return "KR"
        return None

    def _matches_pattern(self, value: str, pattern: str) -> bool:
        return bool(re.fullmatch(pattern, value.strip().upper()))

    def _build_summary(self, label: str, confidence: float, signals: list[FraudSignal], compliance: list[ComplianceFlag]) -> str:
        signal_text = signals[0].explanation if signals else "No major fraud signal dominated this scan."
        compliance_text = next((c.message for c in compliance if c.severity != "pass"), "Compliance checks look acceptable.")
        return (
            f"Predicted presentation type: {label} ({confidence:.0%} confidence). "
            f"Top signal: {signal_text} {compliance_text}"
        )
