# Ingestion API

FastAPI service for transaction and loan-application ingestion with GCS storage, Pub/Sub emission, and (GAP-17) PDF document OCR processing.

---

## System Dependencies

### Document OCR Pipeline (GAP-17)

The OCR pipeline requires two system binaries that are **not** installed by `pip`:

| Dependency | Purpose | Install |
|------------|---------|---------|
| `tesseract-ocr` | OCR engine for scanned PDFs | See below |
| `poppler-utils` | PDF → image rasterisation (`pdf2image`) | See below |

**macOS:**
```bash
brew install tesseract poppler
```

**Debian / Ubuntu (Docker):**
```bash
apt-get install -y tesseract-ocr poppler-utils
```

If `tesseract` is not installed, the pipeline gracefully falls back to `pdfminer.six` for digital (text-layer) PDFs.  Scanned PDFs will log a `TesseractNotAvailableError` and return an empty `raw_text` with that error recorded in the `errors` list of the `DocumentExtractionResult`.

---

## Python Dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GCS_RAW_BUCKET` | `risk-raw-data` | GCS bucket for raw uploads |
| `PUBSUB_TOPIC` | `projects/…/topics/ingestion-events` | Pub/Sub topic |
| `DOCUMENT_EVENTS_TOPIC` | `document-extraction-results` | Pub/Sub topic for OCR results |
| `OCR_DPI` | `300` | Rasterisation DPI for pdf2image |
| `OCR_LANG` | `eng` | Tesseract language pack |
| `MAX_UPLOAD_SIZE_MB` | `20` | Maximum PDF upload size |

---

## Running Tests

```bash
cd ingestion-api
pytest tests/ -v
```
