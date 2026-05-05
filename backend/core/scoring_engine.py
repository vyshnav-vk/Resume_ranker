"""
Hybrid Scoring Engine
=====================
Combines SBERT semantic embeddings + TF-IDF keyword match + Experience factor
to produce a final 1-10 score for each resume.

Score = (0.50 × Semantic) + (0.30 × Keyword) + (0.20 × Experience)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# ── Model singleton (loaded once per worker) ──────────────────────────────────
_SBERT_MODEL: Optional[SentenceTransformer] = None

def get_sbert_model() -> SentenceTransformer:
    global _SBERT_MODEL
    if _SBERT_MODEL is None:
        logger.info("Loading SBERT model: all-mpnet-base-v2 ...")
        _SBERT_MODEL = SentenceTransformer("all-mpnet-base-v2")
    return _SBERT_MODEL


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class ResumeScore:
    """Full scoring breakdown for one resume."""
    candidate_id: str
    raw_text: str

    semantic_score: float = 0.0        # 0-1  (cosine similarity)
    keyword_score:  float = 0.0        # 0-1  (TF-IDF overlap)
    experience_score: float = 0.0      # 0-1  (normalised years)

    final_score: float = 0.0           # 1-10 weighted composite
    matched_keywords: list[str] = field(default_factory=list)
    years_of_experience: int = 0
    predicted_role: Optional[str] = None
    explanation: str = ""


# ── Experience Extractor ──────────────────────────────────────────────────────
# Patterns: "5 years", "5+ years", "five years", "2-3 years experience"
_YEAR_PATTERNS = [
    re.compile(r"(\d+)\+?\s*(?:–|-|to)?\s*\d*\s*years?\s+(?:of\s+)?experience", re.I),
    re.compile(r"(\d+)\+?\s*years?\s+(?:of\s+)?(?:relevant\s+)?(?:work\s+)?experience", re.I),
    re.compile(r"experience\s+of\s+(\d+)\+?\s*years?", re.I),
    re.compile(r"(\d+)\+?\s*yrs?", re.I),
]

_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

def extract_years_of_experience(text: str) -> int:
    """Return the maximum number of years found in the text."""
    years_found = []
    for pattern in _YEAR_PATTERNS:
        for match in pattern.finditer(text):
            try:
                years_found.append(int(match.group(1)))
            except (IndexError, ValueError):
                pass

    # Word-based fallback ("five years")
    for word, num in _WORD_TO_NUM.items():
        if re.search(rf"\b{word}\b\s*years?", text, re.I):
            years_found.append(num)

    return max(years_found, default=0)


def experience_score(years: int, required_years: int = 3) -> float:
    """
    Normalise experience to [0, 1].
    - Below required: linear penalty (0 → 0.4)
    - At required: 0.8
    - Exceeds (up to 2×): bonus up to 1.0
    """
    if years <= 0:
        return 0.20
    if years < required_years:
        return 0.20 + (years / required_years) * 0.60
    bonus = min((years - required_years) / max(required_years, 1), 1.0)
    return 0.80 + bonus * 0.20


# ── Keyword Extractor ─────────────────────────────────────────────────────────
def extract_keywords_tfidf(
    jd_text: str,
    resume_texts: list[str],
    top_n: int = 30,
) -> tuple[list[str], np.ndarray]:
    """
    Fit TF-IDF on JD + resumes; return top-N JD keywords and
    per-resume scores (cosine similarity in TF-IDF space).
    """
    corpus = [jd_text] + resume_texts
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=5000,
        stop_words="english",
        sublinear_tf=True,
    )
    tfidf_matrix = vectorizer.fit_transform(corpus)

    jd_vec = tfidf_matrix[0]
    resume_vecs = tfidf_matrix[1:]

    # Top-N keywords from JD
    feature_names = vectorizer.get_feature_names_out()
    jd_scores = jd_vec.toarray().flatten()
    top_indices = jd_scores.argsort()[-top_n:][::-1]
    jd_keywords = [feature_names[i] for i in top_indices if jd_scores[i] > 0]

    # Per-resume cosine similarity in TF-IDF space
    keyword_sims = cosine_similarity(jd_vec, resume_vecs).flatten()
    return jd_keywords, keyword_sims


def find_matched_keywords(resume_text: str, keywords: list[str]) -> list[str]:
    """Return keywords that appear in the resume (word-boundary match)."""
    resume_lower = resume_text.lower()
    return [kw for kw in keywords if re.search(rf"\b{re.escape(kw)}\b", resume_lower)]


# ── Semantic Scorer ───────────────────────────────────────────────────────────
def compute_semantic_scores(jd_text: str, resume_texts: list[str]) -> np.ndarray:
    """Batch-encode JD and resumes; return cosine similarities."""
    model = get_sbert_model()
    texts = [jd_text] + resume_texts
    embeddings = model.encode(texts, batch_size=16, show_progress_bar=False, normalize_embeddings=True)
    jd_emb = embeddings[0]
    resume_embs = embeddings[1:]
    # Dot product == cosine sim when normalised
    return np.dot(resume_embs, jd_emb)


# ── Composite Scorer (main public API) ────────────────────────────────────────
WEIGHTS = {"semantic": 0.50, "keyword": 0.30, "experience": 0.20}


def scale_to_10(value: float) -> float:
    """Map [0, 1] → [1, 10], rounded to 2 dp."""
    return round(1.0 + value * 9.0, 2)


def score_resumes(
    jd_text: str,
    resumes: list[dict],          # [{"id": str, "text": str}, ...]
    required_years: int = 3,
    top_keywords: int = 30,
    weights: Optional[dict] = None,
) -> list[ResumeScore]:
    """
    Score a batch of resumes against a job description.

    Parameters
    ----------
    jd_text        : Cleaned job-description text.
    resumes        : List of dicts with keys 'id' and 'text'.
    required_years : Seniority threshold for the experience factor.
    top_keywords   : How many TF-IDF keywords to extract from the JD.
    weights        : Override default WEIGHTS dict (must sum to 1.0).

    Returns
    -------
    List of ResumeScore objects, sorted by final_score descending.
    """
    if not resumes:
        return []

    w = weights or WEIGHTS
    assert abs(sum(w.values()) - 1.0) < 1e-6, "Weights must sum to 1.0"

    texts = [r["text"] for r in resumes]

    # ── 1. Semantic similarity ────────────────────────────────────────────────
    logger.info("Computing semantic embeddings for %d resumes …", len(texts))
    semantic_sims = compute_semantic_scores(jd_text, texts)          # shape (N,)

    # ── 2. TF-IDF keyword match ───────────────────────────────────────────────
    logger.info("Computing TF-IDF keyword scores …")
    jd_keywords, keyword_sims = extract_keywords_tfidf(jd_text, texts, top_n=top_keywords)

    # ── 3. Experience extraction ──────────────────────────────────────────────
    results: list[ResumeScore] = []
    for i, resume in enumerate(resumes):
        years = extract_years_of_experience(resume["text"])
        exp_sc = experience_score(years, required_years)

        # Weighted composite
        raw_score = (
            w["semantic"]   * float(np.clip(semantic_sims[i], 0, 1))
            + w["keyword"]  * float(np.clip(keyword_sims[i], 0, 1))
            + w["experience"] * exp_sc
        )
        final = scale_to_10(raw_score)

        matched = find_matched_keywords(resume["text"], jd_keywords)

        explanation = _build_explanation(
            semantic=float(semantic_sims[i]),
            keyword=float(keyword_sims[i]),
            exp_sc=exp_sc,
            years=years,
            matched=matched,
            final=final,
        )

        results.append(ResumeScore(
            candidate_id=resume["id"],
            raw_text=resume["text"],
            semantic_score=round(float(semantic_sims[i]), 4),
            keyword_score=round(float(keyword_sims[i]), 4),
            experience_score=round(exp_sc, 4),
            final_score=final,
            matched_keywords=matched,
            years_of_experience=years,
            explanation=explanation,
        ))

    results.sort(key=lambda r: r.final_score, reverse=True)
    logger.info("Scoring complete. Top score: %.2f", results[0].final_score if results else 0)
    return results


def _build_explanation(
    semantic: float, keyword: float, exp_sc: float,
    years: int, matched: list[str], final: float,
) -> str:
    parts = [
        f"Final Score: {final}/10",
        f"• Semantic Alignment : {semantic:.1%}  (SBERT cosine similarity)",
        f"• Keyword Match      : {keyword:.1%}  (TF-IDF overlap)",
        f"• Experience Factor  : {exp_sc:.1%}  ({years} yrs detected)",
        f"• Matched Keywords   : {', '.join(matched[:10]) or 'None'}",
    ]
    return "\n".join(parts)
