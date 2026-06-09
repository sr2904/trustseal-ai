from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.models import OCRField, ParsedDocument
from app.services.cross_doc import CrossDocumentComparator


def build_doc(
    *,
    raw_text: str = "",
    text_lines: list[str] | None = None,
    **fields: str | None,
) -> ParsedDocument:
    return ParsedDocument(
        raw_text=raw_text,
        text_lines=text_lines or raw_text.splitlines(),
        fields={
            key: OCRField(value=value, confidence=0.9, source="test")
            for key, value in fields.items()
        },
    )


class CrossDocumentComparatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.comparator = CrossDocumentComparator()

    def test_nickname_and_suffix_become_partial_matches(self) -> None:
        id_doc = build_doc(
            raw_text="ARIZONA DRIVER LICENSE DOB 02/14/1974 EXP 02/01/2028",
            first_name="JENNIFER",
            last_name="SMITH",
            dob="1974-02-14",
            address="1234 EXAMPLE ST, PHOENIX AZ 85007",
            id_number="D02141248",
            expiration="2028-02-01",
            issuing_state="AZ",
            license_class="D",
        )
        loan_doc = build_doc(
            raw_text="\n".join(
                [
                    "Uniform Residential Loan Application",
                    "Borrower Name: Jen Marie Smith Jr",
                    "Date of Birth: 02/14/1974",
                    "Property Address: 1234 Example Street",
                    "Phoenix, AZ 85007",
                ]
            )
        )

        result = self.comparator.compare(loan_doc, id_doc)
        by_field = {item.field: item for item in result.comparisons}

        self.assertEqual(by_field["first_name"].flag, "PARTIAL_MATCH")
        self.assertEqual(by_field["last_name"].flag, "PARTIAL_MATCH")
        self.assertEqual(by_field["dob"].flag, "MATCH")
        self.assertEqual(by_field["address"].flag, "MATCH")

    def test_dob_mismatch_is_hard_flag(self) -> None:
        id_doc = build_doc(
            raw_text="DRIVER LICENSE DOB 02/14/1974",
            first_name="DRIVER",
            last_name="SAMPLE",
            dob="1974-02-14",
            issuing_state="AZ",
        )
        other_doc = build_doc(
            raw_text="Borrower Name: Driver Sample\nDate of Birth: 02/15/1974"
        )

        result = self.comparator.compare(id_doc, other_doc)
        by_field = {item.field: item for item in result.comparisons}

        self.assertEqual(by_field["dob"].flag, "MISMATCH")
        self.assertIn("hard identity flag", by_field["dob"].explanation.lower())
        self.assertEqual(result.verdict, "mismatch")

    def test_out_of_state_property_address_is_mismatch(self) -> None:
        id_doc = build_doc(
            raw_text="ARIZONA DRIVER LICENSE",
            first_name="DRIVER",
            last_name="SAMPLE",
            dob="1974-02-14",
            address="1234 EXAMPLE ST, PHOENIX AZ 85007",
            issuing_state="AZ",
        )
        deed_doc = build_doc(
            raw_text="Deed of Trust\nBorrower Name: Driver Sample\nProperty Address: 88 Ocean View Rd\nSan Diego, CA 92101"
        )

        result = self.comparator.compare(id_doc, deed_doc)
        by_field = {item.field: item for item in result.comparisons}

        self.assertEqual(by_field["address"].flag, "MISMATCH")
        self.assertIn("out-of-state", by_field["address"].explanation.lower())

    def test_non_id_secondary_doc_does_not_force_id_number_or_expiration_mismatch(self) -> None:
        id_doc = build_doc(
            raw_text="ARIZONA DRIVER LICENSE DOB 02/14/1974 EXP 02/01/2028",
            first_name="JANE",
            last_name="DOE",
            dob="1974-02-14",
            address="1234 EXAMPLE ST, PHOENIX AZ 85007",
            id_number="D02141248",
            expiration="2028-02-01",
            issuing_state="AZ",
        )
        loan_doc = build_doc(
            raw_text="Uniform Residential Loan Application\nBorrower Name: Jane Doe\nDate of Birth: 02/14/1974\nProperty Address: 1234 Example St\nPhoenix, AZ 85007\nAccount Number: 99887766"
        )

        result = self.comparator.compare(id_doc, loan_doc)
        by_field = {item.field: item for item in result.comparisons}

        self.assertEqual(by_field["id_number"].flag, "MISSING")
        self.assertEqual(by_field["expiration"].flag, "MISSING")
        self.assertIn("id-specific", by_field["id_number"].explanation.lower())
        self.assertIsNone(by_field["id_number"].doc_value)
        self.assertIsNone(by_field["expiration"].doc_value)

    def test_labeled_first_and_last_name_fields_are_parsed_for_non_id_docs(self) -> None:
        id_doc = build_doc(
            raw_text="ARIZONA DRIVER LICENSE DOB 02/14/1974 EXP 02/01/2028",
            first_name="JANE",
            last_name="DOE",
            dob="1974-02-14",
            address="1234 EXAMPLE ST, PHOENIX AZ 85007",
            issuing_state="AZ",
        )
        form_doc = build_doc(
            raw_text="\n".join(
                [
                    "Uniform Residential Loan Application",
                    "First Name: Jane",
                    "Last Name: Doe",
                    "Date of Birth: 02/14/1974",
                    "Property Address: 1234 Example St",
                    "Phoenix, AZ 85007",
                ]
            )
        )

        result = self.comparator.compare(id_doc, form_doc)
        by_field = {item.field: item for item in result.comparisons}

        self.assertEqual(by_field["first_name"].flag, "MATCH")
        self.assertEqual(by_field["last_name"].flag, "MATCH")

    def test_identical_korean_first_name_is_match(self) -> None:
        left_doc = build_doc(
            raw_text="대한민국 운전면허증",
            first_name="낭월",
            last_name="김",
            dob="1976-04-08",
            address="경기도 부천시",
            id_number="11-99-035960-80",
            expiration="2028-12-31",
            issuing_state="KR",
        )
        right_doc = build_doc(
            raw_text="대한민국 운전면허증",
            first_name="낭월",
            last_name="김",
            dob="1976-04-08",
            address="경기도 부천시",
            id_number="11-99-035960-80",
            expiration="2028-12-31",
            issuing_state="KR",
        )

        result = self.comparator.compare(left_doc, right_doc)
        by_field = {item.field: item for item in result.comparisons}

        self.assertEqual(by_field["first_name"].flag, "MATCH")
        self.assertEqual(by_field["first_name"].confidence, 1.0)

    def test_document_title_is_not_used_as_name_in_fallback_parsing(self) -> None:
        id_doc = build_doc(
            raw_text="대한민국 운전면허증",
            first_name="낭월",
            last_name="김",
            dob="1976-04-08",
            address="경기도 부천시",
            id_number="11-99-035960-80",
            expiration="2028-12-31",
            issuing_state="KR",
        )
        other_doc = build_doc(
            raw_text="\n".join(
                [
                    "Uniform Residential Loan Application",
                    "Date of Birth: 04/08/1976",
                    "Property Address: 1234 Example Street",
                    "Phoenix, AZ 85007",
                ]
            )
        )

        result = self.comparator.compare(id_doc, other_doc)
        by_field = {item.field: item for item in result.comparisons}

        self.assertEqual(by_field["first_name"].flag, "MISSING")
        self.assertIsNone(by_field["first_name"].doc_value)
        self.assertEqual(by_field["last_name"].flag, "MISSING")
        self.assertIsNone(by_field["last_name"].doc_value)

    def test_level4_expired_id_adds_compliance_fail_with_citation(self) -> None:
        id_doc = build_doc(
            raw_text="ARIZONA DRIVER LICENSE DOB 02/14/1974 EXP 01/01/2024",
            first_name="JANE",
            last_name="DOE",
            dob="1974-02-14",
            address="1234 EXAMPLE ST, PHOENIX AZ 85007",
            id_number="D02141248",
            expiration="2024-01-01",
            issuing_state="AZ",
        )
        loan_doc = build_doc(
            raw_text="Uniform Residential Loan Application\nBorrower Name: Jane Doe\nDate of Birth: 02/14/1974\nProperty Address: 1234 Example St\nPhoenix, AZ 85007"
        )

        result = self.comparator.compare(id_doc, loan_doc)
        expired_flag = next(item for item in result.compliance_flags if item.rule == "Expired ID")

        self.assertEqual(expired_flag.severity, "fail")
        self.assertIn("nist ial2", (expired_flag.citation or "").lower())

    def test_level4_expiring_soon_is_warning_not_fail(self) -> None:
        id_doc = build_doc(
            raw_text="ARIZONA DRIVER LICENSE EXP 04/24/2026",
            first_name="JANE",
            last_name="DOE",
            dob="1974-02-14",
            address="1234 EXAMPLE ST, PHOENIX AZ 85007",
            id_number="D02141248",
            expiration="2026-04-24",
            issuing_state="AZ",
        )
        loan_doc = build_doc(
            raw_text="Uniform Residential Loan Application\nBorrower Name: Jane Doe\nDate of Birth: 02/14/1974\nProperty Address: 1234 Example St\nPhoenix, AZ 85007"
        )

        result = self.comparator.compare(id_doc, loan_doc)
        soon_flag = next(item for item in result.compliance_flags if item.rule == "Expiring Soon")

        self.assertEqual(soon_flag.severity, "warning")
        self.assertIn("do not hard fail", soon_flag.message.lower())

    def test_level4_tx_property_out_of_state_id_is_fail(self) -> None:
        id_doc = build_doc(
            raw_text="ARIZONA DRIVER LICENSE",
            first_name="JANE",
            last_name="DOE",
            dob="1974-02-14",
            address="1234 EXAMPLE ST, PHOENIX AZ 85007",
            id_number="D02141248",
            expiration="2028-02-01",
            issuing_state="AZ",
        )
        deed_doc = build_doc(
            raw_text="Deed of Trust\nBorrower Name: Jane Doe\nProperty Address: 88 Ocean View Rd\nDallas, TX 75001"
        )

        result = self.comparator.compare(id_doc, deed_doc)
        state_flag = next(item for item in result.compliance_flags if item.rule == "In-State ID Requirement")

        self.assertEqual(state_flag.severity, "fail")
        self.assertIn("tx and fl", (state_flag.citation or "").lower())


if __name__ == "__main__":
    unittest.main()
