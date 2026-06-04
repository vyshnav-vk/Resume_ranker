"""
Ingestion & Extraction Layer
============================
Handles PDF (text + OCR), DOCX, and plain-text resumes.
Includes cleaning, normalisation, and spaCy-based anonymisation.
"""

from __future__ import annotations

import io
import re
import unicodedata
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

# ── Optional heavy imports (graceful degradation) ─────────────────────────────
try:
    import pdfplumber
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False
    logger.warning("pdfplumber not installed. PDF parsing disabled.")

try:
    from docx import Document as DocxDocument
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False
    logger.warning("python-docx not installed. DOCX parsing disabled.")

try:
    import pytesseract
    from PIL import Image
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False
    logger.warning("pytesseract / Pillow not installed. OCR disabled.")

try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    _SPACY_AVAILABLE = True
except Exception:
    _nlp = None
    _SPACY_AVAILABLE = False
    logger.warning("spaCy en_core_web_sm not available. Anonymisation disabled.")


# ── Normalisation ─────────────────────────────────────────────────────────────
_BULLET_RE   = re.compile(r"^[\u2022\u2023\u25E6\u2043\u2219•▪▸►✓✔·∙◦‣⁃]+\s*", re.M)
_MULTI_WS    = re.compile(r"[ \t]{2,}")
_MULTI_NL    = re.compile(r"\n{3,}")
_NON_ASCII   = re.compile(r"[^\x00-\x7F]+")

def normalize_text(text: str) -> str:
    """Lowercase, remove non-ASCII, standardise bullets and whitespace."""
    # Unicode normalisation
    text = unicodedata.normalize("NFKD", text)
    # Replace curly quotes, dashes
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    # Standardise bullet points → plain "-"
    text = _BULLET_RE.sub("- ", text)
    text = _NON_ASCII.sub(" ", text)
    text = text.lower()
    text = _MULTI_WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


# ── Anonymiser ────────────────────────────────────────────────────────────────
_EMAIL_RE  = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", re.I)
_PHONE_RE  = re.compile(r"(\+?\d[\d\s\-().]{7,}\d)")
_URL_RE    = re.compile(r"https?://\S+|www\.\S+", re.I)
_ADDRESS_RE= re.compile(
    r"\d{1,5}\s[\w\s]{1,30}(?:street|st|avenue|ave|road|rd|lane|ln|blvd|drive|dr)\b",
    re.I,
)

def anonymize_text(text: str) -> str:
    """
    Remove PII using regex + spaCy NER.
    Replaces: names, email, phone, URL, addresses with placeholders.
    """
    # Regex-based removal (fast)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _URL_RE.sub("[URL]", text)
    text = _ADDRESS_RE.sub("[ADDRESS]", text)

    # spaCy NER (names, locations, organisations used as names)
    if _SPACY_AVAILABLE and _nlp:
        doc = _nlp(text[:100_000])          # cap at 100k chars for performance
        replacements: list[tuple[int, int, str]] = []
        for ent in doc.ents:
            if ent.label_ in {"PERSON", "GPE"}:
                replacements.append((ent.start_char, ent.end_char, f"[{ent.label_}]"))
        # Apply in reverse to preserve offsets
        for start, end, label in sorted(replacements, reverse=True):
            text = text[:start] + label + text[end:]

    return text


# ── PDF Parser ────────────────────────────────────────────────────────────────
def _parse_pdf(file_bytes: bytes) -> str:
    if not _PDF_AVAILABLE:
        raise RuntimeError("pdfplumber is required for PDF parsing.")

    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages):
            page_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            if page_text.strip():
                text_parts.append(page_text)
            elif _OCR_AVAILABLE:
                # Fallback: render page as image → OCR
                logger.info("Page %d has no text layer — running OCR …", page_num + 1)
                pil_image = page.to_image(resolution=200).original
                ocr_text  = pytesseract.image_to_string(pil_image)
                text_parts.append(ocr_text)
            else:
                logger.warning(
                    "Page %d appears to be image-only but OCR is not available.", page_num + 1
                )

    return "\n".join(text_parts)


# ── DOCX Parser ───────────────────────────────────────────────────────────────
def _parse_docx(file_bytes: bytes) -> str:
    if not _DOCX_AVAILABLE:
        raise RuntimeError("python-docx is required for DOCX parsing.")

    doc = DocxDocument(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

    # Also extract text from tables
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                paragraphs.append(row_text)

    return "\n".join(paragraphs)


# ── Dispatcher ────────────────────────────────────────────────────────────────
def parse_resume(
    file_bytes: bytes,
    filename: str,
    anonymize: bool = True,
) -> dict:
    """
    Parse any supported resume file.

    Returns
    -------
    {
        "filename": str,
        "raw_text": str,       # before normalisation/anonymisation
        "clean_text": str,     # ready for NLP
        "word_count": int,
        "parse_error": str | None,
    }
    """
    ext = Path(filename).suffix.lower()
    raw_text = ""
    error: str | None = None

    try:
        if ext == ".pdf":
            raw_text = _parse_pdf(file_bytes)
        elif ext in {".docx", ".doc"}:
            raw_text = _parse_docx(file_bytes)
        elif ext in {".txt", ".md"}:
            raw_text = file_bytes.decode("utf-8", errors="replace")
        else:
            raise ValueError(f"Unsupported file type: {ext!r}")
    except Exception as exc:
        error = str(exc)
        logger.error("Failed to parse %s: %s", filename, exc)

    clean = normalize_text(raw_text)
    if anonymize and clean:
        clean = anonymize_text(clean)

    return {
        "filename": filename,
        "raw_text": raw_text,
        "clean_text": clean,
        "word_count": len(clean.split()),
        "parse_error": error,
    }


# ── Batch helper ──────────────────────────────────────────────────────────────
def parse_resume_batch(
    files: list[tuple[bytes, str]],   # [(bytes, filename), …]
    anonymize: bool = True,
) -> list[dict]:
    """Parse multiple resumes; skip files with errors."""
    results = []
    for file_bytes, filename in files:
        parsed = parse_resume(file_bytes, filename, anonymize=anonymize)
        if parsed["parse_error"]:
            logger.error("Skipping %s due to parse error.", filename)
        results.append(parsed)
    return results
