from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import AnalysisResult, HealthResponse, ImageMetrics
from app.services.cross_doc import CrossDocumentComparator
from app.services.document_parser import DocumentParser
from app.services.fraud_checks import FraudAnalyzer
from app.services.image_features import ImageFeatureExtractor
from app.services.ocr_service import OCRService

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title=settings.app_name, version=settings.version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ocr_service = OCRService()
image_feature_extractor = ImageFeatureExtractor()
document_parser = DocumentParser(ocr_service, image_feature_extractor)
fraud_analyzer = FraudAnalyzer()
comparator = CrossDocumentComparator()


def _build_analysis_result_from_parsed_document(
    parsed_document,
    *,
    metrics,
    ocr_provider: str,
    summary_prefix: str,
):
    (
        authenticity_label,
        authenticity_confidence,
        fraud_signals,
        compliance_flags,
        final_risk,
        recommendation,
        debug,
    ) = fraud_analyzer.analyze(metrics, parsed_document, ocr_provider)

    return AnalysisResult(
        authenticity_label=authenticity_label,
        authenticity_confidence=authenticity_confidence,
        summary=summary_prefix + fraud_analyzer._build_summary(
            authenticity_label,
            authenticity_confidence,
            fraud_signals,
            compliance_flags,
        ),
        image_metrics=metrics,
        fraud_signals=fraud_signals,
        compliance_flags=compliance_flags,
        parsed_document=parsed_document,
        final_risk=final_risk,
        recommendation=recommendation,
        debug=debug,
    )


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app=settings.app_name, version=settings.version)


@app.post("/api/analyze-id", response_model=AnalysisResult)
async def analyze_id(file: UploadFile = File(...)) -> AnalysisResult:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    file_bytes = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File too large. Max size is {settings.max_upload_mb}MB.")

    try:
        image = image_feature_extractor.load_image_bytes(file_bytes)
        metrics = image_feature_extractor.extract_metrics(image)
        parsed_document = ocr_service.run(image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected analysis error: {exc}") from exc

    return _build_analysis_result_from_parsed_document(
        parsed_document,
        metrics=metrics,
        ocr_provider=ocr_service.provider,
        summary_prefix="Language-agnostic ID verification completed. ",
    )


@app.post("/api/analyze-document", response_model=AnalysisResult)
async def analyze_document(file: UploadFile = File(...)) -> AnalysisResult:
    try:
        parsed_document = await document_parser.parse_upload(file)
        is_image = bool(file.content_type and file.content_type.startswith("image/"))

        if is_image:
            await file.seek(0)
            file_bytes = await file.read()
            image = image_feature_extractor.load_image_bytes(file_bytes)
            metrics = image_feature_extractor.extract_metrics(image)
            provider = ocr_service.provider
            prefix = "Single-document image analysis completed. "
        else:
            # Text-based uploads do not have image heuristics, so keep the
            # metrics neutral-positive and focus the output on extracted structure plus compliance.
            metrics = ImageMetrics(
                blur_score=140.0,
                brightness=120.0,
                glare_ratio=0.0,
                saturation=70.0,
                contrast=70.0,
                edge_density=0.05,
                width=1000,
                height=625,
                aspect_ratio=1.6,
                face_count=1,
            )
            provider = "document_parser"
            prefix = "Single-document file analysis completed. "

        return _build_analysis_result_from_parsed_document(
            parsed_document,
            metrics=metrics,
            ocr_provider=provider,
            summary_prefix=prefix,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected single-document analysis error: {exc}") from exc


@app.post("/api/compare-docs")
async def compare_docs(
    primary_file: UploadFile = File(...),
    secondary_file: UploadFile = File(...),
):
    try:
        first_doc = await document_parser.parse_upload(primary_file)
        second_doc = await document_parser.parse_upload(secondary_file)
        return comparator.compare(first_doc, second_doc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected comparison error: {exc}") from exc


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
