"""Bi-directional Streamlit component: interactive India district map (Leaflet + custom motion)."""
from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent.parent / "components" / "india_map"
_india_map = components.declare_component("agronova_india_map", path=str(_DIR))


def india_map(locked: dict | None = None, height: int = 640, key: str = "india_map") -> dict | None:
    """Render the map. Returns {lat, lon, district, state, country, source, ts} once the user locks a farm."""
    return _india_map(locked=locked, height=height, key=key, default=None)
