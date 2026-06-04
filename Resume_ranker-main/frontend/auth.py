"""
Authentication Module
=====================
Handles:
  - Username / password login (local user store via JSON)
  - Google OAuth 2.0 login (via google-auth + requests-oauthlib)
  - Session management via st.session_state
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

import streamlit as st

# ── Local user store ──────────────────────────────────────────────────────────
USERS_FILE = Path(__file__).parent / "data" / "users.json"

DEFAULT_USERS = {
    "admin": {
        "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
        "name": "Admin User",
        "role": "admin",
    },
    "recruiter": {
        "password_hash": hashlib.sha256("recruit123".encode()).hexdigest(),
        "name": "HR Recruiter",
        "role": "recruiter",
    },
}


def _load_users() -> dict:
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text())
        except Exception:
            pass
    # Seed defaults
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(DEFAULT_USERS, indent=2))
    return DEFAULT_USERS


def _save_users(users: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2))


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── Local auth helpers ─────────────────────────────────────────────────────────
def register_user(username: str, password: str, name: str, role: str = "recruiter") -> bool:
    """Register a new local user. Returns False if username already exists."""
    users = _load_users()
    if username in users:
        return False
    users[username] = {
        "password_hash": _hash(password),
        "name": name,
        "role": role,
    }
    _save_users(users)
    return True


def verify_local_login(username: str, password: str) -> Optional[dict]:
    """Return user dict on success, None on failure."""
    users = _load_users()
    user = users.get(username)
    if user and user["password_hash"] == _hash(password):
        return {"username": username, "name": user["name"], "role": user["role"], "auth_method": "local"}
    return None


# ── Google OAuth helpers ──────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501")

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"


def get_google_auth_url() -> str:
    """Generate Google OAuth2 authorization URL."""
    state = secrets.token_urlsafe(16)
    st.session_state["oauth_state"] = state
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "offline",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


def exchange_google_code(code: str) -> Optional[dict]:
    """Exchange OAuth code for user info. Returns user dict or None."""
    try:
        import requests as req
        token_resp = req.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        }, timeout=10)
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")

        user_resp = req.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        user_resp.raise_for_status()
        info = user_resp.json()

        return {
            "username":    info.get("email", ""),
            "name":        info.get("name", info.get("email", "")),
            "role":        "recruiter",
            "auth_method": "google",
            "picture":     info.get("picture", ""),
        }
    except Exception as e:
        st.error(f"Google OAuth error: {e}")
        return None


# ── Session helpers ───────────────────────────────────────────────────────────
def set_session(user: dict) -> None:
    st.session_state["user"]       = user
    st.session_state["logged_in"]  = True
    st.session_state["login_time"] = time.time()


def logout() -> None:
    for key in ["user", "logged_in", "login_time", "oauth_state"]:
        st.session_state.pop(key, None)


def is_logged_in() -> bool:
    return bool(st.session_state.get("logged_in"))


def current_user() -> Optional[dict]:
    return st.session_state.get("user")


# ── Login UI ──────────────────────────────────────────────────────────────────
def render_login_page() -> None:
    """Full-page login UI. Sets session on success."""

    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');
    html, body, [data-testid="stAppViewContainer"] {
        background: #0d0f14 !important;
        color: #e2e8f0 !important;
        font-family: 'DM Sans', sans-serif;
    }
    [data-testid="stSidebar"] { display: none !important; }
    #MainMenu, footer, header { visibility: hidden; }
    .login-wrap {
        max-width: 440px;
        margin: 6vh auto 0;
        padding: 2.5rem 2.8rem;
        background: #161b24;
        border: 1px solid #252c3a;
        border-radius: 18px;
        box-shadow: 0 24px 64px rgba(0,0,0,.5);
    }
    .login-title {
        font-family: 'DM Serif Display', serif;
        font-size: 2rem;
        color: #e2e8f0;
        margin: 0 0 .3rem;
    }
    .login-sub { color: #64748b; font-size: .9rem; margin-bottom: 1.8rem; }
    .divider-text {
        text-align: center; color: #64748b; font-size:.8rem;
        border-top: 1px solid #252c3a;
        margin: 1.4rem 0;
        padding-top: .9rem;
    }
    .google-btn {
        display:flex; align-items:center; justify-content:center; gap:10px;
        background:#fff; color:#1f1f1f; font-weight:600; font-size:.95rem;
        border-radius:8px; padding:.6rem 1rem; width:100%;
        text-decoration:none; border:none; cursor:pointer;
        transition: box-shadow .2s;
    }
    .google-btn:hover { box-shadow: 0 2px 12px rgba(255,255,255,.15); }
    .stTextInput input {
        background: #0d0f14 !important;
        border: 1px solid #252c3a !important;
        border-radius: 8px !important;
        color: #e2e8f0 !important;
    }
    .stButton > button {
        background: #4f8ef7 !important;
        color: #fff !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        width: 100% !important;
        padding: .55rem !important;
    }
    .tab-note { color: #64748b; font-size:.78rem; margin-top:.5rem; }
    </style>
    """, unsafe_allow_html=True)

    # Check for OAuth callback code in URL
    params = st.query_params
    if "code" in params and GOOGLE_CLIENT_ID:
        with st.spinner("Signing in with Google…"):
            user = exchange_google_code(params["code"])
            if user:
                set_session(user)
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Google sign-in failed. Please try again.")

    st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="login-title">Resume Ranker</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-sub">Sign in to access the recruiter dashboard</div>', unsafe_allow_html=True)

    tab_login, tab_register = st.tabs(["Sign In", "Register"])

    with tab_login:
        username = st.text_input("Username", key="li_user", placeholder="e.g. recruiter")
        password = st.text_input("Password", type="password", key="li_pass", placeholder="••••••••")
        if st.button("Sign In", key="li_btn"):
            if not username or not password:
                st.error("Please fill in both fields.")
            else:
                user = verify_local_login(username, password)
                if user:
                    set_session(user)
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        st.markdown('<div class="tab-note">Default: <b>admin / admin123</b> &nbsp;|&nbsp; <b>recruiter / recruit123</b></div>', unsafe_allow_html=True)

    with tab_register:
        r_name  = st.text_input("Full Name",   key="reg_name",  placeholder="Jane Smith")
        r_user  = st.text_input("Username",    key="reg_user",  placeholder="jane.smith")
        r_pass  = st.text_input("Password",    type="password", key="reg_pass", placeholder="Min 6 characters")
        r_pass2 = st.text_input("Confirm Password", type="password", key="reg_pass2", placeholder="Repeat password")
        if st.button("Create Account", key="reg_btn"):
            if not all([r_name, r_user, r_pass, r_pass2]):
                st.error("All fields are required.")
            elif len(r_pass) < 6:
                st.error("Password must be at least 6 characters.")
            elif r_pass != r_pass2:
                st.error("Passwords do not match.")
            else:
                ok = register_user(r_user, r_pass, r_name)
                if ok:
                    st.success("Account created! You can now sign in.")
                else:
                    st.error("Username already taken.")

    # Google OAuth button
    if GOOGLE_CLIENT_ID:
        st.markdown('<div class="divider-text">— or continue with —</div>', unsafe_allow_html=True)
        google_url = get_google_auth_url()
        st.markdown(f'''
        <a href="{google_url}" class="google-btn">
            <svg width="18" height="18" viewBox="0 0 18 18"><path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"/><path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"/><path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 6.29C4.672 4.163 6.656 3.58 9 3.58z"/></svg>
            Sign in with Google
        </a>
        ''', unsafe_allow_html=True)
    else:
        st.markdown('<div class="divider-text">— Google OAuth not configured (set GOOGLE_CLIENT_ID env var) —</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)