"""
Upload Management Module
========================
Tracks uploaded resumes in a local JSON store.
Provides UI to:
  - View upload history (filename, date, size, parse status)
  - Delete individual or all uploads
  - Re-use a previous upload in a new ranking run
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st

UPLOAD_STORE = Path(__file__).parent / "data" / "upload_history.json"
UPLOAD_DIR   = Path(__file__).parent / "uploaded_resumes"


def _load_store() -> list[dict]:
    if UPLOAD_STORE.exists():
        try:
            return json.loads(UPLOAD_STORE.read_text())
        except Exception:
            pass
    return []


def _save_store(records: list[dict]) -> None:
    UPLOAD_STORE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_STORE.write_text(json.dumps(records, indent=2))


def save_upload(filename: str, file_bytes: bytes, user: str = "unknown") -> dict:
    """Persist an uploaded resume and record it."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{int(time.time())}_{filename}"
    dest = UPLOAD_DIR / safe_name

    dest.write_bytes(file_bytes)

    record = {
        "id":          safe_name,
        "original_name": filename,
        "stored_name": safe_name,
        "size_kb":     round(len(file_bytes) / 1024, 1),
        "uploaded_by": user,
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "timestamp":   time.time(),
    }
    records = _load_store()
    records.append(record)
    _save_store(records)
    return record


def delete_upload(stored_name: str) -> bool:
    """Delete a specific upload record and its file."""
    records = _load_store()
    records = [r for r in records if r["stored_name"] != stored_name]
    _save_store(records)
    dest = UPLOAD_DIR / stored_name
    if dest.exists():
        dest.unlink()
    return True


def clear_all_uploads() -> None:
    """Delete all upload records and files."""
    records = _load_store()
    for r in records:
        f = UPLOAD_DIR / r["stored_name"]
        if f.exists():
            f.unlink()
    _save_store([])


def get_uploads(user: Optional[str] = None) -> list[dict]:
    """Return all uploads, optionally filtered by user."""
    records = _load_store()
    if user:
        records = [r for r in records if r.get("uploaded_by") == user]
    return sorted(records, key=lambda r: r.get("timestamp", 0), reverse=True)


def load_upload_bytes(stored_name: str) -> Optional[bytes]:
    """Read stored file bytes for re-use."""
    dest = UPLOAD_DIR / stored_name
    if dest.exists():
        return dest.read_bytes()
    return None


# ── Streamlit UI ──────────────────────────────────────────────────────────────
def render_upload_manager(current_user: dict) -> None:
    """Render the Upload Management tab."""

    st.markdown("### 📁 Upload History")
    st.caption("All resumes you've uploaded in previous sessions.")

    username = current_user.get("username", "unknown")
    is_admin = current_user.get("role") == "admin"

    records = get_uploads(user=None if is_admin else username)

    if not records:
        st.info("No uploads found. Upload resumes from the sidebar to get started.")
        return

    # ── Summary stats ─────────────────────────────────────────────────────
    total_size = sum(r.get("size_kb", 0) for r in records)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Files", len(records))
    c2.metric("Total Size", f"{total_size:.1f} KB")
    c3.metric("Latest Upload", records[0]["uploaded_at"] if records else "—")

    st.divider()

    # ── Bulk actions ──────────────────────────────────────────────────────
    col_search, col_del = st.columns([4, 1])
    with col_search:
        search = st.text_input("🔍 Search by filename", placeholder="e.g. john_doe", label_visibility="collapsed")
    with col_del:
        if st.button("🗑️ Clear All", type="secondary", use_container_width=True):
            st.session_state["confirm_clear"] = True

    if st.session_state.get("confirm_clear"):
        st.warning("⚠️ This will delete ALL upload history and files. Are you sure?")
        col_y, col_n = st.columns(2)
        with col_y:
            if st.button("Yes, delete all", type="primary"):
                clear_all_uploads()
                st.session_state.pop("confirm_clear", None)
                st.success("All uploads cleared.")
                st.rerun()
        with col_n:
            if st.button("Cancel"):
                st.session_state.pop("confirm_clear", None)
                st.rerun()

    # ── File table ────────────────────────────────────────────────────────
    filtered = [
        r for r in records
        if search.lower() in r["original_name"].lower()
    ] if search else records

    if not filtered:
        st.info("No files match your search.")
        return

    # Column headers
    h1, h2, h3, h4, h5 = st.columns([3, 1.5, 1.5, 1.5, 1])
    h1.markdown("**Filename**")
    h2.markdown("**Uploaded By**")
    h3.markdown("**Date**")
    h4.markdown("**Size**")
    h5.markdown("**Action**")
    st.markdown("<hr style='margin:4px 0;border-color:#252c3a'>", unsafe_allow_html=True)

    for r in filtered:
        c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1.5, 1.5, 1])
        c1.markdown(f"📄 `{r['original_name']}`")
        c2.markdown(r.get("uploaded_by", "—"))
        c3.markdown(r["uploaded_at"])
        c4.markdown(f"{r['size_kb']} KB")
        with c5:
            if st.button("🗑️", key=f"del_{r['stored_name']}", help="Delete this file"):
                delete_upload(r["stored_name"])
                st.success(f"Deleted {r['original_name']}")
                st.rerun()

    st.caption(f"Showing {len(filtered)} of {len(records)} files.")