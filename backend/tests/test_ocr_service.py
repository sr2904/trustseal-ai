from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.ocr_service import OCRService


class OCRServiceArizonaParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = OCRService()

    def test_arizona_front_extracts_names_and_class_from_numbered_fields(self) -> None:
        lines = [
            "ARIZONA USA",
            "DRIVER LICENSE",
            "4d DLN D02141248",
            "4b EXP 02/01/2028",
            "3 DOB 02/14/2003",
            "Driver Sample",
            "1 SAMPLE",
            "2 DRIVER",
            "8 1234 EXAMPLE ST",
            "PHOENIX, AZ 85007",
            "9 CLASS D",
            "9a ENDORSEMENTS NONE",
        ]

        parsed = self.service._extract_us_like_id("\n".join(lines), lines)

        self.assertEqual(parsed["last_name"], "SAMPLE")
        self.assertEqual(parsed["first_name"], "DRIVER")
        self.assertEqual(parsed["license_class"], "D")

    def test_arizona_split_class_value_is_captured_from_context(self) -> None:
        lines = [
            "ARIZONA USA",
            "DRIVER LICENSE",
            "4d DLN D02141248",
            "4b EXP 02/01/2028",
            "3 DOB 02/14/1974",
            "1 SAMPLE",
            "2 DRIVER",
            "8 1234 EXAMPLE ST",
            "PHOENIX, AZ 85007",
            "9 CLASS",
            "D",
            "9a ENDORSEMENTS NONE",
            "12 RESTRICTIONS B",
        ]

        parsed = self.service._extract_us_like_id("\n".join(lines), lines)

        self.assertEqual(parsed["last_name"], "SAMPLE")
        self.assertEqual(parsed["first_name"], "DRIVER")
        self.assertEqual(parsed["license_class"], "D")

    def test_arizona_standalone_name_lines_above_address_are_used(self) -> None:
        lines = [
            "ARIZONA",
            "DRIVER LICENSE",
            "Ad DLN",
            "D02141248",
            "46 EXP",
            "02/01/2028",
            "DOB",
            "02/14/2003",
            "Dvr Syt",
            "SAMPLE",
            "DRIVER",
            "1234 EXAMPLE ST",
            "PHOENIX AZ 85007",
            "CLASS",
        ]

        parsed = self.service._extract_us_like_id("\n".join(lines), lines)

        self.assertEqual(parsed["last_name"], "SAMPLE")
        self.assertEqual(parsed["first_name"], "DRIVER")

    def test_parse_text_document_uses_generic_labels_for_non_id_form(self) -> None:
        text = "\n".join(
            [
                "Uniform Residential Loan Application",
                "First Name: Jennifer",
                "Last Name: Smith",
                "Date of Birth: 02/14/1974",
                "Property Address: 1234 Example Street",
                "Phoenix, AZ 85007",
            ]
        )

        parsed = self.service.parse_text_document(text)

        self.assertEqual(parsed.fields["first_name"].value, "JENNIFER")
        self.assertEqual(parsed.fields["last_name"].value, "SMITH")
        self.assertEqual(parsed.fields["dob"].value, "1974-02-14")
        self.assertEqual(parsed.fields["address"].value, "1234 EXAMPLE STREET, PHOENIX, AZ 85007")
        self.assertIsNone(parsed.fields["id_number"].value)
        self.assertIsNone(parsed.fields["expiration"].value)


if __name__ == "__main__":
    unittest.main()
