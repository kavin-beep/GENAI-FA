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
        "hourly": "soil_moisture_0_to_1cm,soil_moisture_3_to_9cm,soil_temperature_6cm,relative_humidity_2m,temperature_2m,"
                  "precipitation_probability,leaf_wetness_probability",
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


HUBS = [("Ludhiana", "Punjab", 30.90, 75.85), ("Nashik", "Maharashtra", 19.99, 73.79), ("Thanjavur", "Tamil Nadu", 10.79, 79.14),
        ("Jodhpur", "Rajasthan", 26.24, 73.02), ("Guntur", "Andhra Pradesh", 16.31, 80.44), ("Jorhat", "Assam", 26.75, 94.20)]


def hubs_now() -> list[dict]:
    """Live current conditions + today's outlook for major Indian farming hubs (one batched Open-Meteo call)."""
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=TIMEOUT, headers=UA, params={
        "latitude": ",".join(str(h[2]) for h in HUBS), "longitude": ",".join(str(h[3]) for h in HUBS), "timezone": "auto",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "daily": "precipitation_probability_max,precipitation_sum,temperature_2m_max,temperature_2m_min", "forecast_days": 1})
    r.raise_for_status()
    data = r.json()
    data = data if isinstance(data, list) else [data]
    out = []
    for (name, st_, lat, lon), d in zip(HUBS, data):
        c, dd = d["current"], d["daily"]
        out.append({"name": name, "state": st_, "temp": c["temperature_2m"], "rh": c["relative_humidity_2m"],
                    "wind": c["wind_speed_10m"], "sky": describe_code(c["weather_code"])[0],
                    "rain_prob": dd["precipitation_probability_max"][0] or 0, "rain": dd["precipitation_sum"][0] or 0,
                    "tmax": dd["temperature_2m_max"][0], "tmin": dd["temperature_2m_min"][0]})
    return out


def tool_geocode(query: str, **_) -> dict:
    hits = geocode(query, count=3)
    return {"results": hits} if hits else {"error": f"No place found for '{query}'."}


# ───────────────────────────── real-time clock ─────────────────────────────
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


def now_ist() -> dt.datetime:
    """Current time in India regardless of the server's own timezone (Streamlit Cloud runs on UTC)."""
    return dt.datetime.now(IST)


def tool_local_time(location: str = "", latitude: float | None = None, longitude: float | None = None, **_) -> dict:
    """Exact local date/time, timezone, sunrise, sunset and day length for any place (live)."""
    place = None
    if (latitude is None or longitude is None) and location:
        hits = geocode(location, count=1)
        if not hits:
            return {"error": f"Could not find '{location}'."}
        place = hits[0]
        latitude, longitude = place["latitude"], place["longitude"]
    if latitude is None or longitude is None:
        n = now_ist()
        return {"place": "India (IST)", "local_time": n.strftime("%H:%M"), "date": n.strftime("%A, %d %B %Y"),
                "timezone": "Asia/Kolkata (UTC+05:30)"}
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=TIMEOUT, headers=UA, params={
        "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 2,
        "daily": "sunrise,sunset,daylight_duration"})
    r.raise_for_status()
    d = r.json()
    off = dt.timedelta(seconds=d.get("utc_offset_seconds", 0))
    local = dt.datetime.now(dt.timezone.utc) + off
    daily = d.get("daily", {})
    sr, ss = (daily.get("sunrise") or [""])[0], (daily.get("sunset") or [""])[0]
    hours = off.total_seconds() / 3600
    out = {"place": place or {"latitude": latitude, "longitude": longitude},
           "local_time": local.strftime("%H:%M"), "date": local.strftime("%A, %d %B %Y"),
           "timezone": f"{d.get('timezone')} (UTC{'+' if hours >= 0 else '-'}{int(abs(hours)):02d}:{int(abs(hours) % 1 * 60):02d})",
           "sunrise": sr[-5:], "sunset": ss[-5:],
           "daylight_hours": round((daily.get("daylight_duration") or [0])[0] / 3600, 1)}
    if sr and ss:
        t = local.strftime("%Y-%m-%dT%H:%M")
        out["is_daytime"] = sr <= t <= ss
        out["note"] = ("Daylight now." if out["is_daytime"] else "It is dark now. If a spray is needed, plan it for "
                       "early morning or dusk tomorrow, when wind is calm and bees are least active.")
    return out


