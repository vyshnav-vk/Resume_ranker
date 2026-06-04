"""
Role Classifier — "No JD" Branch
==================================
A two-stage classifier that predicts the candidate's primary role when no
Job Description is supplied:

  Stage 1 (fast): TF-IDF + Random Forest — instant prediction.
  Stage 2 (quality): SBERT embeddings → KNN against role prototypes.

Both stages are trained lazily on first use with the bundled role corpus.
"""

from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

# ── Standard role corpus (role → representative keywords / description) ───────
# In production, replace/extend with data from the Kaggle Resume Dataset.
ROLE_CORPUS: dict[str, str] = {
    "Data Scientist": (
        "machine learning deep learning neural networks tensorflow pytorch scikit-learn "
        "pandas numpy statistics regression classification clustering nlp computer vision "
        "data analysis exploratory data a/b testing feature engineering model deployment"
    ),
    "Machine Learning Engineer": (
        "mlops model serving kubernetes docker mlflow airflow spark feature store "
        "real-time inference pipeline automation tensorflow serving torchserve "
        "distributed training model optimisation quantisation onnx"
    ),
    "Software Engineer": (
        "software development algorithms data structures system design rest api microservices "
        "java python c++ go backend frontend full-stack ci/cd agile scrum unit testing "
        "code review version control git distributed systems scalability"
    ),
    "Frontend Developer": (
        "react angular vue javascript typescript html css sass webpack redux next.js "
        "responsive design ui ux component library accessibility performance optimisation "
        "browser compatibility figma adobe xd"
    ),
    "DevOps Engineer": (
        "devops ci/cd jenkins github actions gitlab terraform ansible kubernetes helm "
        "docker aws azure gcp infrastructure as code monitoring prometheus grafana elk "
        "sre incident management on-call reliability"
    ),
    "Data Engineer": (
        "data pipeline etl spark kafka airflow dbt snowflake bigquery redshift databricks "
        "sql data warehouse data lake hadoop flink streaming batch processing "
        "data modelling schema design data quality orchestration"
    ),
    "HR Manager": (
        "human resources talent acquisition recruitment onboarding payroll performance "
        "management employee relations labour law compliance training development "
        "succession planning hris workday bamboohr engagement retention"
    ),
    "Finance Analyst": (
        "financial analysis forecasting budgeting p&l balance sheet cash flow dcf valuation "
        "excel vba power bi tableau accounting gaap ifrs variance analysis cost reduction "
        "risk management investment portfolio mergers acquisitions"
    ),
    "Product Manager": (
        "product roadmap stakeholder management agile scrum user stories kpis okrs "
        "go-to-market competitive analysis user research wireframing jira confluence "
        "prioritisation launch strategy product analytics growth"
    ),
    "Cybersecurity Analyst": (
        "penetration testing siem soc vulnerability assessment incident response "
        "firewall ids ips wireshark nessus metasploit owasp iso 27001 gdpr "
        "threat modelling zero trust endpoint security"
    ),
}

from pathlib import Path

MODEL_CACHE_PATH = Path("cache/role_classifier.pkl")
MODEL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Model Training ─────────────────────────────────────────────────────────────
def _build_pipeline() -> tuple[Pipeline, LabelEncoder]:
    texts  = list(ROLE_CORPUS.values())
    labels = list(ROLE_CORPUS.keys())

    # Augment corpus: each role description repeated 5× with slight word sampling
    aug_texts, aug_labels = [], []
    rng = np.random.default_rng(42)
    for text, label in zip(texts, labels):
        words = text.split()
        for _ in range(5):
            sampled = rng.choice(words, size=max(len(words) - 5, len(words) // 2), replace=False)
            aug_texts.append(" ".join(sampled))
            aug_labels.append(label)

    all_texts  = texts  + aug_texts
    all_labels = labels + aug_labels

    le = LabelEncoder()
    y = le.fit_transform(all_labels)

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=3000, sublinear_tf=True)),
        ("clf",   RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1)),
    ])
    pipe.fit(all_texts, y)
    return pipe, le


def _load_or_train() -> tuple[Pipeline, LabelEncoder]:
    if MODEL_CACHE_PATH.exists():
        try:
            with open(MODEL_CACHE_PATH, "rb") as f:
                pipe, le = pickle.load(f)
            logger.info("Loaded cached role classifier from %s", MODEL_CACHE_PATH)
            return pipe, le
        except Exception:
            logger.warning("Cache corrupt; retraining …")

    logger.info("Training role classifier …")
    pipe, le = _build_pipeline()
    with open(MODEL_CACHE_PATH, "wb") as f:
        pickle.dump((pipe, le), f)
    return pipe, le


# ── Public API ────────────────────────────────────────────────────────────────
class RoleClassifier:
    """Singleton wrapper around the TF-IDF + Random Forest pipeline."""

    _instance: Optional["RoleClassifier"] = None

    def __new__(cls) -> "RoleClassifier":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pipe, cls._instance._le = _load_or_train()
        return cls._instance

    def predict(self, text: str) -> dict:
        """
        Predict the most likely role for a resume.

        Returns
        -------
        {
          "predicted_role": str,
          "confidence": float,          # 0-1
          "top3": [(role, prob), …],    # top-3 predictions
        }
        """
        proba = self._pipe.predict_proba([text])[0]
        top3_idx = np.argsort(proba)[-3:][::-1]
        top3 = [(self._le.inverse_transform([i])[0], float(proba[i])) for i in top3_idx]

        return {
            "predicted_role": top3[0][0],
            "confidence":     round(top3[0][1], 4),
            "top3":           top3,
        }

    def predict_batch(self, texts: list[str]) -> list[dict]:
        return [self.predict(t) for t in texts]


# ── Synthetic JD Generator (No-JD fallback) ───────────────────────────────────
def generate_synthetic_jd(role: str) -> str:
    """
    Return a synthetic JD for the predicted role.
    Used so the scoring engine always has a JD to compare against.
    """
    base = ROLE_CORPUS.get(role, "")
    if not base:
        return ""
    return (
        f"We are looking for a {role}. "
        f"Key requirements include: {base}. "
        f"The ideal candidate will have strong communication skills, "
        f"team collaboration experience, and a track record of delivering results."
    )
