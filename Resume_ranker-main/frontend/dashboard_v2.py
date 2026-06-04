"""
Resume Ranker — Dashboard v2
============================
Integrates all Member-1 features:
  ✅ Login (username/password + Google OAuth)
  ✅ Upload Management
  ✅ Filters
  ✅ Candidate Comparison
  ✅ Export (CSV + PDF)
"""

from __future__ import annotations
import sys
import logging
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from PIL import Image

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Member-1 modules ──────────────────────────────────────────────────────────
from frontend.auth           import render_login_page, is_logged_in, current_user, logout
from frontend.upload_manager import render_upload_manager, save_upload
from frontend.filters        import render_filter_sidebar, render_active_filter_tags
from frontend.comparison     import render_comparison_tab
from frontend.export         import render_export_tab

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8000/api"
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# ── Page config (must be first Streamlit call) ────────────────────────────────
try:
    logo = Image.open(ROOT / "frontend" / "Logo.jpg")
    st.set_page_config(page_title="Resume Ranker", page_icon=logo,
                       layout="wide", initial_sidebar_state="expanded")
except Exception:
    st.set_page_config(page_title="Resume Ranker", page_icon="📄",
                       layout="wide", initial_sidebar_state="expanded")

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono&display=swap');
:root {
    --bg:      #0d0f14; --surface: #161b24; --border: #252c3a;
    --accent:  #4f8ef7; --accent2: #a78bfa; --green:  #34d399;
    --amber:   #fbbf24; --red:     #f87171; --text:   #e2e8f0; --muted: #64748b;
}
html, body, [data-testid="stAppViewContainer"] {
    background: var(--bg) !important; color: var(--text) !important;
    font-family: 'DM Sans', sans-serif;
}
[data-testid="stSidebar"] { background: var(--surface) !important; border-right: 1px solid var(--border); }
h1,h2,h3 { font-family:'DM Serif Display',serif; color:var(--text) !important; }
.rank-card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1rem 1.4rem; margin-bottom:.75rem; transition:border-color .2s; }
.rank-card:hover { border-color:var(--accent); }
.score-pill { display:inline-block; font-family:'JetBrains Mono',monospace; font-size:1.5rem; font-weight:700; padding:.15rem .6rem; border-radius:8px; min-width:60px; text-align:center; }
.score-high { background:rgba(52,211,153,.15); color:var(--green);  border:1px solid var(--green); }
.score-mid  { background:rgba(251,191,36,.12); color:var(--amber); border:1px solid var(--amber); }
.score-low  { background:rgba(248,113,113,.12);color:var(--red);   border:1px solid var(--red);  }
.keyword-tag { display:inline-block; background:rgba(79,142,247,.12); color:var(--accent); border:1px solid rgba(79,142,247,.3); border-radius:20px; font-size:.72rem; padding:2px 10px; margin:2px 3px; font-family:'JetBrains Mono',monospace; }
.stat-box { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:1rem; text-align:center; }
.stat-box .val { font-family:'JetBrains Mono',monospace; font-size:2rem; font-weight:700; color:var(--accent); }
.stat-box .lbl { font-size:.78rem; color:var(--muted); }
.bar-wrap { margin:4px 0; }
.bar-label { font-size:.78rem; color:var(--muted); margin-bottom:2px; }
.bar-outer { background:var(--border); border-radius:4px; height:7px; }
.bar-inner { height:7px; border-radius:4px; }
.stButton > button { background:var(--accent) !important; color:#fff !important; border:none !important; border-radius:8px !important; font-family:'DM Sans',sans-serif !important; font-weight:600 !important; }
#MainMenu, footer { visibility:hidden; }
.user-chip { display:inline-flex; align-items:center; gap:8px; background:#1c2333; border:1px solid #252c3a; border-radius:20px; padding:4px 12px; font-size:.82rem; color:#e2e8f0; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def score_color(s): return "score-high" if s >= 7.5 else ("score-mid" if s >= 5.0 else "score-low")

def bar_html(label, value, color="#4f8ef7"):
    pct = int(value * 100)
    return f'<div class="bar-wrap"><div class="bar-label">{label} — {pct}%</div><div class="bar-outer"><div class="bar-inner" style="width:{pct}%;background:{color}"></div></div></div>'

def keywords_html(kws):
    return " ".join(f'<span class="keyword-tag">{k}</span>' for k in kws)

def radar_chart(candidate, jd_keywords):
    cats   = ["Semantic Fit","Keyword Match","Experience","Keyword Breadth","Overall"]
    matched_pct = len(candidate["matched_keywords"]) / max(len(jd_keywords), 1)
    vals   = [candidate["semantic_score"], candidate["keyword_score"],
              candidate["experience_score"], matched_pct,
              (candidate["final_score"] - 1) / 9]
    vals  += [vals[0]]; cats += [cats[0]]
    fig = go.Figure(go.Scatterpolar(
        r=[v*100 for v in vals], theta=cats, fill="toself",
        line=dict(color="#4f8ef7", width=2), fillcolor="rgba(79,142,247,0.15)"))
    fig.update_layout(
        polar=dict(bgcolor="#161b24",
            radialaxis=dict(visible=True, range=[0,100], color="#64748b", gridcolor="#252c3a"),
            angularaxis=dict(color="#e2e8f0", gridcolor="#252c3a")),
        paper_bgcolor="#0d0f14", showlegend=False,
        margin=dict(l=40,r=40,t=40,b=40), height=320)
    return fig

def score_breakdown_chart(candidate):
    labels = ["Semantic (50%)", "Keyword (30%)", "Experience (20%)"]
    values = [candidate["semantic_score"], candidate["keyword_score"], candidate["experience_score"]]
    colors = ["#4f8ef7","#a78bfa","#34d399"]
    fig = go.Figure(go.Bar(x=labels, y=[v*100 for v in values], marker_color=colors,
        text=[f"{v*100:.1f}%" for v in values], textposition="outside"))
    fig.update_layout(paper_bgcolor="#0d0f14", plot_bgcolor="#161b24",
        font=dict(color="#e2e8f0"),
        yaxis=dict(range=[0,105], gridcolor="#252c3a"),
        xaxis=dict(gridcolor="#252c3a"),
        margin=dict(l=10,r=10,t=10,b=10), height=240)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════════════════

# ── STEP 1: Auth gate ─────────────────────────────────────────────────────────
if not is_logged_in():
    render_login_page()
    st.stop()

# ── Logged-in user ────────────────────────────────────────────────────────────
user = current_user()

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    try:
        st.image(str(ROOT / "frontend" / "Logo.jpg"), use_column_width=True)
    except Exception:
        pass

    st.markdown("## 📄 Resume Ranker")
    st.markdown("*Hybrid NLP scoring powered by SBERT + TF-IDF*")

    # User chip
    st.markdown(f"""
    <div class="user-chip">
      👤 <b>{user.get('name','User')}</b>
      &nbsp;<span style="color:#64748b;font-size:.75rem">{user.get('role','').upper()}</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚪 Logout", use_container_width=True):
        logout()
        st.rerun()

    st.divider()

    # ── Upload section ────────────────────────────────────────────────────
    st.markdown("### 📂 Upload Resumes")
    uploaded_files = st.file_uploader(
        "Drop PDF, DOCX, or TXT files",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    # Auto-save uploads to history
    if uploaded_files:
        for f in uploaded_files:
            key = f"saved_{f.name}_{f.size}"
            if not st.session_state.get(key):
                save_upload(f.name, f.getvalue(), user.get("username", "unknown"))
                st.session_state[key] = True

    # ── Job Description ───────────────────────────────────────────────────
    st.markdown("### 📋 Job Description")
    jd_mode_sel = st.radio("Mode", ["Custom JD","Standard Role","Auto-Classify"],
                           label_visibility="collapsed")
    jd_text = job_title = standard_role = None

    if jd_mode_sel == "Custom JD":
        jd_text   = st.text_area("Paste Job Description", height=140, placeholder="Senior Data Scientist…")
        job_title = st.text_input("Job Title (optional)", placeholder="Senior Data Scientist")
    elif jd_mode_sel == "Standard Role":
        try:
            roles_resp   = requests.get(f"{API_BASE}/roles", timeout=5).json()
            role_options = roles_resp.get("roles", [])
        except Exception:
            role_options = ["Data Scientist","Software Engineer","HR Manager","Finance Analyst"]
        standard_role = st.selectbox("Select Role", role_options)
        job_title = standard_role
    else:
        st.info("The system will auto-classify each resume.")

    st.divider()

    # ── Settings ──────────────────────────────────────────────────────────
    st.markdown("### ⚙️ Settings")
    required_years = st.slider("Required Experience (yrs)", 0, 15, 3)
    anonymize      = st.toggle("Anonymise PII", value=True)
    top_n_display  = st.slider("Show Top N Candidates", 3, 20, 10)
    run_btn        = st.button("🚀 Rank Resumes", use_container_width=True)


# ── PAGE HEADER ───────────────────────────────────────────────────────────────
st.markdown("""
<h1 style='margin-bottom:0'>Resume Ranking Dashboard</h1>
<p style='color:#64748b;margin-top:4px'>Professional-grade candidate intelligence platform</p>
""", unsafe_allow_html=True)
st.divider()


# ── RUN RANKING ───────────────────────────────────────────────────────────────
if run_btn:
    if not uploaded_files:
        st.error("Please upload at least one resume.")
        st.stop()

    api_jd = jd_text or ""
    if jd_mode_sel == "Standard Role":
        api_jd = ""

    with st.spinner("Parsing resumes and computing scores…"):
        files_data = [("files", (f.name, f.read(), "application/octet-stream"))
                      for f in uploaded_files]
        form_data  = {"required_years": str(required_years),
                      "anonymize": str(anonymize).lower()}
        if api_jd.strip():
            form_data["jd_text"] = api_jd
        if job_title:
            form_data["job_title"] = job_title

        try:
            resp = requests.post(f"{API_BASE}/rank", files=files_data,
                                 data=form_data, timeout=120)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.ConnectionError:
            st.error("❌ Cannot reach the API server. Make sure FastAPI is running on port 8000.")
            st.code("uvicorn backend.api.main:app --reload --port 8000")
            st.stop()
        except Exception as e:
            st.error(f"API error: {e}")
            st.stop()

    ranked   = data["ranked"][:top_n_display]
    jd_mode  = data["jd_mode"]
    all_kws  = ranked[0]["matched_keywords"] if ranked else []

    st.session_state["ranked"]   = ranked
    st.session_state["jd_mode"]  = jd_mode
    st.session_state["all_kws"]  = all_kws
    st.session_state["job_title"] = job_title or ""
    st.session_state["run_done"] = True


# ── RESULTS ───────────────────────────────────────────────────────────────────
if st.session_state.get("run_done"):
    ranked    = st.session_state["ranked"]
    jd_mode   = st.session_state["jd_mode"]
    all_kws   = st.session_state["all_kws"]
    job_title = st.session_state.get("job_title", "")

    # ── Apply filters (Member 1) ──────────────────────────────────────────
    filtered = render_filter_sidebar(ranked)

    # ── Stats row ─────────────────────────────────────────────────────────
    avg_score = sum(c["final_score"] for c in filtered) / len(filtered) if filtered else 0
    top_score = filtered[0]["final_score"] if filtered else 0
    jd_label  = "🤖 Auto" if jd_mode == "classifier" else "📋 JD"

    c1, c2, c3, c4 = st.columns(4)
    for col, val, lbl in [
        (c1, len(filtered),       "Candidates Shown"),
        (c2, top_score,           "Top Score /10"),
        (c3, f"{avg_score:.1f}",  "Average Score"),
        (c4, jd_label,            "Mode"),
    ]:
        col.markdown(f'<div class="stat-box"><div class="val">{val}</div><div class="lbl">{lbl}</div></div>',
                     unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Active filter banner
    render_active_filter_tags(ranked, filtered)

    # ── Tabs: always visible, content adapts based on ranking state ──────
    tab_leader, tab_detail, tab_compare, tab_uploads, tab_export = st.tabs([
        "🏆 Leaderboard",
        "🔍 Deep Dive",
        "⚖️ Compare",
        "📁 Uploads",
        "📤 Export",
    ])

    # ── TAB 1 : Leaderboard ───────────────────────────────────────────────
    with tab_leader:
        st.markdown("### Ranked Candidates")
        if not filtered:
            st.warning("No candidates match the current filters. Try widening the filter range in the sidebar.")
        for cand in filtered:
            sc   = cand["final_score"]
            pill = score_color(sc)
            col_rank, col_info, col_score = st.columns([1, 6, 2])
            with col_rank:
                st.markdown(f"<h2 style='color:#64748b;text-align:center'>#{cand['rank']}</h2>",
                            unsafe_allow_html=True)
            with col_info:
                st.markdown(f"**{cand['filename']}**")
                role_label = f"🎯 {cand.get('predicted_role','')}" if cand.get("predicted_role") else ""
                st.caption(f"{role_label}  |  🗓️ {cand['years_of_experience']} yrs exp")
                st.markdown(
                    bar_html("Semantic",    cand["semantic_score"],   "#4f8ef7") +
                    bar_html("Keyword",     cand["keyword_score"],    "#a78bfa") +
                    bar_html("Experience",  cand["experience_score"], "#34d399"),
                    unsafe_allow_html=True)
            with col_score:
                st.markdown(
                    f'<div style="text-align:center;padding-top:1rem">'
                    f'<span class="score-pill {pill}">{sc}</span></div>',
                    unsafe_allow_html=True)
            with st.expander("🔑 Matched Keywords & Explanation"):
                st.markdown(keywords_html(cand["matched_keywords"]), unsafe_allow_html=True)
                st.markdown("---")
                st.code(cand["explanation"], language=None)
            st.markdown("<hr style='border-color:#252c3a'>", unsafe_allow_html=True)

    # ── TAB 2 : Deep Dive ─────────────────────────────────────────────────
    with tab_detail:
        st.markdown("### Candidate Analysis")
        options = {f"#{c['rank']} — {c['filename']}": c for c in filtered}
        if not options:
            st.warning("No candidates to analyse. Adjust filters.")
        else:
            selected_label = st.selectbox("Select Candidate", list(options.keys()))
            cand = options[selected_label]
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown("#### 🕸️ Skill-Gap Radar")
                st.plotly_chart(radar_chart(cand, all_kws), use_container_width=True)
            with col_r:
                st.markdown("#### 📊 Score Breakdown")
                st.plotly_chart(score_breakdown_chart(cand), use_container_width=True)
            st.markdown("#### 💡 Why this Score?")
            st.info(cand["explanation"])
            st.markdown("#### 🔑 Matched Keywords")
            st.markdown(keywords_html(cand["matched_keywords"]), unsafe_allow_html=True)

    # ── TAB 3 : Compare (Member 1) ────────────────────────────────────────
    with tab_compare:
        render_comparison_tab(filtered)

    # ── TAB 4 : Upload Management (Member 1) ──────────────────────────────
    with tab_uploads:
        render_upload_manager(user)

    # ── TAB 5 : Export (Member 1 — enhanced) ─────────────────────────────
    with tab_export:
        render_export_tab(filtered, job_title=job_title, jd_mode=jd_mode)

else:
    # ── Before ranking: show all tabs with empty states ───────────────────
    st.markdown("""
    <div style="background:rgba(79,142,247,.08);border:1px solid rgba(79,142,247,.3);
    border-radius:10px;padding:1rem 1.4rem;margin-bottom:1.5rem">
    👈 <b style="color:#4f8ef7">Upload resumes</b> from the sidebar and click
    <b style="color:#4f8ef7">🚀 Rank Resumes</b> to get started.
    </div>
    """, unsafe_allow_html=True)

    tab_leader, tab_detail, tab_compare, tab_uploads, tab_export = st.tabs([
        "🏆 Leaderboard",
        "🔍 Deep Dive",
        "⚖️ Compare",
        "📁 Uploads",
        "📤 Export",
    ])

    _empty_msg = lambda icon, text: st.markdown(
        f'<div style="text-align:center;padding:3rem;color:#64748b">'
        f'<div style="font-size:2.5rem">{icon}</div>'
        f'<div style="margin-top:.5rem">{text}</div></div>',
        unsafe_allow_html=True
    )

    with tab_leader:
        _empty_msg("🏆", "No ranking yet — upload resumes and click <b>Rank Resumes</b>")

    with tab_detail:
        _empty_msg("🔍", "Run a ranking first to analyse individual candidates")

    with tab_compare:
        _empty_msg("⚖️", "Run a ranking first to compare candidates side by side")

    with tab_uploads:
        render_upload_manager(user)

    with tab_export:
        _empty_msg("📤", "Run a ranking first to export results")