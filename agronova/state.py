"""Session state, settings resolution and usage monitoring."""
from __future__ import annotations

import csv
import datetime as dt
import os
import uuid
from pathlib import Path

import streamlit as st

from .llm import Settings

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "usage_log.csv"
LOG_FIELDS = ["ts", "session", "event", "feature", "region", "model", "latency_s", "tokens_in", "tokens_out",
              "tool_calls", "rating", "language", "detail"]


def init() -> None:
    ss = st.session_state
    ss.setdefault("sid", uuid.uuid4().hex[:8])
    ss.setdefault("profile", {"lat": None, "lon": None, "district": "", "state": "", "country": "India",
                              "crop": "", "stage": "", "farm_size": "", "irrigation": "", "prefs": []})
    ss.setdefault("messages", [])
    ss.setdefault("language", "Auto — match my language")
    ss.setdefault("validation", [])
    ss.setdefault("map_ts", None)


def api_key() -> str:
    """The app's built-in AI key, read only from server-side secrets or environment (never from visitors)."""
    try:
        for k in ("GROQ_API_KEY", "XAI_API_KEY", "GROK_API_KEY"):
            if k in st.secrets and str(st.secrets[k]).strip():
                return str(st.secrets[k]).strip()
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY") or os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY") or ""


def settings() -> Settings:
    ss = st.session_state
    return Settings(model=ss.get("model") or "openai/gpt-oss-120b", temperature=ss.get("temperature", 0.6),
                    max_tokens=ss.get("max_tokens", 1400), thinking=ss.get("thinking", True), tools=ss.get("use_tools", True),
                    web=ss.get("use_web", True), guard=ss.get("use_guard", True))


def place_label(p: dict | None = None) -> str:
    p = p or st.session_state.profile
    if p.get("lat") is None:
        return ""
    return ", ".join(x for x in [p.get("district"), p.get("state"), p.get("country")] if x)


def log(event: str, **kw) -> None:
    row = {f: "" for f in LOG_FIELDS}
    row.update(ts=dt.datetime.now().isoformat(timespec="seconds"), session=st.session_state.get("sid", ""), event=event,
               region=place_label() or kw.pop("region", ""), model=st.session_state.get("model", ""),
               language=st.session_state.get("language", ""))
    row.update({k: v for k, v in kw.items() if k in row})
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        new = not LOG_PATH.exists()
        with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
    except OSError:
        pass  # read-only filesystems: keep the session copy only
    st.session_state.setdefault("session_log", []).append(row)
