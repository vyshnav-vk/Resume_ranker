"""
Candidate Comparison Module
============================
Side-by-side comparison of 2-4 selected candidates across:
  - Score breakdown bars
  - Keyword overlap / unique keywords
  - Experience
  - Role prediction
  - Head-to-head radar chart
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st


# ── Helpers ───────────────────────────────────────────────────────────────────
def _score_color(score: float) -> str:
    if score >= 7.5: return "#34d399"
    if score >= 5.0: return "#fbbf24"
    return "#f87171"


def _bar_html(label: str, value: float, color: str) -> str:
    pct = int(value * 100)
    return f"""
    <div style="margin:6px 0">
      <div style="font-size:.75rem;color:#64748b;margin-bottom:2px">{label} — {pct}%</div>
      <div style="background:#252c3a;border-radius:4px;height:8px">
        <div style="width:{pct}%;height:8px;border-radius:4px;background:{color}"></div>
      </div>
    </div>"""


def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """Convert #rrggbb to rgba(r,g,b,alpha)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _radar(candidates: list[dict]) -> go.Figure:
    categories = ["Semantic", "Keyword", "Experience", "Overall"]
    colors     = ["#4f8ef7", "#a78bfa", "#34d399", "#fbbf24", "#f87171"]
    fig = go.Figure()
    for i, c in enumerate(candidates):
        vals = [
            c["semantic_score"],
            c["keyword_score"],
            c["experience_score"],
            (c["final_score"] - 1) / 9,
        ]
        vals_pct = [v * 100 for v in vals] + [vals[0] * 100]
        cats     = categories + [categories[0]]
        color    = colors[i % len(colors)]
        fig.add_trace(go.Scatterpolar(
            r=vals_pct, theta=cats,
            fill="toself",
            name=c["filename"][:20],
            line=dict(color=color, width=2),
            fillcolor=_hex_to_rgba(color, 0.15),
        ))
    fig.update_layout(
        polar=dict(
            bgcolor="#161b24",
            radialaxis=dict(visible=True, range=[0, 100], color="#64748b", gridcolor="#252c3a"),
            angularaxis=dict(color="#e2e8f0", gridcolor="#252c3a"),
        ),
        paper_bgcolor="#0d0f14",
        showlegend=True,
        legend=dict(font=dict(color="#e2e8f0"), bgcolor="#161b24"),
        margin=dict(l=40, r=40, t=30, b=30),
        height=370,
    )
    return fig


# ── Main UI ───────────────────────────────────────────────────────────────────
def render_comparison_tab(ranked: list[dict]) -> None:
    """Render the Candidate Comparison tab."""

    st.markdown("### ⚖️ Side-by-Side Comparison")

    if len(ranked) < 2:
        st.info("Upload at least 2 resumes and run ranking to compare candidates.")
        return

    options = {f"#{c['rank']} — {c['filename']}": c for c in ranked}
    labels  = list(options.keys())

    selected = st.multiselect(
        "Select 2–4 candidates to compare",
        options=labels,
        default=labels[:min(2, len(labels))],
        max_selections=4,
        key="compare_select",
    )

    if len(selected) < 2:
        st.warning("Please select at least 2 candidates.")
        return

    candidates = [options[s] for s in selected]

    # ── Radar overlay ─────────────────────────────────────────────────────
    st.plotly_chart(_radar(candidates), use_container_width=True)
    st.divider()

    # ── Per-candidate cards ───────────────────────────────────────────────
    cols = st.columns(len(candidates))
    for col, c in zip(cols, candidates):
        score = c["final_score"]
        color = _score_color(score)
        with col:
            st.markdown(f"""
            <div style="background:#161b24;border:1px solid #252c3a;border-radius:12px;padding:1.2rem;">
              <div style="font-size:.8rem;color:#64748b">Rank #{c['rank']}</div>
              <div style="font-weight:600;font-size:.95rem;margin:.2rem 0">{c['filename']}</div>
              <div style="font-size:2rem;font-weight:700;color:{color};font-family:monospace">{score}</div>
              <div style="font-size:.75rem;color:#64748b">/ 10</div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                _bar_html("Semantic",   c["semantic_score"],   "#4f8ef7") +
                _bar_html("Keyword",    c["keyword_score"],    "#a78bfa") +
                _bar_html("Experience", c["experience_score"], "#34d399"),
                unsafe_allow_html=True
            )

            role = c.get("predicted_role") or "—"
            yoe  = c.get("years_of_experience", 0)
            st.markdown(f"""
            <div style="margin-top:1rem;font-size:.8rem;color:#64748b">
              🎯 Role: <span style="color:#e2e8f0">{role}</span><br>
              🗓️ Experience: <span style="color:#e2e8f0">{yoe} yrs</span>
            </div>
            """, unsafe_allow_html=True)

    st.divider()

    # ── Keyword overlap matrix ────────────────────────────────────────────
    st.markdown("#### 🔑 Keyword Overlap")
    all_kws = set()
    for c in candidates:
        all_kws.update(c.get("matched_keywords", []))

    if all_kws:
        rows = []
        for kw in sorted(all_kws):
            row = {"Keyword": kw}
            for c in candidates:
                has = kw in c.get("matched_keywords", [])
                row[c["filename"][:18]] = "✅" if has else "❌"
            rows.append(row)

        import pandas as pd
        df = pd.DataFrame(rows).set_index("Keyword")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No matched keywords to compare.")

    # ── Winner badge ──────────────────────────────────────────────────────
    winner = max(candidates, key=lambda c: c["final_score"])
    st.markdown(f"""
    <div style="background:rgba(52,211,153,.1);border:1px solid #34d399;border-radius:10px;
    padding:1rem;text-align:center;margin-top:1rem">
      🏆 <b style="color:#34d399">Top pick among selected:</b>
      <span style="color:#e2e8f0;font-size:1.1rem"> {winner['filename']}</span>
      &nbsp; <span style="color:#34d399;font-family:monospace;font-size:1.1rem">{winner['final_score']}/10</span>
    </div>
    """, unsafe_allow_html=True)