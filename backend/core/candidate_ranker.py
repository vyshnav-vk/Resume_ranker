"""
Candidate ranking and ATS scoring pipeline.

This module can run independently while Member 1 and Member 2 are still
building their parts. It accepts either:
- a CSV file containing parsed candidate data, or
- individual resume files such as .txt, .md, .pdf, or .docx.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from backend.core.parser import parse_resume


@dataclass
class CandidateInput:
    candidate_id: str
    name: str
    resume_text: str
    skills: list[str]
    source: str = ""


@dataclass
class CandidateRanking:
    rank: int
    candidate_id: str
    name: str
    ats_score: float
    similarity_score: float
    skill_score: float
    experience_score: float
    years_of_experience: int
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: str
    source: str = ""


_YEAR_PATTERNS = [
    re.compile(r"(\d+)\+?\s*(?:-|to)?\s*\d*\s*years?\s+(?:of\s+)?experience", re.I),
    re.compile(r"(\d+)\+?\s*years?\s+(?:of\s+)?(?:relevant\s+)?(?:work\s+)?experience", re.I),
    re.compile(r"experience\s+of\s+(\d+)\+?\s*years?", re.I),
    re.compile(r"(\d+)\+?\s*yrs?", re.I),
]

_WORD_TO_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "for",
    "in",
    "is",
    "of",
    "or",
    "the",
    "to",
    "with",
}


def split_skills(value: str | Iterable[str] | None) -> list[str]:
    """Convert comma/semicolon/pipe separated skills into a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;|]", value)
    else:
        parts = list(value)
    return sorted({part.strip().lower() for part in parts if part and part.strip()})


def extract_required_skills(job_description: str, known_skills: Iterable[str]) -> list[str]:
    """
    Detect required skills from a JD using a known skills list.

    Member 2 can later replace this with their skill extraction output. Until
    then, this keeps Member 3 testable and explainable.
    """
    jd_lower = job_description.lower()
    required = []
    for skill in split_skills(known_skills):
        if re.search(rf"\b{re.escape(skill)}\b", jd_lower):
            required.append(skill)
    return sorted(set(required))


def extract_years_of_experience(text: str) -> int:
    """Return the maximum years of experience found in resume text."""
    years_found: list[int] = []
    for pattern in _YEAR_PATTERNS:
        for match in pattern.finditer(text):
            years_found.append(int(match.group(1)))

    for word, num in _WORD_TO_NUM.items():
        if re.search(rf"\b{word}\b\s*years?", text, re.I):
            years_found.append(num)

    return max(years_found, default=0)


def calculate_experience_score(years: int, required_years: int = 3) -> float:
    """Normalize experience into a 0-1 score."""
    if years <= 0:
        return 0.20
    if years < required_years:
        return 0.20 + (years / required_years) * 0.60
    bonus = min((years - required_years) / max(required_years, 1), 1.0)
    return 0.80 + bonus * 0.20


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]*", text.lower())
        if token not in _STOP_WORDS and len(token) > 1
    ]


def compute_tfidf_similarities(job_description: str, resume_texts: list[str]) -> list[float]:
    """
    Compute JD/resume similarity using a small pure-Python TF-IDF implementation.

    This avoids requiring external packages while your part is developed
    separately. It can later be replaced by embeddings or sklearn TF-IDF.
    """
    documents = [job_description] + resume_texts
    tokenized = [tokenize(document) for document in documents]
    vocabulary = sorted({token for document in tokenized for token in document})
    if not vocabulary:
        return [0.0 for _ in resume_texts]

    doc_count = len(tokenized)
    doc_freq = {
        term: sum(1 for document in tokenized if term in set(document))
        for term in vocabulary
    }
    idf = {
        term: 1.0 + (__import__("math").log((1 + doc_count) / (1 + doc_freq[term])))
        for term in vocabulary
    }

    vectors = [_tfidf_vector(document, vocabulary, idf) for document in tokenized]
    jd_vector = vectors[0]
    return [_cosine_similarity(jd_vector, vector) for vector in vectors[1:]]


def _tfidf_vector(tokens: list[str], vocabulary: list[str], idf: dict[str, float]) -> list[float]:
    counts = {token: tokens.count(token) for token in set(tokens)}
    total = len(tokens) or 1
    return [(counts.get(term, 0) / total) * idf[term] for term in vocabulary]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    import math

    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def load_candidates_from_csv(csv_path: str | Path) -> list[CandidateInput]:
    """
    Load candidate data from CSV.

    Supported columns:
    - candidate_id or id
    - name
    - resume_text or text
    - skills
    """
    path = Path(csv_path)
    candidates: list[CandidateInput] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            resume_text = row.get("resume_text") or row.get("text") or ""
            candidate_id = row.get("candidate_id") or row.get("id") or f"csv-{index}"
            name = row.get("name") or candidate_id
            candidates.append(
                CandidateInput(
                    candidate_id=candidate_id,
                    name=name,
                    resume_text=resume_text,
                    skills=split_skills(row.get("skills")),
                    source=str(path),
                )
            )
    return candidates


