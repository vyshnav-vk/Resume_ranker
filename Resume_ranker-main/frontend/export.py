"""
Export Module
=============
Provides:
  - CSV export (already in dashboard — enhanced here with more fields)
  - PDF export via reportlab (professional summary report)
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st


# ── CSV ───────────────────────────────────────────────────────────────────────
def build_csv(ranked: list[dict]) -> bytes:
    rows = []
    for c in ranked:
        rows.append({
            "Rank":              c["rank"],
            "Filename":          c["filename"],
            "Final Score (1-10)": c["final_score"],
            "Semantic Score":    c["semantic_score"],
            "Keyword Score":     c["keyword_score"],
            "Experience Score":  c["experience_score"],
            "Years of Experience": c.get("years_of_experience", 0),
            "Predicted Role":    c.get("predicted_role", ""),
            "Matched Keywords":  ", ".join(c.get("matched_keywords", [])),
            "Explanation":       c.get("explanation", ""),
        })
    df = pd.DataFrame(rows)
    return df.to_csv(index=False).encode("utf-8")


# ── PDF ───────────────────────────────────────────────────────────────────────
def build_pdf(ranked: list[dict], job_title: Optional[str] = None, jd_mode: str = "provided") -> bytes:
    """Generate a professional PDF summary report."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )

        styles = getSampleStyleSheet()
        BG     = colors.HexColor("#0d0f14")
        ACCENT = colors.HexColor("#4f8ef7")
        GREEN  = colors.HexColor("#34d399")
        AMBER  = colors.HexColor("#fbbf24")
        RED    = colors.HexColor("#f87171")
        MUTED  = colors.HexColor("#64748b")
        WHITE  = colors.HexColor("#e2e8f0")

        title_style = ParagraphStyle("title",
            fontSize=22, textColor=ACCENT, spaceAfter=4,
            fontName="Helvetica-Bold", alignment=TA_LEFT)
        sub_style = ParagraphStyle("sub",
            fontSize=10, textColor=MUTED, spaceAfter=16,
            fontName="Helvetica")
        section_style = ParagraphStyle("section",
            fontSize=13, textColor=WHITE, spaceBefore=12, spaceAfter=6,
            fontName="Helvetica-Bold")
        body_style = ParagraphStyle("body",
            fontSize=9, textColor=WHITE, fontName="Helvetica", leading=13)

        story = []

        # Header
        title_text = job_title or ("Auto-Classified Role" if jd_mode == "classifier" else "Ranking Report")
        story.append(Paragraph("Resume Ranker — Candidate Report", title_style))
        story.append(Paragraph(
            f"Position: {title_text} &nbsp;|&nbsp; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; Candidates: {len(ranked)}",
            sub_style
        ))
        story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
        story.append(Spacer(1, 0.4*cm))

        # Summary table
        story.append(Paragraph("Ranking Summary", section_style))
        avg = sum(c["final_score"] for c in ranked) / len(ranked) if ranked else 0
        summary_data = [
            ["Metric", "Value"],
            ["Total Candidates", str(len(ranked))],
            ["Top Score", f"{ranked[0]['final_score']}/10" if ranked else "—"],
            ["Average Score", f"{avg:.2f}/10"],
            ["JD Mode", "Custom JD" if jd_mode == "provided" else "Auto-Classified"],
        ]
        summary_tbl = Table(summary_data, colWidths=[5*cm, 5*cm])
        summary_tbl.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,0),  ACCENT),
            ("TEXTCOLOR",   (0,0), (-1,0),  colors.white),
            ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",    (0,0), (-1,-1), 9),
            ("BACKGROUND",  (0,1), (-1,-1), colors.HexColor("#161b24")),
            ("TEXTCOLOR",   (0,1), (-1,-1), WHITE),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#161b24"), colors.HexColor("#1c2333")]),
            ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#252c3a")),
            ("ROWBACKGROUNDS", (0,0), (-1,0), [ACCENT]),
            ("ALIGN",       (0,0), (-1,-1), "LEFT"),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING",(0,0), (-1,-1), 8),
            ("TOPPADDING",  (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ]))
        story.append(summary_tbl)
        story.append(Spacer(1, 0.6*cm))

        # Ranked table
        story.append(Paragraph("Candidate Rankings", section_style))
        headers = ["Rank", "Filename", "Score", "Semantic", "Keyword", "Exp.", "YoE", "Role"]
        rows = [headers]
        for c in ranked:
            rows.append([
                f"#{c['rank']}",
                c["filename"][:30],
                f"{c['final_score']}/10",
                f"{c['semantic_score']:.0%}",
                f"{c['keyword_score']:.0%}",
                f"{c['experience_score']:.0%}",
                f"{c.get('years_of_experience', 0)} yrs",
                (c.get("predicted_role") or "—")[:18],
            ])

        col_widths = [1.2*cm, 5.5*cm, 1.8*cm, 2*cm, 1.8*cm, 1.5*cm, 1.5*cm, 3*cm]
        tbl = Table(rows, colWidths=col_widths, repeatRows=1)

        row_styles = [
            ("BACKGROUND",  (0,0), (-1,0),  ACCENT),
            ("TEXTCOLOR",   (0,0), (-1,0),  colors.white),
            ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",    (0,0), (-1,-1), 8),
            ("TEXTCOLOR",   (0,1), (-1,-1), WHITE),
            ("GRID",        (0,0), (-1,-1), 0.4, colors.HexColor("#252c3a")),
            ("ALIGN",       (0,0), (-1,-1), "LEFT"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING",(0,0), (-1,-1), 6),
            ("TOPPADDING",  (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ]
        # Alternate row colors
        for i in range(1, len(rows)):
            bg = colors.HexColor("#161b24") if i % 2 == 1 else colors.HexColor("#1c2333")
            row_styles.append(("BACKGROUND", (0,i), (-1,i), bg))
            # Score color
            score = ranked[i-1]["final_score"]
            sc = GREEN if score >= 7.5 else (AMBER if score >= 5.0 else RED)
            row_styles.append(("TEXTCOLOR", (2,i), (2,i), sc))

        tbl.setStyle(TableStyle(row_styles))
        story.append(tbl)
        story.append(Spacer(1, 0.6*cm))

        # Individual breakdowns
        story.append(Paragraph("Individual Explanations", section_style))
        for c in ranked[:10]:  # top 10
            story.append(Paragraph(
                f"<b>#{c['rank']} — {c['filename']}</b> &nbsp; Score: {c['final_score']}/10",
                body_style
            ))
            kws = ", ".join(c.get("matched_keywords", [])[:10]) or "None"
            story.append(Paragraph(f"<font color='#64748b'>Keywords:</font> {kws}", body_style))
            story.append(Paragraph(
                c.get("explanation", "").replace("\n", "  |  "),
                ParagraphStyle("exp", fontSize=8, textColor=MUTED, fontName="Helvetica", leading=12)
            ))
            story.append(Spacer(1, 0.3*cm))

        # Footer
        story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED))
        story.append(Paragraph("Generated by Resume Ranker Pro — Hybrid NLP Scoring (SBERT + TF-IDF + Experience)", sub_style))

        doc.build(story)
        return buf.getvalue()

    except ImportError:
        return _pdf_fallback(ranked, job_title)


def _pdf_fallback(ranked: list[dict], job_title: Optional[str]) -> bytes:
    """Plain text fallback if reportlab not installed."""
    lines = [
        "RESUME RANKER — CANDIDATE REPORT",
        f"Position : {job_title or 'N/A'}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Candidates: {len(ranked)}",
        "=" * 60,
    ]
    for c in ranked:
        lines += [
            f"#{c['rank']} {c['filename']}",
            f"  Score: {c['final_score']}/10",
            f"  Role : {c.get('predicted_role','—')}",
            f"  YoE  : {c.get('years_of_experience',0)} yrs",
            "",
        ]
    return "\n".join(lines).encode("utf-8")


# ── Streamlit Export Tab ──────────────────────────────────────────────────────
def render_export_tab(ranked: list[dict], job_title: Optional[str] = None, jd_mode: str = "provided") -> None:
    """Enhanced export tab replacing the basic one in dashboard.py."""

    st.markdown("### 📤 Export Results")

    if not ranked:
        st.info("No ranking results to export yet.")
        return

    import pandas as pd
    df = pd.DataFrame([{
        "Rank":              c["rank"],
        "Filename":          c["filename"],
        "Final Score":       c["final_score"],
        "Semantic":          c["semantic_score"],
        "Keyword":           c["keyword_score"],
        "Experience":        c["experience_score"],
        "Years Exp":         c.get("years_of_experience", 0),
        "Predicted Role":    c.get("predicted_role", ""),
        "Matched Keywords":  ", ".join(c.get("matched_keywords", [])),
    } for c in ranked])

    st.dataframe(df, use_container_width=True)
    st.divider()

    col_csv, col_pdf = st.columns(2)

    with col_csv:
        st.markdown("#### 📊 CSV Export")
        st.caption("Download rankings as a spreadsheet-ready CSV file.")
        csv_bytes = build_csv(ranked)
        st.download_button(
            "⬇️ Download CSV",
            data=csv_bytes,
            file_name=f"ranked_resumes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col_pdf:
        st.markdown("#### 📄 PDF Report")
        st.caption("Download a professional summary report (requires reportlab).")
        if st.button("⬇️ Generate & Download PDF", use_container_width=True):
            with st.spinner("Generating PDF…"):
                pdf_bytes = build_pdf(ranked, job_title=job_title, jd_mode=jd_mode)
            st.download_button(
                "📥 Click to Save PDF",
                data=pdf_bytes,
                file_name=f"resume_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )