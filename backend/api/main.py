"""
FastAPI — Resume Ranker API v2.2
=================================
POST /api/rank      → Score + skill-extract + project-extract + skill-gap resumes
GET  /api/health    → Health check
GET  /api/roles     → Available ML roles
POST /api/retrain   → Invalidate classifier cache
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Header
import os
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.auth_manager import (
    verify_password, create_session, verify_session, destroy_session,
    generate_otp, verify_otp, send_otp_email, exchange_google_code,
    is_email_authorized, authenticate_user, hash_password, send_user_notification,
    get_user
)

from backend.core.parser import parse_resume_batch
from backend.core.scoring_engine import score_resumes, ResumeScore
from backend.core.classifier import (
    RoleClassifier, generate_synthetic_jd,
    skill_gap_for_role, ROLE_CORPUS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Resume Ranker API",
    version="2.2.0",
    description="Hybrid NLP resume ranking with project extraction and skill-gap analysis.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ────────────────────────────────────────────────────────────
class ProjectEntry(BaseModel):
    title:            str
    description:      str
    skills_mentioned: list[str]


class SkillGap(BaseModel):
    role:            str
    expected_skills: list[str]
    present:         list[str]
    missing:         list[str]
    coverage_pct:    float


class CandidateResult(BaseModel):
    rank:                int
    candidate_id:        str
    filename:            str
    final_score:         float
    semantic_score:      float
    keyword_score:       float
    experience_score:    float
    years_of_experience: int
    predicted_role:      Optional[str]
    role_confidence:     Optional[float]
    matched_keywords:    list[str]
    skills:              dict[str, list[str]]
    all_skills:          list[str]
    projects:            list[ProjectEntry]       # NEW
    skill_gap:           Optional[SkillGap]       # NEW
    word_count:          int
    explanation:         str


class RankResponse(BaseModel):
    job_title:     Optional[str]
    jd_mode:       str
    detected_role: Optional[str]
    total_resumes: int
    ranked:        list[CandidateResult]


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class SendOtpRequest(BaseModel):
    email: str


class VerifyOtpRequest(BaseModel):
    email: str
    otp: str


class OAuthRequest(BaseModel):
    code: str


class AuthResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    email: Optional[str] = None


class ProfileResponse(BaseModel):
    success: bool
    email: str
    name: str


class UpdateProfileRequest(BaseModel):
    name: str


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.2.0"}


@app.get("/api/roles")
def get_roles():
    return {"roles": sorted(ROLE_CORPUS.keys())}


@app.post("/api/retrain")
def retrain(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized: authentication token is required")
    parts = authorization.split(" ")
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None
    if not token or not verify_session(token):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or expired session token")

    RoleClassifier.reset()
    return {"status": "cache cleared — classifier retrains on next /api/rank call"}


@app.post("/api/auth/login", response_model=AuthResponse)
def login(req: LoginRequest):
    email_clean = req.email.strip().lower()
    if authenticate_user(req.email, req.password):
        token = create_session(req.email)
        user = get_user(email_clean)
        user_name = user["name"] if (user and user.get("name")) else email_clean.split("@")[0].capitalize()
        # Fallback for default admin
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
        if email_clean == admin_email:
            user_name = "Admin Recruiter"
            
        send_user_notification(
            recipient_email=email_clean,
            name=user_name,
            subject="🔑 Secure Sign In Alert",
            event_title="Recruiter Login",
            message_body="You have successfully signed in using your email & password.",
            event_type="login"
        )
        return AuthResponse(success=True, message="Login successful", token=token, email=email_clean)
    raise HTTPException(status_code=401, detail="Invalid email or password")


@app.post("/api/auth/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    email = req.email.strip().lower()
    name = req.name.strip()
    if not name:
         raise HTTPException(status_code=400, detail="Full Name is required for registration.")
    
    # Check if user already exists
    existing = get_user(email)
    if existing and existing["is_verified"]:
        raise HTTPException(status_code=400, detail="User already registered. Please sign in.")
        
    # Check if email is authorized
    if not is_email_authorized(email):
        raise HTTPException(
            status_code=403,
            detail=f"Email '{email}' is not pre-authorized. Please add it to AUTHORIZED_EMAILS in your .env file and restart the backend server."
        )
        
    # Hash password and create unverified record
    password_hash = hash_password(req.password)
    from backend.core.auth_manager import create_unverified_user
    if not create_unverified_user(email, name, password_hash):
        raise HTTPException(status_code=500, detail="Failed to create user account.")
        
    # Send verification code
    otp = generate_otp(email)
    success = send_otp_email(email, otp)
    if success:
        return AuthResponse(success=True, message="Verification code sent via email.")
    else:
        raise HTTPException(status_code=500, detail="Failed to send verification email.")


@app.post("/api/auth/register/verify", response_model=AuthResponse)
def register_verify(req: VerifyOtpRequest):
    email = req.email.strip().lower()
    
    if not verify_otp(email, req.otp):
        raise HTTPException(status_code=401, detail="Invalid or expired verification code.")
        
    from backend.core.auth_manager import verify_user_email
    if not verify_user_email(email):
        raise HTTPException(status_code=500, detail="Failed to verify email in user registry.")
        
    user = get_user(email)
    user_name = user["name"] if (user and user.get("name")) else email.split("@")[0].capitalize()
    
    token = create_session(email)
    send_user_notification(
        recipient_email=email,
        name=user_name,
        subject="🆕 Registration Success",
        event_title="Account Verification",
        message_body="Welcome to Resume Ranker Pro! Your email address has been verified and registration is complete.",
        event_type="register"
    )
    return AuthResponse(success=True, message="Registration completed successfully.", token=token, email=email)


@app.post("/api/auth/send-otp", response_model=AuthResponse)
def send_otp(req: SendOtpRequest):
    email = req.email.strip().lower()
    if not is_email_authorized(email):
        raise HTTPException(status_code=403, detail="Email is not authorized as an admin")
        
    otp = generate_otp(email)
    success = send_otp_email(email, otp)
    if success:
        return AuthResponse(success=True, message="OTP sent successfully")
    else:
        raise HTTPException(status_code=500, detail="Failed to send OTP email")


@app.post("/api/auth/verify-otp", response_model=AuthResponse)
def verify_otp_endpoint(req: VerifyOtpRequest):
    email = req.email.strip().lower()
    if not is_email_authorized(email):
        raise HTTPException(status_code=403, detail="Email is not authorized as an admin")
        
    if verify_otp(email, req.otp):
        token = create_session(email)
        return AuthResponse(success=True, message="OTP verification successful", token=token, email=email)
    else:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP code")


@app.post("/api/auth/oauth/google", response_model=AuthResponse)
def oauth_google(req: OAuthRequest):
    user_info = exchange_google_code(req.code)
    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code with Google")
        
    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google user profile does not contain an email address")
        
    if not is_email_authorized(email):
        raise HTTPException(status_code=403, detail=f"Google account {email} is not authorized for access")
        
    google_name = user_info.get("name", "").strip()
    if not google_name:
        google_name = f"{user_info.get('given_name', '')} {user_info.get('family_name', '')}".strip()
        
    # Ensure Google authenticated user is registered and verified in database
    import secrets
    existing = get_user(email)
    is_new = False
    if not existing:
        is_new = True
        dummy_hash = hash_password(secrets.token_hex(32))
        final_name = google_name if google_name else email.split("@")[0].capitalize()
        create_unverified_user(email, final_name, dummy_hash)
        verify_user_email(email)
        user_name = final_name
    else:
        user_name = existing["name"] if existing.get("name") else google_name
        default_prefix = email.split("@")[0].capitalize()
        if google_name and (not existing.get("name") or existing["name"] == default_prefix):
            import sqlite3
            from backend.core.auth_manager import DB_PATH
            try:
                conn = sqlite3.connect(str(DB_PATH))
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET name = ? WHERE email = ?", (google_name, email))
                conn.commit()
                conn.close()
                user_name = google_name
            except Exception as e:
                logger.error(f"Failed to update Google OAuth name for existing user: {e}")
        if not user_name:
            user_name = default_prefix
        if not existing["is_verified"]:
            verify_user_email(email)
            
    token = create_session(email)
    
    action_str = "registered and signed in" if is_new else "signed in"
    send_user_notification(
        recipient_email=email,
        name=user_name,
        subject="🌐 Google OAuth Login Success",
        event_title="Google OAuth Login",
        message_body=f"You have successfully {action_str} to Resume Ranker Pro using your Google account.",
        event_type="login"
    )
    return AuthResponse(success=True, message="OAuth login successful", token=token, email=email)


@app.get("/api/auth/verify-token", response_model=AuthResponse)
def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
        
    token = parts[1]
    email = verify_session(token)
    if email:
        return AuthResponse(success=True, message="Token is valid", token=token, email=email)
    else:
        raise HTTPException(status_code=401, detail="Token is expired or invalid")


@app.get("/api/auth/profile", response_model=ProfileResponse)
def get_profile(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
        
    token = parts[1]
    email = verify_session(token)
    if not email:
        raise HTTPException(status_code=401, detail="Token is expired or invalid")
        
    user = get_user(email)
    user_name = user["name"] if (user and user.get("name")) else email.split("@")[0].capitalize()
    
    # Fallback for default admin
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
    if email == admin_email:
        user_name = "Admin Recruiter"
        
    return ProfileResponse(success=True, email=email, name=user_name)


@app.post("/api/auth/profile", response_model=AuthResponse)
def update_profile(req: UpdateProfileRequest, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
        
    token = parts[1]
    email = verify_session(token)
    if not email:
        raise HTTPException(status_code=401, detail="Token is expired or invalid")
        
    new_name = req.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
        
    # Check if admin
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
    if email == admin_email:
        return AuthResponse(success=True, message="Profile updated (transient admin)")
        
    # Update in SQLite
    import sqlite3
    from backend.core.auth_manager import DB_PATH
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET name = ? WHERE email = ?", (new_name, email))
        conn.commit()
        conn.close()
        return AuthResponse(success=True, message="Profile updated successfully")
    except Exception as e:
        logger.error(f"Failed to update profile name for {email}: {e}")
        raise HTTPException(status_code=500, detail="Database update failed")


@app.post("/api/auth/logout", response_model=AuthResponse)
def logout(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=400, detail="Missing Authorization header")
    parts = authorization.split(" ")
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1]
        email = verify_session(token)
        destroy_session(token)
        if email:
            user = get_user(email)
            user_name = user["name"] if (user and user.get("name")) else email.split("@")[0].capitalize()
            admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
            if email == admin_email:
                user_name = "Admin Recruiter"
                
            send_user_notification(
                recipient_email=email,
                name=user_name,
                subject="🔓 Sign Out Success",
                event_title="Recruiter Logout",
                message_body="You have successfully logged out of your session on Resume Ranker Pro.",
                event_type="logout"
            )
    return AuthResponse(success=True, message="Session destroyed")


@app.post("/api/rank", response_model=RankResponse)
async def rank_resumes(
    files:          list[UploadFile] = File(...),
    jd_text:        Optional[str]    = Form(None),
    job_title:      Optional[str]    = Form(None),
    required_years: int              = Form(3),
    anonymize:      bool             = Form(True),
    authorization:  Optional[str]    = Header(None),
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized: authentication token is required")
    parts = authorization.split(" ")
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None
    if not token or not verify_session(token):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or expired session token")
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    # 1. Parse + skill + project extract
    raw_files = [(await f.read(), f.filename or "unknown") for f in files]
    parsed    = parse_resume_batch(raw_files, anonymize=anonymize)
    valid     = [p for p in parsed if not p["parse_error"] and p["clean_text"]]

    if not valid:
        raise HTTPException(status_code=422, detail="Could not extract text from any file.")

    # 2. JD mode
    jd_mode       = "provided"
    detected_role: Optional[str] = None
    role_preds:    dict[str, dict] = {}

    if not jd_text or not jd_text.strip():
        jd_mode    = "classifier"
        classifier = RoleClassifier()
        for p in valid:
            pred = classifier.predict(p["clean_text"])
            role_preds[p["filename"]] = pred
        top_role      = Counter(v["predicted_role"] for v in role_preds.values()).most_common(1)[0][0]
        detected_role = top_role
        jd_text       = generate_synthetic_jd(top_role)
        logger.info("No JD. Predicted role: %s. Synthetic JD generated.", top_role)

    # 3. Score
    resume_inputs = [
        {"id": str(uuid.uuid4()), "text": p["clean_text"], "filename": p["filename"]}
        for p in valid
    ]
    scored: list[ResumeScore] = score_resumes(
        jd_text=jd_text,
        resumes=[{"id": r["id"], "text": r["text"]} for r in resume_inputs],
        required_years=required_years,
    )

    id_to_filename     = {r["id"]: r["filename"] for r in resume_inputs}
    filename_to_parsed = {p["filename"]: p for p in valid}

    # 4. Build response
    ranked_results = []
    for rank, score in enumerate(scored, start=1):
        filename   = id_to_filename.get(score.candidate_id, "unknown")
        pred_info  = role_preds.get(filename, {})
        parsed_doc = filename_to_parsed.get(filename, {})

        # Determine role for skill gap (predicted or job_title if provided)
        gap_role = (
            pred_info.get("predicted_role")
            or job_title
            or detected_role
        )
        skill_gap = None
        if gap_role and gap_role in ROLE_CORPUS:
            skill_gap = skill_gap_for_role(
                role=gap_role,
                candidate_skills=parsed_doc.get("all_skills", []),
            )

        ranked_results.append(CandidateResult(
            rank                = rank,
            candidate_id        = score.candidate_id,
            filename            = filename,
            final_score         = score.final_score,
            semantic_score      = score.semantic_score,
            keyword_score       = score.keyword_score,
            experience_score    = score.experience_score,
            years_of_experience = score.years_of_experience,
            predicted_role      = pred_info.get("predicted_role", job_title),
            role_confidence     = round(pred_info["confidence"], 3) if pred_info.get("confidence") else None,
            matched_keywords    = score.matched_keywords[:20],
            skills              = parsed_doc.get("skills", {}),
            all_skills          = parsed_doc.get("all_skills", []),
            projects            = [ProjectEntry(**p) for p in parsed_doc.get("projects", [])],
            skill_gap           = SkillGap(**skill_gap) if skill_gap else None,
            word_count          = parsed_doc.get("word_count", 0),
            explanation         = score.explanation,
        ))

    return RankResponse(
        job_title     = job_title,
        jd_mode       = jd_mode,
        detected_role = detected_role,
        total_resumes = len(valid),
        ranked        = ranked_results,
    )