def load_candidates_from_resume_files(paths: Iterable[str | Path]) -> list[CandidateInput]:
    """Parse individual resume files and return candidate input records."""
    candidates: list[CandidateInput] = []
    for index, item in enumerate(paths, start=1):
        path = Path(item)
        parsed = parse_resume(path.read_bytes(), path.name, anonymize=False)
        text = parsed["clean_text"] or parsed["raw_text"]
        candidates.append(
            CandidateInput(
                candidate_id=f"file-{index}",
                name=path.stem,
                resume_text=text,
                skills=[],
                source=str(path),
            )
        )
    return candidates


def rank_candidates(
    job_description: str,
    candidates: list[CandidateInput],
    required_skills: list[str] | None = None,
    required_years: int = 3,
) -> list[CandidateRanking]:
    """
    Rank candidates using TF-IDF similarity, skill match, and experience.

    ATS score formula:
    - 50% JD/resume TF-IDF similarity
    - 30% required skill match
    - 20% experience match
    """
    if not job_description.strip():
        raise ValueError("job_description is required.")
    if not candidates:
        return []

    candidate_texts = [candidate.resume_text for candidate in candidates]
    similarities = compute_tfidf_similarities(job_description, candidate_texts)

    all_candidate_skills = [skill for c in candidates for skill in c.skills]
    detected_required_skills = required_skills or extract_required_skills(
        job_description,
        all_candidate_skills,
    )

    rankings: list[CandidateRanking] = []
    for index, candidate in enumerate(candidates):
        candidate_skills = set(split_skills(candidate.skills))
        resume_lower = candidate.resume_text.lower()

        matched_skills = []
        missing_skills = []
        for skill in detected_required_skills:
            found = skill in candidate_skills or re.search(rf"\b{re.escape(skill)}\b", resume_lower)
            if found:
                matched_skills.append(skill)
            else:
                missing_skills.append(skill)

        skill_score = (
            len(matched_skills) / len(detected_required_skills)
            if detected_required_skills
            else 0.0
        )
        years = extract_years_of_experience(candidate.resume_text)
        exp_score = calculate_experience_score(years, required_years)
        similarity = min(max(similarities[index], 0.0), 1.0)

        ats_score = round(
            ((0.50 * similarity) + (0.30 * skill_score) + (0.20 * exp_score)) * 100,
            2,
        )

        explanation = build_score_explanation(
            ats_score=ats_score,
            similarity=similarity,
            skill_score=skill_score,
            exp_score=exp_score,
            years=years,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
        )

        rankings.append(
            CandidateRanking(
                rank=0,
                candidate_id=candidate.candidate_id,
                name=candidate.name,
                ats_score=ats_score,
                similarity_score=round(similarity, 4),
                skill_score=round(skill_score, 4),
                experience_score=round(exp_score, 4),
                years_of_experience=years,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                explanation=explanation,
                source=candidate.source,
            )
        )

    rankings.sort(key=lambda item: item.ats_score, reverse=True)
    for rank, item in enumerate(rankings, start=1):
        item.rank = rank
    return rankings


def build_score_explanation(
    ats_score: float,
    similarity: float,
    skill_score: float,
    exp_score: float,
    years: int,
    matched_skills: list[str],
    missing_skills: list[str],
) -> str:
    matched = ", ".join(matched_skills) if matched_skills else "none"
    missing = ", ".join(missing_skills) if missing_skills else "none"
    return (
        f"ATS score {ats_score}%: JD similarity {similarity:.1%}, "
        f"skill match {skill_score:.1%}, experience match {exp_score:.1%} "
        f"({years} years detected). Matched skills: {matched}. "
        f"Missing skills: {missing}."
    )


def rankings_to_dict(rankings: list[CandidateRanking]) -> list[dict]:
    return [asdict(ranking) for ranking in rankings]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Member 3 candidate ranking.")
    parser.add_argument("--jd", help="Job description text.")
    parser.add_argument("--jd-file", help="Text file containing the current job description.")
    parser.add_argument("--csv", help="CSV file with candidate data.")
    parser.add_argument("--resumes", nargs="*", help="Individual resume files.")
    parser.add_argument("--required-skills", default="", help="Comma separated required skills.")
    parser.add_argument("--required-years", type=int, default=3)
    args = parser.parse_args()

    if args.jd_file:
        job_description = Path(args.jd_file).read_text(encoding="utf-8")
    else:
        job_description = args.jd or ""

    candidates: list[CandidateInput] = []
    if args.csv:
        candidates.extend(load_candidates_from_csv(args.csv))
    if args.resumes:
        candidates.extend(load_candidates_from_resume_files(args.resumes))

    required_skills = split_skills(args.required_skills)
    rankings = rank_candidates(
        job_description=job_description,
        candidates=candidates,
        required_skills=required_skills or None,
        required_years=args.required_years,
    )
    print(json.dumps(rankings_to_dict(rankings), indent=2))


if __name__ == "__main__":
    main()
