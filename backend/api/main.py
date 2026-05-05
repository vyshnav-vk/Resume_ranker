"""
FastAPI — Resume Ranker API
============================
Endpoints:
  POST /api/rank      → Score resumes against a JD (or classify if no JD)
  GET  /api/health    → Health check
  GET  /api/roles     → Available standard roles
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.parser import parse_resume_batch
from backend.core.scoring_engine import score_resumes, ResumeScore
from backend.core.classifier import RoleClassifier, generate_synthetic_jd, ROLE_CORPUS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Resume Ranker API",
    version="1.0.0",
    description="Production-grade hybrid NLP resume scoring system.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic response models ──────────────────────────────────────────────────
class CandidateResult(BaseModel):
    rank: int
    candidate_id: str
    filename: str
    final_score: float
    semantic_score: float
    keyword_score: float
    experience_score: float
    years_of_experience: int
    predicted_role: Optional[str]
    matched_keywords: list[str]
    explanation: str


class RankResponse(BaseModel):
    job_title:    Optional[str]
    jd_mode:      str            # "provided" | "classifier"
    total_resumes: int
    ranked:        list[CandidateResult]


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/roles")
def get_roles():
    return {"roles": list(ROLE_CORPUS.keys())}


@app.post("/api/rank", response_model=RankResponse)
async def rank_resumes(
    files:          list[UploadFile] = File(...),
    jd_text:        Optional[str]    = Form(None),
    job_title:      Optional[str]    = Form(None),
    required_years: int              = Form(3),
    anonymize:      bool             = Form(True),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    # ── 1. Parse ───────────────────────────────────────────────────────────
    raw_files = [(await f.read(), f.filename or "unknown") for f in files]
    parsed    = parse_resume_batch(raw_files, anonymize=anonymize)
    valid     = [p for p in parsed if not p["parse_error"] and p["clean_text"]]

    if not valid:
        raise HTTPException(status_code=422, detail="Could not extract text from any uploaded file.")

    # ── 2. Determine JD mode ───────────────────────────────────────────────
    jd_mode      = "provided"
    classifier   = None
    role_preds: dict[str, dict] = {}

    if not jd_text or not jd_text.strip():
        jd_mode    = "classifier"
        classifier = RoleClassifier()
        # Predict role per resume
        for p in valid:
            pred = classifier.predict(p["clean_text"])
            role_preds[p["filename"]] = pred

        # Use most common predicted role to build a synthetic JD
        from collections import Counter
        top_role = Counter(v["predicted_role"] for v in role_preds.values()).most_common(1)[0][0]
        jd_text  = generate_synthetic_jd(top_role)
        logger.info("No JD provided. Predicted role: %s. Synthetic JD generated.", top_role)

    # ── 3. Score ───────────────────────────────────────────────────────────
    resume_inputs = [
        {"id": str(uuid.uuid4()), "text": p["clean_text"], "filename": p["filename"]}
        for p in valid
    ]

    scored: list[ResumeScore] = score_resumes(
        jd_text        = jd_text,
        resumes        = [{"id": r["id"], "text": r["text"]} for r in resume_inputs],
        required_years = required_years,
    )

    # Build id → filename map
    id_to_filename = {r["id"]: r["filename"] for r in resume_inputs}

    # ── 4. Format response ─────────────────────────────────────────────────
    ranked_results = []
    for rank, score in enumerate(scored, start=1):
        filename = id_to_filename.get(score.candidate_id, "unknown")
        pred_role = (
            role_preds.get(filename, {}).get("predicted_role")
            if jd_mode == "classifier"
            else job_title
        )
        ranked_results.append(CandidateResult(
            rank               = rank,
            candidate_id       = score.candidate_id,
            filename           = filename,
            final_score        = score.final_score,
            semantic_score     = score.semantic_score,
            keyword_score      = score.keyword_score,
            experience_score   = score.experience_score,
            years_of_experience= score.years_of_experience,
            predicted_role     = pred_role,
            matched_keywords   = score.matched_keywords[:15],
            explanation        = score.explanation,
        ))

    return RankResponse(
        job_title      = job_title,
        jd_mode        = jd_mode,
        total_resumes  = len(valid),
        ranked         = ranked_results,
    )
