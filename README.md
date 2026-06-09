# TrustSeal AI — Document Verification Platform

<div align="center">

**AI-powered identity verification and document authentication for notarization workflows**

[![GitHub](https://img.shields.io/badge/GitHub-sr2904%2Ftrusteal--ai-blue?logo=github)](https://github.com/sr2904/trustseal-ai)
[![Demo](https://img.shields.io/badge/Demo-YouTube-red?logo=youtube)](https://youtu.be/CF3Ra36zS4w)
![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green?logo=fastapi)
![JavaScript](https://img.shields.io/badge/JavaScript-ES6-yellow?logo=javascript)

</div>

---

## What This Is

TrustSeal AI is an intelligent document verification platform built for notarization and identity review workflows. It analyzes uploaded documents, extracts structured fields, detects fraud signals, compares documents for consistency, and surfaces compliance issues — turning a manual, error-prone review process into a fast, explainable decision.

---

## The Problem

Notarization and document review are manual, time-consuming, and error-prone. Reviewers inspect document quality, verify identity details across multiple files, and catch compliance issues under time pressure. Small inconsistencies, poor image quality, or expired IDs can be missed, while harmless formatting differences create unnecessary friction.

---

## System Architecture

```
User uploads document(s)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Backend                      │
│                      main.py                            │
│                                                         │
│  /api/analyze-id        → Single ID image analysis     │
│  /api/analyze-document  → Single doc (any format)      │
│  /api/compare-docs      → Cross-document comparison    │
└──────────┬──────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│                   Service Pipeline                       │
│                                                          │
│  ImageFeatureExtractor  ─────► blur, glare, brightness  │
│         │                      contrast, edge density   │
│         ▼                                               │
│    OCRService  ──────────────► raw text extraction      │
│         │                      field parsing            │
│         ▼                                               │
│  DocumentParser  ────────────► PDF, DOCX, JSON, CSV     │
│         │                      HTML, XML, TXT           │
│         ▼                                               │
│   FraudAnalyzer  ────────────► authenticity label       │
│         │                      fraud signals            │
│         │                      compliance flags         │
│         │                      risk level + rec         │
│         ▼                                               │
│  CrossDocumentComparator ────► field-by-field compare   │
│                                name, DOB, address       │
│                                ID number, expiration    │
│                                verdict + compliance     │
└──────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│               Frontend (HTML/CSS/JS)                     │
│                                                          │
│  Single Doc Mode  ─── upload → analyze → results        │
│  Multi Doc Mode   ─── upload 2 → compare → table        │
│  Download/Copy Report                                    │
│  4 Accessibility modes                                   │
└──────────────────────────────────────────────────────────┘
```

---

## Key Features

### Level 1 — Authenticity Analysis
```
Upload ID image
      │
      ▼
Image Feature Extraction (OpenCV)
  • blur_score     → Laplacian variance
  • glare_ratio    → pixels > 240 brightness threshold
  • brightness     → grayscale mean
  • contrast       → grayscale std deviation
  • edge_density   → Canny edge detection
  • face_count     → Haar cascade face detection
      │
      ▼
Fraud Signal Scoring
  → genuine / screen / print / unknown
  → low / medium / high risk
  → confidence score
```

### Level 2 — Field Extraction
Structured fields extracted from every document:

| Field | Description |
|---|---|
| `first_name` | Given name |
| `last_name` | Surname + suffix handling |
| `dob` | Date of birth (normalized to YYYY-MM-DD) |
| `id_number` | Government ID / license number |
| `expiration` | Expiry date |
| `address` | Full address with normalization |
| `license_class` | Driver license class |
| `issuing_state` | State of issue |

### Level 3 — Cross-Document Comparison
```
Primary Document + Secondary Document
             │
             ▼
     Document Type Detection
     (id / deed / loan_application / utility_bill / unknown)
             │
             ▼
     Field-by-Field Comparison
     ┌─────────────────────────────────────┐
     │ first_name  → nickname-aware match  │
     │ last_name   → suffix-aware match    │
     │ dob         → exact match (hard)    │
     │ address     → normalized + fuzzy    │
     │ id_number   → identity doc only     │
     │ expiration  → identity doc only     │
     │ license_cls → identity doc only     │
     │ issuing_state → identity doc only   │
     └─────────────────────────────────────┘
             │
             ▼
     Verdict: strong_match / partial_match / mismatch
     Overall Match Score (0.0 – 1.0)
     Recommendation
```

### Level 4 — Compliance Flagging

| Rule | Severity | Condition |
|---|---|---|
| Expired ID | fail | Expiration date is in the past |
| Expiring Soon | warning | < 30 days to expiration |
| ID Standard Detection | fail | No government ID detected |
| Name Review | warning/fail | Name mismatch across documents |
| DOB Review | fail | DOB mismatch (hard identity flag) |
| In-State ID Requirement | fail | TX/FL property docs require in-state ID |
| ID Record Completeness | warning | ID number missing from extracted data |

---

## Cross-Document Comparison Logic

```
Name Matching
  • Exact match           → MATCH (confidence 1.0)
  • Nickname root match   → PARTIAL_MATCH (e.g. Jen = Jennifer)
  • Similarity ≥ 0.9      → PARTIAL_MATCH (OCR variation)
  • Below threshold       → MISMATCH

Address Matching
  • Normalize → strip punctuation, expand abbreviations
    (ST = STREET, AVE = AVENUE, BLVD = BOULEVARD...)
  • Same ZIP + same state + street similarity ≥ 0.88 → PARTIAL_MATCH
  • Out-of-state on property doc → MISMATCH with compliance flag
  • Overall similarity ≥ 0.7 → PARTIAL_MATCH

DOB Matching
  • Any mismatch → hard MISMATCH (fail-level compliance flag)
  • Date format normalization: MM/DD/YYYY, DD-MM-YYYY, YYYY-MM-DD all handled
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Data Models | Pydantic |
| Image Analysis | OpenCV (blur, glare, brightness, edges, face detection) |
| OCR | OCR-based text extraction and parsing |
| Document Parsing | PDF (pypdf), DOCX, JSON, CSV, HTML, XML, TXT |
| Name Matching | SequenceMatcher + nickname dictionary + suffix handling |
| Address Normalization | Custom regex + street suffix expansion |
| Compliance | Rule-based engine with NIST IAL2 and MISMO citations |
| Frontend | HTML, CSS, Vanilla JavaScript |

---

## Supported File Types

| Format | How it's processed |
|---|---|
| JPG / PNG / BMP / TIFF | OpenCV image analysis + OCR |
| PDF | pypdf text extraction |
| DOCX | XML parsing from zip archive |
| JSON | Recursive key-value walker |
| CSV | Row-by-row text extraction |
| HTML / XML | Tag stripping + text extraction |
| TXT / MD | Direct UTF-8 decode |

---

## Running Locally

```bash
# Clone
git clone https://github.com/sr2904/trustseal-ai.git
cd trustseal-ai

# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8001

# Frontend (separate terminal)
cd frontend
python3 -m http.server 8080
```

Open `http://127.0.0.1:8080` in your browser.

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check + version |
| `/api/analyze-id` | POST | Analyze a single ID image |
| `/api/analyze-document` | POST | Analyze any document format |
| `/api/compare-docs` | POST | Compare two documents field-by-field |

---

## File Structure

```
trustseal-ai/
├── backend/
│   ├── app/
│   │   ├── main.py              — FastAPI entry point, route handlers
│   │   ├── models.py            — Pydantic data models
│   │   ├── config.py            — App settings
│   │   └── services/
│   │       ├── ocr_service.py   — OCR text extraction + field parsing
│   │       ├── image_features.py — OpenCV image metric extraction
│   │       ├── document_parser.py — Multi-format document parser
│   │       ├── fraud_checks.py  — Fraud signal detection + scoring
│   │       └── cross_doc.py     — Cross-document comparison engine
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── index.html               — UI structure
│   ├── app.js                   — Frontend logic, API calls, rendering
│   └── styles.css               — Dark theme UI
└── README.md
```

---

## Demo

▶ [Watch the Demo Video](https://youtu.be/CF3Ra36zS4w)

---

## Future Work

- Multilingual OCR coverage and extraction accuracy improvements
- Advanced review dashboard for notaries and compliance teams
- Confidence scoring improvements for edge-case name variations
- Integration with e-notarization platforms
