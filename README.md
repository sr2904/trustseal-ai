# CareCaller Full Stack

CareCaller is a healthcare voice triage demo built for hackathon judging. The default package is set up to be stable first:

- Deepgram handles speech-to-text
- audio cleaning reduces background noise and trims silence
- medical normalization and extraction happen in the backend
- Gemini extraction is included as an optional layer but is disabled by default

## Run

### Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8001
```

### Frontend
```bash
cd frontend
python3 -m http.server 8080
```

Open `http://127.0.0.1:8080`.

## Required key

For the stable version, only this is required in `backend/.env`:

```env
DEEPGRAM_API_KEY=your_key_here
```

Gemini is optional and disabled by default.

## Common Voice accent benchmarking

Use Mozilla Common Voice to test accent robustness, not to fully retrain the model.

1. Download Common Voice and locate:
   - `validated.tsv`
   - the `clips/` directory
2. Create a CareCaller manifest:

```bash
cd backend
.venv/bin/python scripts/prepare_common_voice_manifest.py \
  /path/to/validated.tsv \
  /path/to/clips \
  benchmarks/common_voice_manifest.jsonl \
  --limit 25
```

You can optionally filter by accent:

```bash
.venv/bin/python scripts/prepare_common_voice_manifest.py \
  /path/to/validated.tsv \
  /path/to/clips \
  benchmarks/common_voice_indian.jsonl \
  --limit 25 \
  --accent indian
```

3. Evaluate the STT pipeline:

```bash
.venv/bin/python scripts/evaluate_benchmarks.py benchmarks/common_voice_manifest.jsonl
```

The benchmark reports:
- WER
- CER
- numeric accuracy
- keyword accuracy
- numeric confusion accuracy

## What was added

- `backend/app/audio_cleaner.py` for normalization, silence trimming, and optional denoise
- `backend/scripts/prepare_common_voice_manifest.py` to convert Common Voice rows into a benchmark manifest
- safe default config with Gemini disabled

## Demo framing

Use the app to show:
- real audio upload or microphone recording
- cleaned transcript
- extracted clinical entities
- urgency routing

Then mention that Common Voice was used to benchmark accent robustness.