# ───────────────────────────── reference images (Wikipedia / Wikimedia Commons) ─────────────────────────────
WIKI_UA = {"User-Agent": "AgroNova-SmartFarming/1.0 (educational farming assistant)"}
_TAG = __import__("re").compile(r"<[^>]+>")


def tool_reference_images(query: str, count: int = 4, **_) -> dict:
    """Real, openly-licensed photos for a pest, disease, deficiency, crop, variety, tool or practice."""
    count = max(1, min(int(count or 4), 6))
    images, seen = [], set()
    try:  # 1) Wikipedia articles' lead images: most reliable for "what does X look like"
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=WIKI_UA, timeout=TIMEOUT, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": query, "gsrlimit": 6,
            "prop": "pageimages|info|description", "piprop": "thumbnail", "pithumbsize": 640, "inprop": "url"})
        pages = sorted((r.json().get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for p in pages:
            th = (p.get("thumbnail") or {}).get("source")
            if th and th not in seen and not th.lower().endswith((".svg", ".svg.png")):
                seen.add(th)
                images.append({"url": th, "title": p.get("title"), "caption": p.get("description") or p.get("title"),
                               "page": p.get("fullurl"), "source": "Wikipedia", "license": "see source page"})
    except Exception:
        pass
    if len(images) < count:
        try:  # 2) Wikimedia Commons photos, with license and author
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_UA, timeout=TIMEOUT, params={
                "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": 6, "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 640})
            for p in (r.json().get("query") or {}).get("pages", {}).values():
                ii = (p.get("imageinfo") or [{}])[0]
                th, md = ii.get("thumburl"), ii.get("extmetadata", {})
                if not th or th in seen or not ii.get("url", "").lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue
                seen.add(th)
                images.append({"url": th, "title": p.get("title", "").replace("File:", "").rsplit(".", 1)[0],
                               "caption": _TAG.sub("", (md.get("ImageDescription") or {}).get("value", ""))[:140],
                               "page": ii.get("descriptionurl"), "source": "Wikimedia Commons",
                               "license": (md.get("LicenseShortName") or {}).get("value", ""),
                               "author": _TAG.sub("", (md.get("Artist") or {}).get("value", "")).strip()[:60]})
                if len(images) >= count:
                    break
        except Exception:
            pass
    # Relevance: keep photos whose title shares a meaningful word with the query (drops generic/unrelated articles)
    generic = {"damage", "leaf", "leaves", "larva", "larvae", "plant", "plants", "crop", "crops", "symptom", "symptoms",
               "photo", "picture", "disease", "pest", "field", "with", "from", "india", "indian", "farm"}
    keys = [w for w in __import__("re").findall(r"[a-z]{4,}", query.lower()) if w not in generic]
    if keys:
        rel = [im for im in images if any(k in (im.get("title") or "").lower() for k in keys)]
        if rel:
            images = rel
    images = images[:count]
    if not images:
        return {"error": f"No openly-licensed reference photos found for '{query}'. Describe the symptoms in words."}
    return {"query": query, "images": images,
            "note": "These photos are shown to the farmer below your answer. Refer to them (e.g. 'see the reference "
                    "photos'); do not paste image links yourself."}


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
    {
        "name": "get_local_time",
        "description": "Exact current local date and time, timezone, sunrise, sunset, day length and whether it is daytime "
                       "for any place. Use for 'what time/date is it', sunrise/sunset, spraying or irrigation timing "
                       "today, or times in other countries (Kenya, Ghana, Canada…).",
        "parameters": {"type": "object", "properties": {
            "location": {"type": "string", "description": "Place name if no coordinates"},
            "latitude": {"type": "number"}, "longitude": {"type": "number"}}},
        "fn": tool_local_time, "label": "Checking local time",
    },
    {
        "name": "find_reference_images",
        "description": "Find real, openly-licensed reference photos (Wikipedia / Wikimedia Commons) of a pest, disease, "
                       "nutrient deficiency, weed, crop, variety, tool or practice. Use whenever a picture would help the "
                       "farmer recognise or do something. Search with the precise English or scientific name, e.g. "
                       "'Alternaria solani tomato leaf', 'pink bollworm cotton', 'drip irrigation'. The photos are shown "
                       "below your answer automatically.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Precise English / scientific search terms"},
            "count": {"type": "integer", "description": "Number of photos, 1-6 (default 4)"}},
            "required": ["query"]},
        "fn": tool_reference_images, "label": "Finding reference photos",
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
