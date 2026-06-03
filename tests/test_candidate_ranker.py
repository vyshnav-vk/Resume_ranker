from backend.core.candidate_ranker import (
    CandidateInput,
    load_candidates_from_csv,
    rank_candidates,
    split_skills,
)


def test_split_skills_accepts_common_separators():
    assert split_skills("Python, SQL; Flask|NLP") == ["flask", "nlp", "python", "sql"]


def test_load_candidates_from_csv():
    candidates = load_candidates_from_csv("sample_data/candidates.csv")
    assert len(candidates) == 3
    assert candidates[0].candidate_id == "cand-001"
    assert "python" in candidates[0].skills


def test_rank_candidates_orders_best_match_first():
    jd = (
        "Need Python NLP developer with machine learning, SQL, Flask, "
        "REST APIs and 3 years of experience."
    )
    candidates = [
        CandidateInput(
            candidate_id="good",
            name="Good Match",
            resume_text="Python NLP developer with 4 years of experience, SQL, Flask and REST APIs.",
            skills=["Python", "NLP", "SQL", "Flask", "REST APIs"],
        ),
        CandidateInput(
            candidate_id="weak",
            name="Weak Match",
            resume_text="React developer with 1 year of experience in HTML and CSS.",
            skills=["React", "HTML", "CSS"],
        ),
    ]

    ranked = rank_candidates(jd, candidates, required_skills=["python", "nlp", "sql", "flask"])

    assert ranked[0].candidate_id == "good"
    assert ranked[0].rank == 1
    assert ranked[0].ats_score > ranked[1].ats_score
    assert "python" in ranked[0].matched_skills
    assert "flask" in ranked[1].missing_skills
