# Resume Ranker Pro — Production-Grade Resume Ranking System

## Architecture

```
resume_ranker/
├── backend/
│   ├── api/
│   │   └── main.py              # FastAPI endpoints
│   └── core/
│       ├── parser.py            # Multi-format ingestion + anonymisation
│       ├── scoring_engine.py    # Hybrid SBERT + TF-IDF + Experience scorer
│       └── classifier.py        # Role classifier (no-JD branch)
├── frontend/
│   └── dashboard.py             # Streamlit recruiter dashboard
├── tests/
│   └── test_scoring.py          # Pytest unit tests
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
└── requirements.txt
```

## Scoring Formula

```
Score (1–10) = (0.50 × Semantic Embedding)
             + (0.30 × Keyword Match)
             + (0.20 × Experience Factor)
```

| Component | Method | Why |
|-----------|--------|-----|
| Semantic | SBERT `all-mpnet-base-v2` cosine similarity | Understands context, immune to keyword stuffing |
| Keyword | TF-IDF bigram overlap | Ensures "must-have" terms (AWS, Java) are present |
| Experience | Regex year extraction → normalised curve | Penalises junior/senior mismatches |

## Quickstart (Local)

```bash
# 1. Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 2. Start API
uvicorn backend.api.main:app --reload --port 8000

# 3. Start Dashboard (new terminal)
streamlit run frontend/dashboard.py

# 4. Run tests
pytest tests/ -v
```

## Quickstart (Docker)

```bash
cd docker
docker compose up --build
# API  → http://localhost:8000/docs
# UI   → http://localhost:8501
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/rank` | Upload resumes + JD, returns ranked list |
| `GET`  | `/api/roles` | List of standard roles |
| `GET`  | `/api/health` | Health check |

### POST /api/rank — Form Fields

| Field | Type | Description |
|-------|------|-------------|
| `files` | File[] | Resume files (PDF/DOCX/TXT) |
| `jd_text` | str (optional) | Job description text |
| `job_title` | str (optional) | Display label |
| `required_years` | int | Seniority threshold (default 3) |
| `anonymize` | bool | Strip PII before scoring (default true) |

## Key Design Decisions

- **Anonymisation first**: spaCy NER removes names/locations before any score is computed — eliminating bias.
- **Classifier fallback**: When no JD is provided, a TF-IDF + Random Forest model predicts the candidate's role and generates a synthetic JD, keeping the scoring pipeline unified.
- **SBERT beats keyword stuffing**: Because sentence embeddings capture semantic context, a resume with "Python" repeated 100 times scores no differently than one with it mentioned once naturally.
- **Experience curve**: Non-linear — under-qualified candidates are penalised, over-qualified ones are mildly boosted (not penalised).
- **FAISS-ready**: The vector embeddings from `score_resumes` can be stored in FAISS to allow JD hot-swapping without re-parsing all resumes.

Project Workflow:
Layer 1 — Ingestion & Extraction
Resumes are uploaded in any format (PDF, DOCX, image-only PDF, TXT). Each file goes through the multi-format parser, then a normaliser (lowercasing, bullet cleanup, non-ASCII removal), and finally the spaCy anonymiser which strips names, emails, phone numbers, and addresses before any scoring happens — eliminating bias.
Layer 2 — Hybrid NLP Core
The system branches based on whether a Job Description is provided. If yes, SBERT encodes both the JD and resumes into vector embeddings stored in FAISS. If no JD is provided, a TF-IDF + Random Forest classifier predicts the candidate's most likely role and auto-generates a synthetic JD — keeping the scoring pipeline unified regardless of the branch.
Layer 3 — Scoring Engine
Each resume receives three sub-scores that are combined into a single 1–10 rating: semantic similarity (50%, SBERT cosine similarity capturing context), keyword match (30%, TF-IDF bigram overlap ensuring must-have terms are present), and experience factor (20%, regex-extracted years of experience mapped to a normalised curve).
Layer 4 — Dashboard
Results are served via FastAPI and rendered in a Streamlit dashboard showing a ranked leaderboard, a radar chart for skill-gap analysis, an explainability panel explaining why each candidate scored as they did, and a CSV export for the recruiter to download.
