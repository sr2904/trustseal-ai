from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher

from app.models import CompareFieldResult, CompareResponse, ComplianceFlag, ParsedDocument


@dataclass
class DocumentProfile:
    first_name: str | None = None
    last_name: str | None = None
    dob: str | None = None
    address: str | None = None
    id_number: str | None = None
    expiration: str | None = None
    license_class: str | None = None
    issuing_state: str | None = None
    document_type: str = "unknown"


class CrossDocumentComparator:
    FIELDS = ["first_name", "last_name", "dob", "address", "id_number", "expiration", "license_class", "issuing_state"]
    EXPIRING_SOON_DAYS = 30
    NOTARY_GRACE_DAYS = 5 * 365
    IN_STATE_PROPERTY_STATES = {"TX", "FL"}
    ID_KEYWORDS = {"DRIVER LICENSE", "LICENSE", "DOB", "EXP", "DLN", "CLASS"}
    DOC_NAME_LABELS = [
        "NAME",
        "BORROWER",
        "CO-BORROWER",
        "APPLICANT",
        "CUSTOMER",
        "SIGNER",
        "OWNER",
    ]
    NON_NAME_TOKENS = {
        "UNIFORM",
        "RESIDENTIAL",
        "LOAN",
        "APPLICATION",
        "DATE",
        "BIRTH",
        "DOB",
        "EXP",
        "EXPIRES",
        "EXPIRATION",
        "PROPERTY",
        "ADDRESS",
        "SERVICE",
        "MAILING",
        "ACCOUNT",
        "STATEMENT",
        "UTILITY",
        "FORM",
        "TRUST",
        "DEED",
    }
    DOC_FIRST_NAME_LABELS = ["FIRST NAME", "GIVEN NAME"]
    DOC_LAST_NAME_LABELS = ["LAST NAME", "SURNAME", "FAMILY NAME"]
    DOC_ADDRESS_LABELS = [
        "PROPERTY ADDRESS",
        "RESIDENCE ADDRESS",
        "MAILING ADDRESS",
        "SERVICE ADDRESS",
        "ADDRESS",
        "PROPERTY",
    ]
    ADDRESS_SUFFIXES = {
        "STREET": "ST",
        "ST": "ST",
        "AVENUE": "AVE",
        "AVE": "AVE",
        "ROAD": "RD",
        "RD": "RD",
        "DRIVE": "DR",
        "DR": "DR",
        "LANE": "LN",
        "LN": "LN",
        "COURT": "CT",
        "CT": "CT",
        "BOULEVARD": "BLVD",
        "BLVD": "BLVD",
        "WAY": "WAY",
        "PLACE": "PL",
        "PL": "PL",
    }
    SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}
    NICKNAME_ROOTS = {
        "JEN": "JENNIFER",
        "JENNY": "JENNIFER",
        "JENN": "JENNIFER",
        "MIKE": "MICHAEL",
        "MATT": "MATTHEW",
        "KATIE": "KATHERINE",
        "KATE": "KATHERINE",
        "KAT": "KATHERINE",
        "DAVE": "DAVID",
        "BOB": "ROBERT",
        "ROB": "ROBERT",
        "ROBBIE": "ROBERT",
        "BILL": "WILLIAM",
        "WILL": "WILLIAM",
        "LIZ": "ELIZABETH",
        "BETH": "ELIZABETH",
        "LISA": "ELIZABETH",
        "TOM": "THOMAS",
        "CHRIS": "CHRISTOPHER",
        "PAT": "PATRICK",
        "JIM": "JAMES",
        "JIMMY": "JAMES",
        "JOE": "JOSEPH",
        "JOEY": "JOSEPH",
        "NICK": "NICHOLAS",
        "ALEX": "ALEXANDER",
        "SAM": "SAMUEL",
        "DAN": "DANIEL",
        "DANNY": "DANIEL",
        "ANDY": "ANDREW",
        "TONY": "ANTHONY",
    }

    def compare(self, first: ParsedDocument, second: ParsedDocument) -> CompareResponse:
        left_doc, right_doc = self._order_documents(first, second)
        left_profile = self._build_profile(left_doc)
        right_profile = self._build_profile(right_doc)

        comparisons = [
            self._compare_name_field("first_name", left_profile.first_name, right_profile.first_name),
            self._compare_name_field("last_name", left_profile.last_name, right_profile.last_name),
            self._compare_dob(left_profile.dob, right_profile.dob),
            self._compare_address(left_profile, right_profile),
            self._compare_identity_document_field(
                "id_number",
                left_profile,
                right_profile,
                "Document numbers align strongly.",
                "Document numbers do not align.",
            ),
            self._compare_identity_document_field(
                "expiration",
                left_profile,
                right_profile,
                "Expiration dates align.",
                "Expiration dates do not align.",
            ),
            self._compare_identity_document_field(
                "license_class",
                left_profile,
                right_profile,
                "License classes align.",
                "License classes do not align.",
            ),
            self._compare_identity_document_field(
                "issuing_state",
                left_profile,
                right_profile,
                "Issuing states align.",
                "Issuing states do not align.",
            ),
        ]

        scores = [item.confidence for item in comparisons if item.flag != "MISSING"]
        overall = round(sum(scores) / len(scores), 3) if scores else 0.0

        hard_fail = any(
            item.field == "dob" and item.flag == "MISMATCH"
            for item in comparisons
        )
        mismatch_count = sum(1 for item in comparisons if item.flag == "MISMATCH")
        partial_count = sum(1 for item in comparisons if item.flag == "PARTIAL_MATCH")

        if hard_fail or mismatch_count >= 2:
            verdict = "mismatch"
            recommendation = "Cross-document mismatch is material. Stop automatic approval and require manual review of the full packet."
        elif partial_count >= 1 or overall < 0.9:
            verdict = "partial_match"
            recommendation = "Documents partially align. Review the flagged fields before notarization."
        else:
            verdict = "strong_match"
            recommendation = "Documents align well overall. Keep standard human review, but no major cross-document inconsistency stands out."

        compliance_flags = self._build_compliance_flags(left_profile, right_profile, comparisons)
        if any(flag.severity == "fail" for flag in compliance_flags):
            recommendation += " Compliance review also found a fail-level issue that should block automatic approval."
        elif any(flag.severity == "warning" for flag in compliance_flags):
            recommendation += " Compliance review also found warning-level items that should be surfaced to the notary."

        return CompareResponse(
            comparisons=comparisons,
            overall_match_score=overall,
            verdict=verdict,
            recommendation=recommendation,
            compliance_flags=compliance_flags,
            id_document=self._profile_to_dict(left_profile),
            other_document=self._profile_to_dict(right_profile),
        )

    def _build_compliance_flags(
        self,
        id_profile: DocumentProfile,
        other_profile: DocumentProfile,
        comparisons: list[CompareFieldResult],
    ) -> list[ComplianceFlag]:
        flags: list[ComplianceFlag] = []
        by_field = {item.field: item for item in comparisons}

        expiration_date = self._safe_date(id_profile.expiration)
        if expiration_date:
            days_left = (expiration_date - date.today()).days
            if days_left < 0:
                grace_window = abs(days_left) <= self.NOTARY_GRACE_DAYS
                grace_text = (
                    " It may still fall inside a common in-person notary grace window of up to 5 years, but it is below NIST IAL2."
                    if grace_window
                    else " It is also outside the common 5-year state grace window cited in the challenge."
                )
                flags.append(
                    ComplianceFlag(
                        rule="Expired ID",
                        severity="fail",
                        message=f"ID expired {abs(days_left)} days ago.{grace_text}",
                        citation="NIST IAL2: expired IDs are an automatic fail for remote notarization; many states only allow an in-person grace window up to 5 years.",
                    )
                )
            elif days_left <= self.EXPIRING_SOON_DAYS:
                flags.append(
                    ComplianceFlag(
                        rule="Expiring Soon",
                        severity="warning",
                        message=f"ID expires in {days_left} days. Warn clearly, but do not hard fail solely for near-term expiration.",
                        citation="Challenge edge case: 12 days to expiration should be surfaced as a warning, not an automatic fail.",
                    )
                )
            else:
                flags.append(
                    ComplianceFlag(
                        rule="Expiration Check",
                        severity="pass",
                        message="ID expiration does not appear to create an immediate compliance issue.",
                        citation="Expiration standard: current IDs are acceptable, with separate edge-case handling for soon-to-expire documents.",
                    )
                )
        else:
            flags.append(
                ComplianceFlag(
                    rule="Expiration Evidence Missing",
                    severity="warning",
                    message="Expiration could not be confirmed from the ID, so a notary should verify it manually.",
                    citation="MISMO standard: the closing package should record the ID type and expiration date.",
                )
            )

        if not id_profile.document_type == "id":
            flags.append(
                ComplianceFlag(
                    rule="ID Standard Detection",
                    severity="fail",
                    message="The system could not confidently identify one document as a government ID, so compliance cannot be established.",
                    citation="Level 4 requires flagging IDs below notary-law standards before approval.",
                )
            )
        elif not id_profile.id_number:
            flags.append(
                ComplianceFlag(
                    rule="ID Record Completeness",
                    severity="warning",
                    message="Document number is missing from the extracted ID data, so the notarization record is incomplete.",
                    citation="MISMO standard: the notary record should capture the ID type and key identifying details.",
                )
            )

        for field_name, rule_name in (("first_name", "Name Review"), ("last_name", "Name Review"), ("dob", "DOB Review")):
            comparison = by_field.get(field_name)
            if not comparison:
                continue
            if comparison.flag == "MISMATCH":
                severity = "fail" if field_name == "dob" else "warning"
                flags.append(
                    ComplianceFlag(
                        rule=rule_name,
                        severity=severity,
                        message=f"{field_name.replace('_', ' ').title()} does not align across documents.",
                        citation="Level 4 requires name mismatches and hard identity discrepancies to be surfaced with a cited rule.",
                    )
                )
            elif comparison.flag == "PARTIAL_MATCH" and field_name in {"first_name", "last_name"}:
                flags.append(
                    ComplianceFlag(
                        rule="Name Review",
                        severity="warning",
                        message=f"{field_name.replace('_', ' ').title()} is only a partial match. Treat nickname or suffix differences as a review item, not a hard fail.",
                        citation="Challenge edge case: Jennifer vs. Jen should remain a partial match, not a mismatch.",
                    )
                )

        property_state = self._document_state(other_profile)
        id_state = self._document_state(id_profile)
        if (
            other_profile.document_type in {"deed", "loan_application", "utility_bill"}
            and property_state in self.IN_STATE_PROPERTY_STATES
            and id_state
            and property_state != id_state
        ):
            flags.append(
                ComplianceFlag(
                    rule="In-State ID Requirement",
                    severity="fail",
                    message=f"Property document points to {property_state}, but the signer ID points to {id_state}. Surface this as an in-state compliance issue.",
                    citation="Challenge rule: TX and FL require in-state ID for certain property transactions.",
                )
            )

        return flags

    def _order_documents(self, first: ParsedDocument, second: ParsedDocument) -> tuple[ParsedDocument, ParsedDocument]:
        first_id_score = self._id_likelihood(first)
        second_id_score = self._id_likelihood(second)
        return (first, second) if first_id_score >= second_id_score else (second, first)

    def _id_likelihood(self, doc: ParsedDocument) -> int:
        raw = doc.raw_text.upper()
        score = sum(1 for token in self.ID_KEYWORDS if token in raw)
        if self._field_value(doc, "id_number"):
            score += 2
        if self._field_value(doc, "expiration"):
            score += 1
        if self._field_value(doc, "license_class"):
            score += 1
        return score

    def _build_profile(self, doc: ParsedDocument) -> DocumentProfile:
        raw_upper = doc.raw_text.upper()
        lines = [line.upper() for line in doc.text_lines if line.strip()]

        profile = DocumentProfile(
            first_name=self._field_value(doc, "first_name"),
            last_name=self._field_value(doc, "last_name"),
            dob=self._field_value(doc, "dob"),
            address=self._field_value(doc, "address"),
            id_number=self._field_value(doc, "id_number"),
            expiration=self._field_value(doc, "expiration"),
            license_class=self._field_value(doc, "license_class"),
            issuing_state=self._field_value(doc, "issuing_state"),
            document_type=self._detect_document_type(raw_upper),
        )

        inferred_first, inferred_last = self._extract_name_from_text(lines)
        profile.first_name = profile.first_name or inferred_first
        profile.last_name = profile.last_name or inferred_last
        profile.dob = profile.dob or self._extract_dob_from_text(raw_upper)
        profile.address = profile.address or self._extract_address_from_text(lines)
        if profile.document_type == "id":
            profile.id_number = profile.id_number or self._extract_id_number_from_text(raw_upper)
            profile.expiration = profile.expiration or self._extract_expiration_from_text(raw_upper)
        profile.issuing_state = profile.issuing_state or self._extract_state_from_address(profile.address)
        return profile

    def _detect_document_type(self, raw_upper: str) -> str:
        if any(token in raw_upper for token in self.ID_KEYWORDS):
            return "id"
        if "UTILITY" in raw_upper or "ACCOUNT NUMBER" in raw_upper or "SERVICE ADDRESS" in raw_upper:
            return "utility_bill"
        if "DEED OF TRUST" in raw_upper or "DEED" in raw_upper or "PROPERTY ADDRESS" in raw_upper:
            return "deed"
        if "UNIFORM RESIDENTIAL LOAN APPLICATION" in raw_upper or "FORM 1003" in raw_upper or "BORROWER" in raw_upper:
            return "loan_application"
        return "unknown"

    def _compare_name_field(self, field: str, left: str | None, right: str | None) -> CompareFieldResult:
        if not left or not right:
            return self._missing(field, left, right)

        if field == "first_name":
            flag, confidence, explanation = self._compare_first_names(left, right)
        else:
            flag, confidence, explanation = self._compare_last_names(left, right)

        return CompareFieldResult(
            field=field,
            id_value=left,
            doc_value=right,
            match=flag == "MATCH",
            confidence=round(confidence, 3),
            flag=flag,
            explanation=explanation,
        )

    def _compare_first_names(self, left: str, right: str) -> tuple[str, float, str]:
        left_parts = self._name_parts(left)
        right_parts = self._name_parts(right)
        if not left_parts or not right_parts:
            left_clean = self._clean_name_value(left)
            right_clean = self._clean_name_value(right)
            if left_clean and right_clean and left_clean == right_clean:
                return "MATCH", 1.0, "First names match exactly."
            return "MISMATCH", 0.2, "First-name extraction was too weak to support a strong cross-document match."

        left_first = left_parts[0]
        right_first = right_parts[0]
        if left_first == right_first:
            if left_parts == right_parts:
                return "MATCH", 1.0, "First names match exactly."
            return "PARTIAL_MATCH", 0.86, "Core first name matches, but one document includes extra middle-name content."

        if self._nickname_root(left_first) == self._nickname_root(right_first):
            return "PARTIAL_MATCH", 0.82, "Nickname or familiar-form variation detected. Treat this as a review item, not a hard fail."

        ratio = self._similarity(left_first, right_first)
        if ratio >= 0.9:
            return "PARTIAL_MATCH", 0.78, "First names are very close and may reflect OCR variation."
        return "MISMATCH", max(0.1, ratio), "First names do not align strongly enough across documents."

    def _compare_last_names(self, left: str, right: str) -> tuple[str, float, str]:
        left_base, left_suffix = self._split_last_name(left)
        right_base, right_suffix = self._split_last_name(right)

        if left_base == right_base:
            if left_suffix == right_suffix:
                return "MATCH", 1.0, "Last names match exactly."
            return "PARTIAL_MATCH", 0.84, "Surname matches, but suffix usage differs between documents."

        ratio = self._similarity(left_base, right_base)
        if ratio >= 0.9:
            return "PARTIAL_MATCH", 0.76, "Last names are close and may reflect OCR drift or minor spelling variation."
        return "MISMATCH", max(0.05, ratio), "Last names do not align strongly enough across documents."

    def _compare_dob(self, left: str | None, right: str | None) -> CompareFieldResult:
        if not left or not right:
            return self._missing("dob", left, right)

        if left == right:
            return CompareFieldResult(
                field="dob",
                id_value=left,
                doc_value=right,
                match=True,
                confidence=1.0,
                flag="MATCH",
                explanation="Date of birth matches exactly.",
            )

        return CompareFieldResult(
            field="dob",
            id_value=left,
            doc_value=right,
            match=False,
            confidence=0.0,
            flag="MISMATCH",
            explanation="Date of birth differs across documents. Treat this as a hard identity flag.",
        )

    def _compare_address(self, left_profile: DocumentProfile, right_profile: DocumentProfile) -> CompareFieldResult:
        left = left_profile.address
        right = right_profile.address
        if not left or not right:
            return self._missing("address", left, right)

        left_norm = self._normalize_address(left)
        right_norm = self._normalize_address(right)
        left_state = self._extract_state_from_address(left_norm)
        right_state = self._extract_state_from_address(right_norm)

        if left_norm == right_norm:
            return CompareFieldResult(
                field="address",
                id_value=left,
                doc_value=right,
                match=True,
                confidence=1.0,
                flag="MATCH",
                explanation="Addresses match after normalization.",
            )

        same_zip = self._extract_zip(left_norm) and self._extract_zip(left_norm) == self._extract_zip(right_norm)
        same_state = left_state and right_state and left_state == right_state
        street_ratio = self._similarity(self._street_address_only(left_norm), self._street_address_only(right_norm))
        overall_ratio = self._similarity(left_norm, right_norm)

        if same_state and same_zip and street_ratio >= 0.88:
            return CompareFieldResult(
                field="address",
                id_value=left,
                doc_value=right,
                match=False,
                confidence=0.84,
                flag="PARTIAL_MATCH",
                explanation="Addresses are very close but not identical. Review for unit, punctuation, or OCR differences.",
            )

        if left_profile.document_type == "id" and right_profile.document_type in {"deed", "loan_application", "utility_bill"} and left_state and right_state and left_state != right_state:
            return CompareFieldResult(
                field="address",
                id_value=left,
                doc_value=right,
                match=False,
                confidence=min(0.4, round(overall_ratio, 3)),
                flag="MISMATCH",
                explanation="Address state differs from the ID state. For property or account documents, surface this as an out-of-state review flag.",
            )

        if overall_ratio >= 0.7:
            return CompareFieldResult(
                field="address",
                id_value=left,
                doc_value=right,
                match=False,
                confidence=round(overall_ratio, 3),
                flag="PARTIAL_MATCH",
                explanation="Addresses partially align, but the difference is material enough to require manual review.",
            )

        return CompareFieldResult(
            field="address",
            id_value=left,
            doc_value=right,
            match=False,
            confidence=round(overall_ratio, 3),
            flag="MISMATCH",
            explanation="Addresses do not align strongly across documents.",
        )

    def _compare_exactish(
        self,
        field: str,
        left: str | None,
        right: str | None,
        match_text: str,
        mismatch_text: str,
    ) -> CompareFieldResult:
        if not left or not right:
            return self._missing(field, left, right)

        ratio = self._similarity(left, right)
        if self._normalize(left) == self._normalize(right):
            flag = "MATCH"
            match = True
            confidence = 1.0
            explanation = match_text
        elif ratio >= 0.88:
            flag = "PARTIAL_MATCH"
            match = False
            confidence = 0.8
            explanation = f"{mismatch_text} The values are close enough that OCR variation is possible."
        else:
            flag = "MISMATCH"
            match = False
            confidence = ratio
            explanation = mismatch_text

        return CompareFieldResult(
            field=field,
            id_value=left,
            doc_value=right,
            match=match,
            confidence=round(confidence, 3),
            flag=flag,
            explanation=explanation,
        )

    def _missing(self, field: str, left: str | None, right: str | None) -> CompareFieldResult:
        return CompareFieldResult(
            field=field,
            id_value=left,
            doc_value=right,
            match=False,
            confidence=0.0,
            flag="MISSING",
            explanation="At least one side is missing, so the system cannot confidently compare this field.",
        )

    def _compare_identity_document_field(
        self,
        field: str,
        left_profile: DocumentProfile,
        right_profile: DocumentProfile,
        match_text: str,
        mismatch_text: str,
    ) -> CompareFieldResult:
        left = getattr(left_profile, field)
        right = getattr(right_profile, field)

        if left_profile.document_type != "id" or right_profile.document_type != "id":
            return CompareFieldResult(
                field=field,
                id_value=left,
                doc_value=right,
                match=False,
                confidence=0.0,
                flag="MISSING",
                explanation="This field is treated as ID-specific, so the system does not score it against non-ID documents.",
            )

        return self._compare_exactish(field, left, right, match_text, mismatch_text)

    def _extract_name_from_text(self, lines: list[str]) -> tuple[str | None, str | None]:
        labeled_first = self._extract_labeled_name_part(lines, self.DOC_FIRST_NAME_LABELS)
        labeled_last = self._extract_labeled_name_part(lines, self.DOC_LAST_NAME_LABELS)
        if labeled_first or labeled_last:
            return labeled_first, labeled_last

        for idx, line in enumerate(lines):
            compact = re.sub(r"\s+", " ", line).strip()
            for label in self.DOC_NAME_LABELS:
                if label not in compact:
                    continue

                candidate = compact.split(label, 1)[-1].strip(" :.-")
                if not candidate and idx + 1 < len(lines):
                    candidate = lines[idx + 1].strip()
                parsed = self._parse_full_name(candidate)
                if parsed != (None, None):
                    return parsed

        for line in lines:
            compact = re.sub(r"\s+", " ", line).strip()
            if (
                re.search(r"\d", compact)
                or re.search(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", compact)
                or any(label in compact for label in self.DOC_ADDRESS_LABELS)
                or any(token in compact for token in ["DATE OF BIRTH", "DOB", "EXP", "EXPIRATION"])
            ):
                continue
            parsed = self._parse_full_name(line)
            if parsed != (None, None):
                return parsed
        return None, None

    def _extract_labeled_name_part(self, lines: list[str], labels: list[str]) -> str | None:
        for idx, line in enumerate(lines):
            compact = re.sub(r"\s+", " ", line).strip()
            for label in labels:
                if label not in compact:
                    continue

                candidate = compact.split(label, 1)[-1].strip(" :.-")
                if not candidate and idx + 1 < len(lines):
                    candidate = lines[idx + 1].strip()
                tokens = [
                    token for token in re.findall(r"[A-Z][A-Z'-]{1,30}", candidate.upper())
                    if token not in {"FIRST", "LAST", "NAME", "GIVEN", "SURNAME", "FAMILY"}
                ]
                if tokens:
                    return tokens[0]
        return None

    def _parse_full_name(self, value: str) -> tuple[str | None, str | None]:
        tokens = [
            token for token in re.findall(r"[A-Z][A-Z'-]{1,30}", value.upper())
            if token not in {"NAME", "BORROWER", "APPLICANT", "CUSTOMER", "OWNER", "SIGNER"}
        ]
        if not tokens or any(token in self.NON_NAME_TOKENS for token in tokens):
            return None, None
        suffix = None
        if tokens and tokens[-1] in self.SUFFIXES:
            suffix = tokens[-1]
            tokens = tokens[:-1]
        if len(tokens) < 2 or len(tokens) > 3:
            return None, None
        first_name = tokens[0]
        last_name = tokens[-1] if not suffix else f"{tokens[-1]} {suffix}"
        return first_name, last_name

    def _extract_dob_from_text(self, raw_upper: str) -> str | None:
        patterns = [
            r"(?:DOB|DATE OF BIRTH|BIRTH DATE)\s*[:#]?\s*([0-9]{1,4}[./-][0-9]{1,2}[./-][0-9]{2,4})",
        ]
        for pattern in patterns:
            m = re.search(pattern, raw_upper)
            if m:
                normalized = self._normalize_date(m.group(1))
                if normalized:
                    return normalized
        return None

    def _extract_expiration_from_text(self, raw_upper: str) -> str | None:
        patterns = [
            r"(?:EXP|EXPIRES|EXPIRATION DATE)\s*[:#]?\s*([0-9]{1,4}[./-][0-9]{1,2}[./-][0-9]{2,4})",
        ]
        for pattern in patterns:
            m = re.search(pattern, raw_upper)
            if m:
                normalized = self._normalize_date(m.group(1))
                if normalized:
                    return normalized
        return None

    def _extract_id_number_from_text(self, raw_upper: str) -> str | None:
        patterns = [
            r"(?:ID(?:ENTIFICATION)?|ACCOUNT)\s*(?:NUMBER|NO)?\s*[:#]?\s*([A-Z0-9-]{6,24})",
            r"\b[A-Z]\d{7,12}\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, raw_upper)
            if m:
                return m.group(1)
        return None

    def _extract_address_from_text(self, lines: list[str]) -> str | None:
        for idx, line in enumerate(lines):
            compact = re.sub(r"\s+", " ", line).strip()

            for label in self.DOC_ADDRESS_LABELS:
                if label not in compact:
                    continue
                candidate = compact.split(label, 1)[-1].strip(" :.-")
                parts: list[str] = []
                if candidate:
                    parts.append(candidate)
                if idx + 1 < len(lines):
                    parts.append(lines[idx + 1].strip())
                if idx + 2 < len(lines) and re.search(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", lines[idx + 2]):
                    parts.append(lines[idx + 2].strip())
                address = self._stitch_address(parts)
                if address:
                    return address

        return self._find_plain_address(lines)

    def _find_plain_address(self, lines: list[str]) -> str | None:
        for idx, line in enumerate(lines):
            compact = re.sub(r"\s+", " ", line).strip()
            if re.search(r"\b\d{1,6}\s+[A-Z0-9 .'-]+\b(ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|DR|DRIVE|LN|LANE|WAY|CT|COURT)\b", compact):
                parts = [compact]
                if idx + 1 < len(lines) and re.search(r"\b[A-Z .'-]+,?\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", lines[idx + 1]):
                    parts.append(lines[idx + 1].strip())
                return self._stitch_address(parts)
        return None

    def _stitch_address(self, parts: list[str]) -> str | None:
        cleaned = [re.sub(r"\s+", " ", part).strip(" ,") for part in parts if part and part.strip(" ,")]
        if not cleaned:
            return None
        address = ", ".join(dict.fromkeys(cleaned))
        return address if re.search(r"\d", address) else None

    def _field_value(self, doc: ParsedDocument, key: str) -> str | None:
        field = doc.fields.get(key)
        return (field.value if field else None) or None

    def _name_parts(self, value: str) -> list[str]:
        ascii_parts = [part for part in re.findall(r"[A-Z][A-Z'-]{1,30}", value.upper()) if part not in self.SUFFIXES]
        if ascii_parts:
            return ascii_parts

        cleaned = self._clean_name_value(value)
        return [cleaned] if cleaned else []

    def _clean_name_value(self, value: str) -> str:
        normalized = re.sub(r"[\W_]+", "", value, flags=re.UNICODE).upper()
        return normalized or ""

    def _split_last_name(self, value: str) -> tuple[str, str | None]:
        parts = self._name_parts(value)
        if not parts:
            return "", None
        suffix = None
        raw_parts = re.findall(r"[A-Z][A-Z'-]{1,30}", value.upper())
        if raw_parts and raw_parts[-1] in self.SUFFIXES:
            suffix = raw_parts[-1]
        return parts[-1], suffix

    def _nickname_root(self, value: str) -> str:
        token = re.sub(r"[^A-Z]", "", value.upper())
        return self.NICKNAME_ROOTS.get(token, token)

    def _normalize_address(self, value: str) -> str:
        normalized = re.sub(r"[^A-Z0-9 ]", " ", value.upper())
        tokens = [token for token in normalized.split() if token]
        resolved = [self.ADDRESS_SUFFIXES.get(token, token) for token in tokens]
        return " ".join(resolved)

    def _street_address_only(self, value: str) -> str:
        normalized = self._normalize_address(value)
        tokens = normalized.split()
        if len(tokens) <= 3:
            return normalized
        state = self._extract_state_from_address(normalized)
        if state and state in tokens:
            tokens = tokens[:tokens.index(state)]
        zip_code = self._extract_zip(normalized)
        if zip_code and zip_code in tokens:
            tokens = [token for token in tokens if token != zip_code]
        return " ".join(tokens)

    def _extract_zip(self, value: str) -> str | None:
        m = re.search(r"\b\d{5}(?:-\d{4})?\b", value)
        return m.group(0) if m else None

    def _extract_state_from_address(self, value: str | None) -> str | None:
        if not value:
            return None
        m = re.search(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b", value.upper())
        if m:
            return m.group(1)
        return None

    def _document_state(self, profile: DocumentProfile) -> str | None:
        return profile.issuing_state or self._extract_state_from_address(profile.address)

    def _safe_date(self, value: str | None) -> date | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def _normalize_date(self, value: str) -> str | None:
        clean = value.replace(".", "-").replace("/", "-")
        parts = [part for part in clean.split("-") if part]
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
            year_num = int(year)
            month_num = int(month)
            day_num = int(day)
        except ValueError:
            return None

        if not (1900 <= year_num <= 2100 and 1 <= month_num <= 12 and 1 <= day_num <= 31):
            return None
        return f"{year_num:04d}-{month_num:02d}-{day_num:02d}"

    def _similarity(self, left: str, right: str) -> float:
        return SequenceMatcher(None, self._normalize(left), self._normalize(right)).ratio()

    def _normalize(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    def _profile_to_dict(self, profile: DocumentProfile) -> dict[str, str | None]:
        return {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "dob": profile.dob,
            "id_number": profile.id_number,
            "expiration": profile.expiration,
            "address": profile.address,
            "license_class": profile.license_class,
            "issuing_state": profile.issuing_state,
        }
