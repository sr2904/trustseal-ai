from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class OCRField(BaseModel):
    value: str | None = None
    confidence: float = 0.0
    source: str = "derived"


class FraudSignal(BaseModel):
    name: str
    level: Literal["info", "warning", "critical"]
    score: float = 0.0
    explanation: str


class ComplianceFlag(BaseModel):
    rule: str
    severity: Literal["pass", "warning", "fail"]
    message: str
    citation: str | None = None


class ImageMetrics(BaseModel):
    blur_score: float = 0.0
    brightness: float = 0.0
    glare_ratio: float = 0.0
    saturation: float = 0.0
    contrast: float = 0.0
    edge_density: float = 0.0
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    face_count: int = 0


class ParsedDocument(BaseModel):
    raw_text: str = ""
    fields: dict[str, OCRField] = Field(default_factory=dict)
    text_lines: list[str] = Field(default_factory=list)
    language_note: str = "Language-agnostic pipeline: raw OCR is compared structurally."


class AnalysisResult(BaseModel):
    authenticity_label: Literal["genuine", "screen", "print", "unknown"]
    authenticity_confidence: float
    summary: str
    image_metrics: ImageMetrics
    fraud_signals: list[FraudSignal]
    compliance_flags: list[ComplianceFlag]
    parsed_document: ParsedDocument
    final_risk: Literal["low", "medium", "high"]
    recommendation: str
    debug: dict[str, Any] = Field(default_factory=dict)


class CompareFieldResult(BaseModel):
    field: str
    id_value: str | None
    doc_value: str | None
    match: bool
    confidence: float
    flag: Literal["MATCH", "PARTIAL_MATCH", "MISMATCH", "MISSING"]
    explanation: str


class CompareResponse(BaseModel):
    comparisons: list[CompareFieldResult]
    overall_match_score: float
    verdict: Literal["strong_match", "partial_match", "mismatch"]
    recommendation: str
    compliance_flags: list[ComplianceFlag] = Field(default_factory=list)
    id_document: dict[str, str | None] = Field(default_factory=dict)
    other_document: dict[str, str | None] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
