"""Live data tools the AI can call on its own (agentic tool use).

All sources are free and need no API key:
  * Open-Meteo forecast + geocoding  (https://open-meteo.com)
  * ISRIC SoilGrids v2               (https://soilgrids.org)
  * A built-in Indian / global crop-calendar knowledge base
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import requests

TIMEOUT = 12
UA = {"User-Agent": "AgroNova-SmartFarming/1.0"}

WEATHER_CODES = {
    0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"), 48: ("Rime fog", "🌫️"), 51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"),
    55: ("Heavy drizzle", "🌧️"), 61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌨️"), 67: ("Freezing rain", "🌨️"), 71: ("Light snow", "🌨️"), 73: ("Snow", "❄️"),
    75: ("Heavy snow", "❄️"), 77: ("Snow grains", "❄️"), 80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌧️"),
    82: ("Violent showers", "⛈️"), 85: ("Snow showers", "🌨️"), 86: ("Snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm + hail", "⛈️"), 99: ("Severe thunderstorm", "⛈️"),
}


def describe_code(code: int | None) -> tuple[str, str]:
    return WEATHER_CODES.get(int(code or 0), ("Unknown", "🌡️"))


# ───────────────────────────── geocoding ─────────────────────────────
def geocode(query: str, country_code: str | None = None, count: int = 5) -> list[dict]:
    params: dict[str, Any] = {"name": query, "count": count, "language": "en", "format": "json"}
    if country_code:
        params["countryCode"] = country_code
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search", params=params, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    out = []
    for g in r.json().get("results", []) or []:
        out.append({
            "name": g.get("name"), "district": g.get("admin2"), "state": g.get("admin1"),
            "country": g.get("country"), "latitude": g.get("latitude"), "longitude": g.get("longitude"),
            "elevation_m": g.get("elevation"),
        })
    return out


# ───────────────────────────── weather ─────────────────────────────
def fetch_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """Raw Open-Meteo forecast used both by the UI charts and the AI tool."""
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": max(1, min(int(days), 16)),
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,"
                   "wind_speed_10m,cloud_cover",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "precipitation_probability_max,et0_fao_evapotranspiration,wind_speed_10m_max,uv_index_max,"
                 "sunshine_duration",
        "hourly": "soil_moisture_0_to_1cm,soil_moisture_3_to_9cm,soil_temperature_6cm,relative_humidity_2m",
    }
    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    return r.json()


def _mean(vals):
    vals = [v for v in (vals or []) if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def tool_weather(location: str = "", latitude: float | None = None, longitude: float | None = None,
                 days: int = 7, **_) -> dict:
    place = None
    if (latitude is None or longitude is None) and location:
        hits = geocode(location, count=1)
        if not hits:
            return {"error": f"Could not find a place called '{location}'."}
        place = hits[0]
        latitude, longitude = place["latitude"], place["longitude"]
    if latitude is None or longitude is None:
        return {"error": "Need a location name or latitude/longitude."}
    raw = fetch_forecast(float(latitude), float(longitude), days)
    cur, d, h = raw.get("current", {}), raw.get("daily", {}), raw.get("hourly", {})
    daily = []
    for i, day in enumerate(d.get("time", [])):
        label, _icon = describe_code(d["weather_code"][i])
        daily.append({
            "date": day, "sky": label,
            "t_max_c": d["temperature_2m_max"][i], "t_min_c": d["temperature_2m_min"][i],
            "rain_mm": d["precipitation_sum"][i], "rain_chance_pct": d["precipitation_probability_max"][i],
            "evapotranspiration_mm": d["et0_fao_evapotranspiration"][i],
            "wind_max_kmh": d["wind_speed_10m_max"][i], "uv_max": d["uv_index_max"][i],
        })
    return {
        "source": "Open-Meteo live forecast",
        "place": place or {"latitude": latitude, "longitude": longitude},
        "timezone": raw.get("timezone"),
        "now": {
            "temperature_c": cur.get("temperature_2m"), "feels_like_c": cur.get("apparent_temperature"),
            "humidity_pct": cur.get("relative_humidity_2m"), "wind_kmh": cur.get("wind_speed_10m"),
            "sky": describe_code(cur.get("weather_code"))[0], "cloud_cover_pct": cur.get("cloud_cover"),
        },
        "soil_next_24h": {
            "moisture_0_1cm_m3m3": _mean(h.get("soil_moisture_0_to_1cm", [])[:24]),
            "moisture_3_9cm_m3m3": _mean(h.get("soil_moisture_3_to_9cm", [])[:24]),
            "temperature_6cm_c": _mean(h.get("soil_temperature_6cm", [])[:24]),
        },
        "daily": daily,
        "week_totals": {"rain_mm": round(sum(x["rain_mm"] or 0 for x in daily), 1),
                        "et0_mm": round(sum(x["evapotranspiration_mm"] or 0 for x in daily), 1)},
    }


# ───────────────────────────── soil ─────────────────────────────
def tool_soil(latitude: float, longitude: float, **_) -> dict:
    props = ["phh2o", "soc", "clay", "sand", "silt", "nitrogen", "cec"]
    try:
        r = requests.get(
            "https://rest.isric.org/soilgrids/v2.0/properties/query",
            params=[("lon", longitude), ("lat", latitude), *[("property", p) for p in props],
                    ("depth", "0-5cm"), ("depth", "15-30cm"), ("value", "mean")],
            timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        layers = r.json().get("properties", {}).get("layers", [])
    except Exception as e:  # SoilGrids is sometimes slow / down
        return {"error": f"SoilGrids unavailable ({type(e).__name__}). Use regional soil knowledge instead."}
    nice = {"phh2o": ("pH (water)", ""), "soc": ("Organic carbon", "g/kg"), "clay": ("Clay", "%"),
            "sand": ("Sand", "%"), "silt": ("Silt", "%"), "nitrogen": ("Total nitrogen", "g/kg"),
            "cec": ("Cation exchange capacity", "cmol/kg")}
    out: dict[str, Any] = {}
    for L in layers:
        f = L.get("unit_measure", {}).get("d_factor", 1) or 1
        name, unit = nice.get(L["name"], (L["name"], ""))
        for dep in L.get("depths", []):
            v = dep.get("values", {}).get("mean")
            if v is not None:
                out.setdefault(name, {})[dep["label"]] = f"{round(v / f, 2)} {unit}".strip()
    if not out:
        return {"note": "SoilGrids has no data for this exact point (often urban/water). Use regional soil knowledge.",
                "latitude": latitude, "longitude": longitude}
    return {"source": "ISRIC SoilGrids 250m (modelled)", "latitude": latitude, "longitude": longitude,
            "properties": out}


# ───────────────────────────── crop calendar KB ─────────────────────────────
INDIA_SEASONS = {
    "Kharif (monsoon)": {"sow": "Jun–Jul", "harvest": "Sep–Oct",
                         "crops": "rice, maize, pearl millet (bajra), sorghum, cotton, soybean, groundnut, pigeon pea, green gram, sugarcane"},
    "Rabi (winter)": {"sow": "Oct–Dec", "harvest": "Feb–Apr",
                      "crops": "wheat, barley, mustard, chickpea, lentil, peas, potato, onion"},
    "Zaid (summer)": {"sow": "Mar–Apr", "harvest": "May–Jun",
                      "crops": "watermelon, muskmelon, cucumber, moong, fodder, vegetables (irrigated)"},
}
STATE_NOTES = {
    "Punjab": "Alluvial loam; canal + tubewell irrigation; rice–wheat system; falling groundwater, stubble burning issue.",
    "Haryana": "Alluvial/sandy loam; rice–wheat, mustard, cotton (south-west); groundwater stress.",
    "Rajasthan": "Arid/semi-arid, sandy soils, 250–600 mm rain; bajra, guar (cluster bean), moth bean, mustard, cumin.",
    "Gujarat": "Black & alluvial soils; cotton, groundnut, castor, cumin; drip adoption high.",
    "Maharashtra": "Deccan black (regur) soils; cotton, soybean, sugarcane, onion (Nashik), grapes, pomegranate; rain-shadow drought belt in Marathwada.",
    "Madhya Pradesh": "Black soils; soybean (Kharif), wheat & chickpea (Rabi).",
    "Uttar Pradesh": "Indo-Gangetic alluvium; wheat, rice, sugarcane, potato.",
    "Bihar": "Alluvial, flood-prone north; rice, wheat, maize, makhana, litchi.",
    "West Bengal": "Alluvial/laterite; rice (3 seasons), jute, potato, tea in north.",
    "Odisha": "Red/laterite, often acidic soils; rice, pulses; cyclone risk Oct–Nov.",
    "Andhra Pradesh": "Red & black soils, delta alluvium; rice, chilli, cotton, groundnut, aquaculture.",
    "Telangana": "Red/black soils; cotton, rice, maize, red gram.",
    "Karnataka": "Red & black soils; ragi, maize, coffee (Western Ghats), sugarcane, arecanut.",
    "Tamil Nadu": "Red/alluvial; Samba/Kuruvai rice (Cauvery delta), sugarcane, banana, coconut; NE monsoon Oct–Dec.",
    "Kerala": "Laterite, acidic soils; coconut, rubber, pepper, cardamom, rice; heavy SW monsoon.",
    "Assam": "Alluvial, acidic; tea, rice (Sali), jute; floods Jun–Sep.",
    "Himachal Pradesh": "Hill soils; apple, stone fruits, off-season vegetables.",
    "Uttarakhand": "Hill & Tarai soils; rice, wheat, millets (mandua), horticulture.",
    "Jammu and Kashmir": "Temperate; apple, saffron (Pampore), walnut, rice in valley.",
    "Chhattisgarh": "Red-yellow soils; 'rice bowl', minor millets.",
    "Jharkhand": "Acidic red soils, plateau; rice, pulses, vegetables; lime application common.",
}
GLOBAL_NOTES = {
    "Kenya": "Bimodal rains: long rains Mar–May, short rains Oct–Dec; maize, beans, tea, coffee; drought-prone ASALs.",
    "Ghana": "Major season Apr–Jul, minor Sep–Nov (south); cocoa, maize, cassava, yam; north is single season.",
    "Canada": "Short season May–Sep; canola, wheat, barley, pulses on Prairies; frost risk late May & early Sep.",
    "Brazil": "Soy (Sep–Jan), safrinha maize after soy; coffee, sugarcane; cerrado acidic soils need liming.",
    "Nigeria": "Rainy Apr–Oct; maize, sorghum, cassava, yam, rice.",
    "Italy": "Mediterranean; grapes, olives, durum wheat, tomatoes; hot dry summers.",
}


def tool_crop_calendar(region: str = "", month: str = "", **_) -> dict:
    month = month or dt.date.today().strftime("%B")
    hit_state = next((s for s in STATE_NOTES if s.lower() in region.lower()), None)
    hit_country = next((c for c in GLOBAL_NOTES if c.lower() in region.lower()), None)
    res: dict[str, Any] = {"region": region, "month": month, "source": "AgroNova crop-calendar KB (ICAR/FAO summaries)"}
    if hit_country:
        res["regional_notes"] = GLOBAL_NOTES[hit_country]
    else:
        res["india_seasons"] = INDIA_SEASONS
        if hit_state:
            res["regional_notes"] = STATE_NOTES[hit_state]
    res["advice"] = "Combine with live weather + soil tools and confirm varieties with local KVK / extension office."
    return res


def tool_geocode(query: str, **_) -> dict:
    hits = geocode(query, count=3)
    return {"results": hits} if hits else {"error": f"No place found for '{query}'."}


# ───────────────────────────── registry ─────────────────────────────
TOOL_SPECS = [
    {
        "name": "get_weather_forecast",
        "description": "Live weather (current + up to 16-day daily forecast) and near-surface soil moisture/temperature "
                       "for a place. Use whenever advice depends on rain, heat, frost, wind, irrigation timing, spraying "
                       "or harvest timing. Prefer latitude/longitude from the farm profile when available.",
        "parameters": {"type": "object", "properties": {
            "location": {"type": "string", "description": "Place name, e.g. 'Nashik, Maharashtra' (if no coordinates)"},
            "latitude": {"type": "number"}, "longitude": {"type": "number"},
            "days": {"type": "integer", "description": "Forecast days 1-16 (default 7)"}}},
        "fn": tool_weather, "label": "Checking live weather",
    },
    {
        "name": "get_soil_properties",
        "description": "Modelled topsoil properties (pH, organic carbon, clay/sand/silt, nitrogen, CEC) at a coordinate "
                       "from ISRIC SoilGrids. Use for soil, fertilizer, liming or crop-suitability questions.",
        "parameters": {"type": "object", "properties": {
            "latitude": {"type": "number"}, "longitude": {"type": "number"}},
            "required": ["latitude", "longitude"]},
        "fn": tool_soil, "label": "Reading soil profile",
    },
    {
        "name": "get_crop_calendar",
        "description": "Season / sowing-window knowledge and regional agronomy notes for an Indian state or country.",
        "parameters": {"type": "object", "properties": {
            "region": {"type": "string", "description": "State or country, e.g. 'Rajasthan' or 'Kenya'"},
            "month": {"type": "string", "description": "Month name, default current month"}},
            "required": ["region"]},
        "fn": tool_crop_calendar, "label": "Consulting crop calendar",
    },
    {
        "name": "geocode_place",
        "description": "Find coordinates, district and state for a place name.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "fn": tool_geocode, "label": "Locating place",
    },
]
TOOLS = {t["name"]: t for t in TOOL_SPECS}


def run_tool(name: str, args: dict) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"Unknown tool {name}"}
    try:
        return spec["fn"](**args)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
