from __future__ import annotations

import io
import pathlib
import sys
import unittest
import zipfile

from fastapi import UploadFile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.document_parser import DocumentParser
from app.services.image_features import ImageFeatureExtractor
from app.services.ocr_service import OCRService


class DocumentParserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.parser = DocumentParser(OCRService(), ImageFeatureExtractor())

    async def test_plain_text_upload_is_parsed_into_fields(self) -> None:
        upload = UploadFile(
            filename="sample.txt",
            file=io.BytesIO(
                b"Name: Driver Sample\nDOB: 02/14/2003\nAddress: 1234 Example St\nPhoenix, AZ 85007\n"
            ),
            headers={"content-type": "text/plain"},
        )

        parsed = await self.parser.parse_upload(upload)

        self.assertEqual(parsed.fields["first_name"].value, "DRIVER")
        self.assertEqual(parsed.fields["last_name"].value, "SAMPLE")
        self.assertEqual(parsed.fields["dob"].value, "2003-02-14")
        self.assertEqual(parsed.fields["address"].value, "1234 EXAMPLE ST, PHOENIX, AZ 85007")

    async def test_json_upload_is_flattened_for_comparison(self) -> None:
        upload = UploadFile(
            filename="sample.json",
            file=io.BytesIO(
                b'{ "borrower": { "name": "Driver Sample", "dob": "02/14/2003" }, "address": "1234 Example St\\nPhoenix, AZ 85007" }'
            ),
            headers={"content-type": "application/json"},
        )

        parsed = await self.parser.parse_upload(upload)

        self.assertIn("borrower", parsed.raw_text.lower())
        self.assertEqual(parsed.fields["dob"].value, "2003-02-14")

    async def test_csv_upload_is_converted_to_text_lines(self) -> None:
        upload = UploadFile(
            filename="sample.csv",
            file=io.BytesIO(
                b"field,value\nname,Driver Sample\ndob,02/14/2003\naddress,1234 Example St Phoenix AZ 85007\n"
            ),
            headers={"content-type": "text/csv"},
        )

        parsed = await self.parser.parse_upload(upload)

        self.assertIn("field value", parsed.raw_text.lower())
        self.assertEqual(parsed.fields["dob"].value, "2003-02-14")

    async def test_docx_upload_is_extracted(self) -> None:
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>Name: Driver Sample</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>DOB: 02/14/2003</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Address: 1234 Example St</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Phoenix, AZ 85007</w:t></w:r></w:p>"
            "</w:body></w:document>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("word/document.xml", xml)
        buf.seek(0)

        upload = UploadFile(
            filename="sample.docx",
            file=buf,
            headers={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )

        parsed = await self.parser.parse_upload(upload)

        self.assertEqual(parsed.fields["first_name"].value, "DRIVER")
        self.assertEqual(parsed.fields["last_name"].value, "SAMPLE")


if __name__ == "__main__":
    unittest.main()
