from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.models import ImageMetrics, OCRField, ParsedDocument
from app.services.fraud_checks import FraudAnalyzer
from app.services.ocr_service import OCRService


class FraudAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = FraudAnalyzer()

    def test_level1_flags_state_id_format_violation(self) -> None:
        parsed = ParsedDocument(
            raw_text="ARIZONA DRIVER LICENSE\nDOB 02/14/1974\nEXP 02/01/2028",
            fields={
                "first_name": OCRField(value="JANE", confidence=0.9),
                "last_name": OCRField(value="DOE", confidence=0.9),
                "dob": OCRField(value="1974-02-14", confidence=0.9),
                "expiration": OCRField(value="2028-02-01", confidence=0.9),
                "address": OCRField(value="1234 EXAMPLE ST, PHOENIX AZ 85007", confidence=0.9),
                "id_number": OCRField(value="12345678", confidence=0.9),
                "license_class": OCRField(value="D", confidence=0.9),
                "issuing_state": OCRField(value="AZ", confidence=0.9),
            },
        )

        _, _, signals, _, _, _, debug = self.analyzer.analyze(
            ImageMetrics(width=1000, height=625, aspect_ratio=1.6, face_count=1, blur_score=140, brightness=120, contrast=70, saturation=70, edge_density=0.05, glare_ratio=0.0),
            parsed,
            "test",
        )

        names = {signal.name for signal in signals}
        self.assertIn("state_id_format_violation", names)
        self.assertIn("state_id_format_violation", debug)

    def test_level1_flags_two_digit_date_format_violation(self) -> None:
        parsed = ParsedDocument(
            raw_text="ARIZONA DRIVER LICENSE\nDOB 02/14/74\nEXP 02/01/28",
            fields={
                "first_name": OCRField(value="JANE", confidence=0.9),
                "last_name": OCRField(value="DOE", confidence=0.9),
                "dob": OCRField(value="1974-02-14", confidence=0.9),
                "expiration": OCRField(value="2028-02-01", confidence=0.9),
                "address": OCRField(value="1234 EXAMPLE ST, PHOENIX AZ 85007", confidence=0.9),
                "id_number": OCRField(value="D12345678", confidence=0.9),
                "license_class": OCRField(value="D", confidence=0.9),
                "issuing_state": OCRField(value="AZ", confidence=0.9),
            },
        )

        _, _, signals, _, _, _, _ = self.analyzer.analyze(
            ImageMetrics(width=1000, height=625, aspect_ratio=1.6, face_count=1, blur_score=140, brightness=120, contrast=70, saturation=70, edge_density=0.05, glare_ratio=0.0),
            parsed,
            "test",
        )

        self.assertIn("date_format_violation", {signal.name for signal in signals})


class OCRServiceFailureTests(unittest.TestCase):
    def test_image_ocr_failure_is_explicit(self) -> None:
        service = OCRService()
        service._provider_initialized = True
        service._provider = "regex_only"
        service._provider_error = "Image OCR could not start."

        import numpy as np

        with self.assertRaisesRegex(ValueError, "Image OCR could not start"):
            service.run(np.zeros((40, 40, 3), dtype=np.uint8))


if __name__ == "__main__":
    unittest.main()
