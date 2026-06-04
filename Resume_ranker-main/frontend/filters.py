"""
Candidate Filters Module
========================
Provides UI controls and logic to filter ranked candidates by:
  - Score range (min / max)
  - Predicted role
  - Years of experience
  - Matched keywords
  - Search by filename
"""

from __future__ import annotations

from typing import Optional
import streamlit as st


def render_filter_sidebar(ranked: list[dict]) -> list[dict]:
    """
    Render filter controls in the sidebar and return the filtered list.
    Call this after ranking results are available.
    """
    if not ranked:
        return ranked

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔽 Filter Candidates")

    # ── Score range ───────────────────────────────────────────────────────
    scores = [c["final_score"] for c in ranked]
    min_s, max_s = min(scores), max(scores)
    score_range = st.sidebar.slider(
        "Score Range",
        min_value=1.0, max_value=10.0,
        value=(max(1.0, min_s), min(10.0, max_s)),
        step=0.1,
        key="filter_score"
    )

    # ── Role filter ───────────────────────────────────────────────────────
    roles = sorted({c.get("predicted_role") or "Unknown" for c in ranked})
    selected_roles = st.sidebar.multiselect(
        "Role",
        options=roles,
        default=roles,
        key="filter_roles"
    )

    # ── Experience range ──────────────────────────────────────────────────
    yoe_vals = [c.get("years_of_experience", 0) for c in ranked]
    min_yoe, max_yoe = min(yoe_vals), max(yoe_vals)
    if min_yoe == max_yoe:
        max_yoe = max_yoe + 1  # avoid slider crash when all equal
    yoe_range = st.sidebar.slider(
        "Years of Experience",
        min_value=0, max_value=max(20, max_yoe),
        value=(min_yoe, max_yoe),
        step=1,
        key="filter_yoe"
    )

    # ── Keyword search ────────────────────────────────────────────────────
    kw_search = st.sidebar.text_input(
        "Must-have keyword",
        placeholder="e.g. python, aws",
        key="filter_kw"
    ).strip().lower()

    # ── Filename search ───────────────────────────────────────────────────
    name_search = st.sidebar.text_input(
        "Search by filename",
        placeholder="e.g. john",
        key="filter_name"
    ).strip().lower()

    # ── Apply filters ─────────────────────────────────────────────────────
    filtered = []
    for c in ranked:
        if not (score_range[0] <= c["final_score"] <= score_range[1]):
            continue
        role = c.get("predicted_role") or "Unknown"
        if role not in selected_roles:
            continue
        yoe = c.get("years_of_experience", 0)
        if not (yoe_range[0] <= yoe <= yoe_range[1]):
            continue
        if kw_search:
            kws = [k.lower() for k in c.get("matched_keywords", [])]
            if not any(kw_search in k for k in kws):
                continue
        if name_search and name_search not in c.get("filename", "").lower():
            continue
        filtered.append(c)

    # ── Filter summary badge ──────────────────────────────────────────────
    total = len(ranked)
    shown = len(filtered)
    if shown < total:
        st.sidebar.info(f"Showing **{shown}** of **{total}** candidates after filters.")
    else:
        st.sidebar.success(f"All **{total}** candidates shown.")

    return filtered


def render_active_filter_tags(ranked: list[dict], filtered: list[dict]) -> None:
    """Show active filter summary as tags above the leaderboard."""
    if len(filtered) == len(ranked):
        return

    removed = len(ranked) - len(filtered)
    st.markdown(
        f'<div style="background:#1e2a1e;border:1px solid #34d399;border-radius:8px;'
        f'padding:.5rem 1rem;margin-bottom:1rem;font-size:.85rem;color:#34d399">'
        f'🔽 Filters active — showing <b>{len(filtered)}</b> candidates '
        f'(<b>{removed}</b> hidden). Adjust filters in the sidebar to show more.</div>',
        unsafe_allow_html=True
    )