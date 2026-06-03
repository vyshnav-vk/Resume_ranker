# Candidate Ranking Sample Inputs

This folder lets the ranking/ATS module run before parsing, upload, and dashboard features are finished.

## CSV input

Use `candidates.csv` when Member 2 gives parsed candidate data in a table.

Required columns:

- `candidate_id`
- `name`
- `resume_text`
- `skills`

Example command:

```bash
python -m backend.core.candidate_ranker --jd "Need Python NLP developer with machine learning SQL Flask REST APIs and 3 years experience" --csv sample_data/candidates.csv --required-skills "Python,NLP,Machine Learning,SQL,Flask,REST APIs" --required-years 3
```

If the job description changes every time, pass the new JD each run:

```bash
python -m backend.core.candidate_ranker --jd-file sample_data/job_description.txt --csv sample_data/candidates.csv --required-skills "Python,NLP,Machine Learning,SQL,Flask,REST APIs" --required-years 3
```

## Individual resume input

Use files in `sample_data/resumes` when resumes are uploaded one by one.

Example command:

```bash
python -m backend.core.candidate_ranker --jd "Need Python NLP developer with machine learning SQL Flask REST APIs and 3 years experience" --resumes sample_data/resumes/asha_nair.txt sample_data/resumes/rahul_mehta.txt sample_data/resumes/neha_sharma.txt --required-skills "Python,NLP,Machine Learning,SQL,Flask,REST APIs" --required-years 3
```

The output includes rank, ATS score, matched skills, missing skills, experience, and score explanation.
