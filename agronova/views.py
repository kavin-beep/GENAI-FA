"""All pages of the AgroNova app."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import time
import uuid

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import llm, prompts, state, theme, tools
from .map_component import india_map

# Warm "field journal" chart palette
GOLD, LEAF, SKY, CLAY, CREAM, MUT = "#e8b04a", "#a9d46f", "#8fc3d6", "#d4693f", "#f2ead9", "#a59c8a"
SERIES = [GOLD, LEAF, SKY, CLAY, "#c9a7e8", "#f3c978"]
RULE = "rgba(242,234,217,.07)"
PLOT_LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                   font=dict(family="Inter Tight, sans-serif", color=MUT, size=12),
                   title_font=dict(family="Instrument Serif, serif", size=22, color=CREAM),
                   margin=dict(l=8, r=8, t=56, b=8), hoverlabel=dict(bgcolor="#211b14", bordercolor="#211b14", font_color=CREAM),
                   xaxis=dict(gridcolor=RULE, zeroline=False, linecolor=RULE), yaxis=dict(gridcolor=RULE, zeroline=False),
                   legend=dict(orientation="h", y=1.1, x=0, font=dict(family="JetBrains Mono", size=10)), colorway=SERIES)
NOBAR = {"displayModeBar": False}
AV_USER, AV_AI = ":material/person:", ":material/eco:"


# ═════════════════════════════ shared helpers ═════════════════════════════
@st.cache_resource(show_spinner=False)
def _client(key: str):
    return llm.make_client(key)


def client_or_warn():
    """The AI is built in: the app's own key comes from server secrets, so visitors never see or enter one."""
    key = state.api_key()
    if not key:
        with st.container(key="panel_nokey"):
            st.markdown("#### AI is resting")
            st.markdown("AgroNova's assistant is offline at the moment. The map, live weather and soil data still work. "
                        "Please try again shortly.")
            st.caption("Site owner: set GROQ_API_KEY in Streamlit secrets.")
        return None
    return _client(key)


# Read-aloud voices (BCP-47). Order matters: more specific names first. Browsers fall back to a related voice if a
# device lacks one (e.g. Devanagari languages → Hindi voice).
LANG_CODES = {"Hinglish": "hi-IN", "Assamese": "as-IN", "Bengali": "bn-IN", "Bodo": "brx-IN", "Dogri": "doi-IN",
              "Gujarati": "gu-IN", "Hindi": "hi-IN", "Kannada": "kn-IN", "Kashmiri": "ks-IN", "Konkani": "kok-IN",
              "Maithili": "mai-IN", "Malayalam": "ml-IN", "Manipuri": "mni-IN", "Marathi": "mr-IN", "Nepali": "ne-NP",
              "Odia": "or-IN", "Punjabi": "pa-IN", "Sanskrit": "sa-IN", "Santali": "sat-IN", "Sindhi": "sd-IN",
              "Tamil": "ta-IN", "Telugu": "te-IN", "Urdu": "ur-IN", "Bhojpuri": "bho-IN", "Rajasthani": "raj-IN",
              "Haryanvi": "bgc-IN", "Chhattisgarhi": "hne-IN", "Tulu": "tcy-IN", "Khasi": "kha-IN", "Mizo": "lus-IN",
              "Kiswahili": "sw-KE", "Français": "fr-FR", "Português": "pt-BR", "Español": "es-ES", "Twi": "en-GH",
              "English": "en-IN"}
CITE = re.compile(r"【[^】]*】")


def clean_answer(text: str) -> str:
    """Remove the model's raw browsing citation markers (sources are listed separately)."""
    return CITE.sub("", text)


SCRIPTS = [((0x0900, 0x097F), "hi-IN"), ((0x0980, 0x09FF), "bn-IN"), ((0x0A00, 0x0A7F), "pa-IN"), ((0x0A80, 0x0AFF), "gu-IN"),
           ((0x0B00, 0x0B7F), "or-IN"), ((0x0B80, 0x0BFF), "ta-IN"), ((0x0C00, 0x0C7F), "te-IN"), ((0x0C80, 0x0CFF), "kn-IN"),
           ((0x0D00, 0x0D7F), "ml-IN"), ((0x0600, 0x06FF), "ur-IN"), ((0x1C50, 0x1C7F), "sat-IN"), ((0xABC0, 0xABFF), "mni-IN")]


def lang_code(text: str = "") -> str:
    """Voice for read-aloud: the chosen language, or (in Auto mode) detected from the answer's script."""
    lang = st.session_state.get("language", "English")
    if not lang.startswith("Auto"):
        return next((v for k, v in LANG_CODES.items() if k in lang), "en-IN")
    counts = {}
    for ch in text[:1500]:
        o = ord(ch)
        for (a, b), code in SCRIPTS:
            if a <= o <= b:
                counts[code] = counts.get(code, 0) + 1
    if counts:
        code = max(counts, key=counts.get)
        if code == "hi-IN" and any(w in text for w in ("आहे", "नाही", "करा ", "मध्ये")):
            return "mr-IN"          # Marathi shares the Devanagari script
        if code == "hi-IN" and any(w in text for w in ("छ ", "गर्नु", "हुन्छ")):
            return "ne-NP"          # Nepali
        if code == "bn-IN" and any(ch in text for ch in "ৰৱ"):
            return "as-IN"          # Assamese uses ৰ and ৱ, which Bengali doesn't
        return code
    low = text.lower()
    if any(w in low for w in (" na ", " ya ", "mazao", "mvua")):
        return "sw-KE"
    if any(w in low for w in (" le ", " les ", " des ", " est ")):
        return "fr-FR"
    if any(w in low for w in (" para ", " não ", " você ")):
        return "pt-BR"
    if any(w in low for w in (" el ", " los ", " para ", " qué ")):
        return "es-ES"
    return "en-IN"


def speak_button(text: str, key: str, autoplay: bool = False, lang: str | None = None) -> None:
    """Read-aloud using the device's own voices (covers Indian languages on Android/Chrome/Edge).

    autoplay=True speaks immediately, once (used when the farmer asked by voice). `lang` overrides the voice language,
    e.g. the language Whisper heard; otherwise it comes from the reply-language setting or the answer's script."""
    plain = re.sub(r"\|[-: |]+\|", " ", text)
    plain = re.sub(r"[#*_`>|]+", " ", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"\s+", " ", plain).strip()[:4000]
    payload = json.dumps(plain)
    code = lang or lang_code(plain)
    auto_js = ""
    if autoplay:
        auto_js = ("try { if(!P.sessionStorage.getItem(KEY)) { P.sessionStorage.setItem(KEY,'1');"
                   " const go=()=>setTimeout(speak,350); if(S.getVoices().length) go();"
                   " else { S.onvoiceschanged=go; setTimeout(go,1200); } } } catch(e) {}")
    st.iframe(f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500&display=swap" rel="stylesheet">
<style>html,body{{margin:0;background:transparent;overflow:hidden}}
button{{font:500 13px 'Inter Tight',sans-serif;color:#f2ead9;background:#211b14;border:0;border-radius:999px;height:34px;padding:0 14px;
cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:background .3s}}button:hover{{background:#2b231a}}
i{{width:7px;height:7px;border-radius:50%;background:#a59c8a}}button.on i{{background:#e8b04a;animation:p 1s infinite}}
@keyframes p{{50%{{opacity:.3}}}}</style></head><body>
<button id="b" title="Voice: {code}"><i></i><span>Listen</span></button>
<script>
const P=window.parent||window, S=P.speechSynthesis, U=P.SpeechSynthesisUtterance;
const b=document.getElementById('b'), t=b.querySelector('span'), text={payload}, lang="{code}", KEY="agro_spoken_{key}";
function reset(){{b.classList.remove('on');t.textContent='Listen';}}
function pickVoice(){{ const vs=S.getVoices(); return vs.find(v=>v.lang.toLowerCase()===lang.toLowerCase())
  || vs.find(v=>v.lang.toLowerCase().startsWith(lang.slice(0,2).toLowerCase()))
  || (lang.endsWith('-IN') ? vs.find(v=>v.lang==='hi-IN') : null); }}
function speak(){{ S.cancel(); const parts=text.match(/[^.!?।॥]+[.!?।॥]?/g)||[text];
  const v=pickVoice(); let i=0;
  const next=()=>{{ if(i>=parts.length){{reset();return;}} const u=new U(parts[i++].trim()); u.lang=lang; u.rate=.96; if(v) u.voice=v;
    u.onend=next; u.onerror=reset; S.speak(u); }};
  b.classList.add('on'); t.textContent='Stop'; next(); }}
b.onclick=()=>{{ if(S.speaking){{S.cancel();reset();return;}} speak(); }};
{auto_js}
</script></body></html>""", height=38)


def gallery_html(images: list[dict]) -> str:
    """Reference photos the AI found (Wikipedia / Wikimedia Commons), with captions and attribution."""
    if not images:
        return ""
    cards = []
    for im in images[:6]:
        cap = html.escape((im.get("title") or "")[:60])
        meta = [x for x in [im.get("source"), im.get("license"), im.get("author")] if x and x != "see source page"]
        sub = html.escape(" · ".join(meta)[:80])
        cards.append(f"<a class='gimg' href='{html.escape(im.get('page') or im['url'])}' target='_blank' rel='noopener'>"
                     f"<img src='{html.escape(im['url'])}' alt='{cap}' loading='lazy'/><b>{cap}</b><span>{sub}</span></a>")
    return "<div class='gal'><span class='lab'>Reference photos</span><div class='gal-row'>" + "".join(cards) + "</div></div>"


def sources_html(srcs: list[dict]) -> str:
    if not srcs:
        return ""
    items = []
    for s in srcs[:6]:
        host = s["url"].split("/")[2].replace("www.", "") if s["url"].startswith("http") else s["url"]
        title = html.escape((s.get("title") or host)[:70])
        items.append(f"<a href='{html.escape(s['url'])}' target='_blank' rel='noopener'><b>{html.escape(host)}</b><span>{title}</span></a>")
    return "<div class='srcs'><span class='lab'>Sources</span>" + "".join(items) + "</div>"


@st.cache_data(ttl=600, show_spinner=False)
def forecast(lat: float, lon: float, days: int = 10) -> dict:
    return tools.fetch_forecast(lat, lon, days)


@st.cache_data(ttl=600, show_spinner=False)
def live_hubs() -> list[dict]:
    return tools.hubs_now()


def tool_chips(trace: list[dict]) -> str:
    if not trace:
        return ""
    out = []
    for t in trace:
        arg = t.get("args", {})
        where = arg.get("location") or arg.get("region") or arg.get("query") or (
            f"{arg['latitude']:.2f}, {arg['longitude']:.2f}" if "latitude" in arg and "longitude" in arg else "")
        done = t.get("ms") is not None
        tail = f" · {t['ms']} ms" if done and t["ms"] else ""
        out.append(f"<span class='{'ok' if done else ''}'>{html.escape(t['label'])}"
                   f"{(' — ' + html.escape(str(where))) if where else ''}{tail}</span>")
    return "<div class='trace'>" + "".join(out) + "</div>"


def render_stream(events, container) -> dict:
    """Render agent events live inside `container`; returns the finished assistant message."""
    with container:
        trace_ph, think_slot, answer_ph, gal_ph, src_ph = st.empty(), st.empty(), st.empty(), st.empty(), st.empty()
        answer_ph.html("<div class='typing'><i></i><i></i><i></i></div>")
    text, thoughts, trace, usage, status, think_ph, sources, images = "", "", [], {}, None, None, [], []
    t0, last = time.time(), 0.0
    for ev in events:
        if ev.kind == "sources":
            sources += ev.data
            src_ph.html(sources_html(sources))
            continue
        if ev.kind == "images":
            known = {x["url"] for x in images}
            images += [im for im in ev.data if im["url"] not in known]
            gal_ph.html(gallery_html(images))
            continue
        if ev.kind == "thought":
            thoughts += ev.data
            if status is None:
                status = think_slot.status("Thinking", expanded=False)
                with status:
                    think_ph = st.empty()
            think_ph.markdown(thoughts)
        elif ev.kind == "text":
            text += ev.data
            if time.time() - last > 0.04:
                answer_ph.markdown(clean_answer(text) + " ▍")
                last = time.time()
        elif ev.kind == "tool_call":
            trace.append({**ev.data, "ms": None})
            trace_ph.html(tool_chips(trace))
        elif ev.kind == "tool_result":
            for t in reversed(trace):
                if t["name"] == ev.data["name"] and t["ms"] is None:
                    t["ms"] = ev.data["ms"]
                    break
            trace_ph.html(tool_chips(trace))
        elif ev.kind == "usage":
            usage = ev.data
        elif ev.kind == "error":
            text += f"\n\n> {ev.data}"
    if status is not None:
        status.update(label=f"Thought for {max(1, round(time.time() - t0))}s", state="complete", expanded=False)
    text = clean_answer(text)
    answer_ph.markdown(text or "_No answer came back. Try again, or pick another model in the sidebar._")
    return {"role": "assistant", "content": text, "thoughts": thoughts, "tools": trace, "usage": usage,
            "sources": sources, "images": images, "model": usage.get("model") or state.settings().model,
            "id": uuid.uuid4().hex[:10]}


BASELINE_PATH = state.LOG_PATH.parent / "baseline.json"
TOOL_LABELS = {"get_weather_forecast": "Checked live weather", "get_soil_properties": "Read soil profile",
               "get_crop_calendar": "Consulted crop calendar", "geocode_place": "Located place", "web_search": "Searched the web",
               "web_open": "Read a web page", "code": "Ran a calculation", "transcribe": "Transcribed voice", "vision": "Looked at photo",
               "get_local_time": "Checked local time", "find_reference_images": "Found reference photos"}


@st.cache_data(show_spinner=False)
def baseline() -> dict:
    """A real, saved run of the AI (data/baseline.json) so pages show genuine results before anyone runs anything."""
    try:
        b = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    # Only ever show genuine answers: drop entries that were rate-limit/error messages or failed grading
    def ok(t):
        t = (t or "").strip()
        return len(t) >= 300 and not t.startswith(("⏳", "⚠️", "🔑", "🧩", "🌩️"))
    b["validation"] = [r for r in b.get("validation", []) if ok(r.get("answer")) and r.get("region_score") not in (None, 1)]
    b["modules"] = {k: m for k, m in (b.get("modules") or {}).items() if ok(m.get("answer"))}
    ab = b.get("ab")
    if not ab or not ok(ab["a"][0]) or not ok(ab["b"][0]) or not ab["b"][2] or ab["b"][2].get("region") == 1:
        b["ab"] = None
    return b


def baseline_label() -> str:
    b = baseline()
    return f"{b.get('model', '').split('/')[-1]} · {b.get('generated', '')}" if b else ""


def track_page(name: str) -> None:
    """Log one page view per page per session, so the Usage monitor reflects real activity."""
    seen = st.session_state.setdefault("_pages_seen", set())
    if name not in seen:
        seen.add(name)
        state.log("page_view", feature=name)


def system_prompt(extra: str = "") -> str:
    return prompts.SYSTEM_PROMPT + "\n\n" + prompts.farm_context(st.session_state.profile, st.session_state.language) + extra


def location_chip() -> None:
    lab = state.place_label()
    now = tools.now_ist()
    clock = f"<span class='loc clock'>Live · {now:%H:%M} IST · {now:%a %d %b}</span>"
    if lab:
        p = st.session_state.profile
        st.html(f"<div class='chips'><span class='loc on'>{html.escape(lab)} &nbsp;·&nbsp; {p['lat']:.3f}, {p['lon']:.3f}</span>{clock}</div>")
    else:
        st.html(f"<div class='chips'><span class='loc'>No farm pinned — set one in Farm Locator</span>{clock}</div>")


def footer():
    st.html("""<footer class="foot2">
      <div class="mark">Agro<em>Nova</em></div>
      <div><h6>Data</h6><p>Groq API · gpt-oss</p><p>Open-Meteo forecast</p><p>ISRIC SoilGrids</p><p>2011 census districts</p></div>
      <div><h6>Imagery & note</h6><p>Footage: Mixkit · Photos: Unsplash · Maps: Esri, OSM</p>
        <p style="margin-top:.8rem">Guidance, not a guarantee. Confirm big decisions with your local KVK — Kisan Call Centre 1800-180-1551.</p></div>
    </footer>""")


# ═════════════════════════════ HOME ═════════════════════════════
def page_home():
    track_page("home")
    theme.hero()
    theme.ticker(["Crop recommendation", "Pest & disease doctor", "Weather-smart alerts", "Soil & fertilizer",
                  "Sustainable farming", "Live market prices", "Sixteen languages", "Photo diagnosis", "Voice questions"])

    # ── Ask box: the fastest way in ──
    st.html("<div id='ask'></div>")
    with st.container(key="panel_ask"):
        st.html("<div class='kicker'><b>→</b><span>Ask AgroNova</span></div>"
                "<h2 class='h2' style='margin:.5rem 0 1rem'>What's happening <em>in your field</em> today?</h2>")
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        q = c1.text_input("Your question", placeholder="e.g. Yellow leaves on my tomato plants in Pune — what should I do?",
                          label_visibility="collapsed", key="home_q")
        if c2.button("Ask", type="primary", width="stretch", icon=":material/arrow_upward:") and q.strip():
            st.session_state.queued = {"text": q.strip(), "attachments": []}
            st.switch_page(PAGES["chat"])
        sug = ["Best crop to sow this month in Punjab?", "Onion price at Lasalgaon today?", "Organic fix for whitefly on cotton?"]
        sc = st.columns(3)
        for i, s_ in enumerate(sug):
            if sc[i].button(s_, key=f"hs{i}", width="stretch", icon=":material/north_east:"):
                st.session_state.queued = {"text": s_, "attachments": []}
                st.switch_page(PAGES["chat"])

    # ── Live India farm pulse (real weather right now) ──
    theme.section("00", "Live · India farm pulse", "Right now, <em>across the fields.</em>",
                  "Live conditions at six major farming hubs, with today's rain chance and whether it's a good day to spray "
                  "(rain chance under 30 %, wind under 15 km/h). Refreshed every 10 minutes from Open-Meteo.")
    try:
        hubs = live_hubs()
    except Exception:
        hubs = []
    if hubs:
        cards = "".join(
            f"""<div class="hub"><div class="hn">{html.escape(h['name'])}</div><div class="hs">{html.escape(h['state'])}</div>
            <div class="ht">{h['temp']:.0f}°<small> {h['tmin']:.0f}–{h['tmax']:.0f}°</small></div><div class="hk">{html.escape(h['sky'])}</div>
            <div class="hm">Humidity {h['rh']:.0f}% · Wind {h['wind']:.0f} km/h<br>Rain today {h['rain_prob']:.0f}%</div>
            <span class="tg {'leaf' if h['rain_prob'] < 30 and h['wind'] < 15 else 'clay'}">{'Good to spray' if h['rain_prob'] < 30 and h['wind'] < 15 else 'Hold spraying'}</span></div>"""
            for h in hubs)
        st.html(f"<div class='hubs reveal'>{cards}</div>")
        st.caption(f"Live · updated {dt.datetime.now():%H:%M} · tap Farm Locator to get this for your own field")

    # ── This month in the field ──
    month = dt.date.today()
    season = prompts.season_for(month)
    sow_now = [n for n, v in tools.INDIA_SEASONS.items() if month.strftime("%b") in v["sow"] or
               (n.startswith("Rabi") and month.month in (10, 11, 12)) or (n.startswith("Kharif") and month.month in (6, 7)) or
               (n.startswith("Zaid") and month.month in (3, 4))]
    harvest_now = [n for n, v in tools.INDIA_SEASONS.items() if (n.startswith("Kharif") and month.month in (9, 10, 11)) or
                   (n.startswith("Rabi") and month.month in (2, 3, 4)) or (n.startswith("Zaid") and month.month in (5, 6))]
    def crops(names):
        return ", ".join(tools.INDIA_SEASONS[n]["crops"] for n in names) or "—"
    st.html(f"""<div class="duo month reveal" style="margin:3.5rem 0 1rem">
      <div><div class="kicker"><b>{month:%b}</b><span>This month in the field · India</span></div>
        <h2 class="h2">It's <em>{season.split(' (')[0]}</em> season.</h2>
        <p class="dek">{season}. Here's what farmers across India are doing in {month:%B}.</p></div>
      <div class="steps">
        <div><i>sow</i><p><b>Sowing now</b><span>{html.escape(crops(sow_now))}</span></p></div>
        <div><i>reap</i><p><b>Harvesting now</b><span>{html.escape(crops(harvest_now))}</span></p></div>
        <div><i>tip</i><p><b>This week's habit</b><span>Check the field planner before spraying: wind and rain decide whether a spray works or washes off.</span></p></div>
      </div></div>""")

    theme.manifesto("Every answer starts with the field — the soil under it, the sky above it, "
                    "and the farmer standing in it. Nothing is guessed when it can be measured.",
                    {"soil", "sky", "farmer", "measured."})

    theme.section("01", "Six modules", "One assistant, <em>every season.</em>",
                  "Each module is a carefully engineered prompt that fetches live data before it answers. "
                  "They were designed in the FA-1 storyboard and tested in FA-2.")
    rows = "".join(
        f"""<div class="row" data-img="{f['img']}"><span class="n">0{i + 1}</span><span class="ti">{f['title']}</span>
        <span class="de">{f['tagline']}</span><span class="ar">→</span><img class="th" src="{f['img']}" alt="" loading="lazy"/></div>"""
        for i, f in enumerate(prompts.FEATURES.values()))
    st.html(f"<div class='idx reveal'>{rows}</div>")
    c1, c2, c3 = st.columns(3)
    c1.page_link(PAGES["studio"], label="Open the Feature Studio", icon=":material/arrow_outward:", width="stretch")
    c2.page_link(PAGES["chat"], label="Talk to AgroNova", icon=":material/arrow_outward:", width="stretch")
    c3.page_link(PAGES["map"], label="Pin your farm", icon=":material/arrow_outward:", width="stretch")

    st.html(f"""
    <div class="duo">
      <div class="reveal"><figure class="tilt"><video autoplay muted loop playsinline poster="{theme.IMG_GREEN}"><source src="{theme.FIELD_VIDEO}" type="video/mp4"/></video></figure>
        <div class="cap"><span>Fig. 1 — Monsoon fields</span><span>Mixkit footage</span></div></div>
      <div class="reveal"><div class="kicker"><b>02</b><span>How it thinks</span></div>
        <h2 class="h2">Reason, <em>fetch,</em> then answer.</h2>
        <p class="dek">It works like a senior agronomist: it plans before it speaks, and when it needs a fact it goes and gets it.</p>
        <div class="steps">
          <div><i>i.</i><p><b>Reads your farm</b><span>Your pinned district, crop stage, water source and preferences go into every question.</span></p></div>
          <div><i>ii.</i><p><b>Thinks it through</b><span>Open the "Thinking" note on any answer to see how it got there.</span></p></div>
          <div><i>iii.</i><p><b>Checks live sources</b><span>Open-Meteo forecasts, ISRIC soil grids and a crop calendar, so no numbers are made up.</span></p></div>
          <div><i>iv.</i><p><b>Explains why</b><span>Short steps and tables, with a reason for each one, in your language.</span></p></div>
        </div></div>
    </div>""")

    st.html(f"""<div class="bignums reveal">
      <div><b data-count="758">0</b><span>Districts on the map</span></div><div><b data-count="37">0</b><span>Answer languages</span></div>
      <div><b data-count="7">0</b><span>Live AI tools</span></div><div><b data-count="3">0</b><span>Pilot countries</span></div></div>""")

    theme.section("03", "Built for real farms", "From Ludhiana <em>to Kumasi.</em>",
                  "The pilot covers India, Ghana and Canada. Ask in Hindi, Tamil, Swahili or French, send a photo of a sick leaf, "
                  "or record a voice note.")
    st.html(f"""<div class="strip reveal">
      <figure><img src="{theme.IMG_FARMERS}" alt="Farmers harvesting"/><div class="cap"><span>Fig. 2 — Harvest crew</span><span>Unsplash</span></div></figure>
      <figure><img src="{theme.IMG_SOIL}" alt="Soil and trowel"/><div class="cap"><span>Fig. 3 — Soil first</span></div></figure>
      <figure><img src="{theme.IMG_SEEDLING}" alt="Seedlings"/><div class="cap"><span>Fig. 4 — Nursery</span></div></figure>
    </div>""")
    footer()


# ═════════════════════════════ FARM LOCATOR ═════════════════════════════
def page_map():
    track_page("map")
    theme.page_header("02", "Farm Locator", "Pin your <em>exact</em> field.",
                      "Explore 758 districts, search any village, use GPS or tap a farming hub. Lock a spot and every answer "
                      "after that is tailored to it.", theme.IMG_ROWS, "Crop rows · Unsplash")
    prof = st.session_state.profile
    locked = {"lat": prof["lat"], "lon": prof["lon"], "district": prof["district"], "state": prof["state"]} if prof["lat"] is not None else None
    val = india_map(locked=locked, height=660, key="india_map")
    if val and val.get("ts") != st.session_state.map_ts:
        st.session_state.map_ts = val["ts"]
        prof.update(lat=val["lat"], lon=val["lon"], district=val.get("district", ""), state=val.get("state", ""),
                    country=val.get("country", "India"))
        state.log("location_locked", detail=f"{val.get('source')}:{val['lat']},{val['lon']}")
        st.toast(f"Farm locked — {state.place_label()}", icon=":material/check:")
        st.rerun()

    st.html("<div style='height:2.4rem'></div>")
    left, right = st.columns([1, 1.45], gap="large")
    with left:
        with st.container(key="panel_profile"):
            st.markdown("#### Farm profile")
            location_chip()
            with st.form("profile_form", border=False):
                crop = st.text_input("Main crop", prof.get("crop", ""), placeholder="Cotton, wheat, tomato…")
                stage = st.selectbox("Crop stage", ["", "Planning / before sowing", "Land preparation", "Sowing", "Seedling",
                                                    "Vegetative", "Flowering", "Fruiting / grain filling", "Harvest", "Post-harvest"])
                c1, c2 = st.columns(2)
                size = c1.text_input("Farm size", prof.get("farm_size", ""), placeholder="2 acres")
                water = c2.selectbox("Water", ["", "Rain-fed", "Canal", "Borewell / tubewell", "Drip", "Sprinkler", "Pond / tank"])
                prefs = st.multiselect("Preferences", ["Organic only", "Low cost", "Low water", "High market value",
                                                       "Quick harvest", "Export quality", "Mechanised"], default=prof.get("prefs", []))
                if st.form_submit_button("Save profile", type="primary", width="stretch"):
                    prof.update(crop=crop, stage=stage or prof.get("stage", ""), farm_size=size,
                                irrigation=water or prof.get("irrigation", ""), prefs=prefs)
                    state.log("profile_saved", detail=crop)
                    st.toast("Profile saved. Every answer will use it.", icon=":material/check:")
    with right:
        if prof["lat"] is None:
            with st.container(key="panel_wx_empty"):
                st.markdown("#### Live farm weather")
                st.html("<p class='h2' style='font-size:2rem;margin:.4rem 0'>Lock a spot on the map to see <em>its sky.</em></p>"
                        "<p class='dek'>You'll get a 10-day forecast, a 7-day field planner (spray, irrigate, alerts), "
                        "your real soil profile and the season calendar for that exact point.</p>")
                if st.button("Try it with a demo farm near Nashik", type="primary", icon=":material/agriculture:"):
                    prof.update(lat=20.2000, lon=73.8300, district="Nashik", state="Maharashtra", country="India",
                                crop=prof.get("crop") or "Onion", farm_size=prof.get("farm_size") or "2 acres")
                    state.log("location_locked", detail="demo:Dindori,Nashik")
                    st.rerun()
        else:
            weather_dashboard(prof["lat"], prof["lon"])
    if prof["lat"] is not None:
        farm_snapshot(prof)


# ───────── Farm snapshot: field planner, soil profile, season calendar, quick questions ─────────
def soil_profile(lat: float, lon: float) -> dict:
    """Cached soil lookup; failures (timeouts) are NOT cached, so the next view tries again."""
    try:
        return _soil_cached(round(lat, 4), round(lon, 4))
    except RuntimeError as e:
        return {"error": str(e)}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _soil_cached(lat: float, lon: float) -> dict:
    """Soil at the pin; if SoilGrids has no value there (towns, water), use the nearest farmland ~5 km away."""
    r = tools.tool_soil(latitude=lat, longitude=lon)
    if r.get("error"):
        r = tools.tool_soil(latitude=lat, longitude=lon)      # one retry: SoilGrids is sometimes slow
        if r.get("error"):
            raise RuntimeError(r["error"])
    if r.get("properties"):
        return r
    for dlat, dlon in [(0.05, 0), (0, 0.05), (-0.05, 0), (0, -0.05)]:
        r2 = tools.tool_soil(latitude=lat + dlat, longitude=lon + dlon)
        if r2.get("properties"):
            r2["nearby"] = True
            return r2
    return r


# name, pH low, pH high, seasons, ideal °C low, high, water need, prefers light soil  (ICAR/FAO agronomy summaries)
CROPS = [("Onion", 6.0, 7.5, ["Rabi", "Kharif"], 13, 30, "medium", False),
         ("Wheat", 6.0, 7.5, ["Rabi"], 10, 25, "medium", False),
         ("Chickpea (gram)", 6.0, 8.0, ["Rabi"], 10, 30, "low", False),
         ("Mustard", 6.0, 7.5, ["Rabi"], 10, 25, "low", False),
         ("Tomato", 6.0, 7.0, ["Rabi", "Zaid", "Kharif"], 18, 30, "medium", False),
         ("Grapes", 6.5, 8.0, ["perennial"], 15, 35, "medium", False),
         ("Soybean", 6.0, 7.5, ["Kharif"], 20, 32, "medium", False),
         ("Cotton", 6.0, 8.0, ["Kharif"], 21, 35, "medium", False),
         ("Pearl millet (bajra)", 6.0, 8.0, ["Kharif"], 25, 35, "low", True),
         ("Rice (paddy)", 5.0, 7.0, ["Kharif"], 20, 35, "high", False),
         ("Sugarcane", 6.0, 7.5, ["perennial"], 20, 35, "high", False),
         ("Groundnut", 6.0, 7.0, ["Kharif", "Zaid"], 22, 32, "low", True),
         ("Watermelon", 6.0, 7.0, ["Zaid"], 22, 35, "medium", True),
         ("Potato", 5.0, 6.5, ["Rabi"], 12, 24, "medium", True)]


def _num(s) -> float | None:
    try:
        return float(str(s).split()[0])
    except (ValueError, IndexError):
        return None


def field_plan(w: dict) -> list[dict]:
    """Rule-based 7-day planner from the live forecast (transparent agronomy rules, no AI needed)."""
    d = w["daily"]
    out = []
    for i, day in enumerate(d["time"][:7]):
        tmax, tmin = d["temperature_2m_max"][i], d["temperature_2m_min"][i]
        rain, prob = d["precipitation_sum"][i] or 0, d["precipitation_probability_max"][i] or 0
        wind, et0 = d["wind_speed_10m_max"][i] or 0, d["et0_fao_evapotranspiration"][i] or 0
        alerts = []
        if tmax >= 38: alerts.append(("Heatwave", "clay"))
        if tmin <= 4: alerts.append(("Frost risk", "sky"))
        if rain >= 20: alerts.append(("Heavy rain", "sky"))
        if wind >= 30: alerts.append(("Strong wind", "clay"))
        spray = prob < 30 and wind < 15 and tmax < 35 and rain < 1
        irrigate = rain < 2 and et0 >= 4
        out.append({"date": pd.to_datetime(day), "sky": tools.describe_code(d["weather_code"][i])[0], "tmax": tmax, "tmin": tmin,
                    "rain": rain, "prob": prob, "wind": wind, "et0": et0, "spray": spray, "irrigate": irrigate, "alerts": alerts})
    return out


def farm_snapshot(prof: dict):
    try:
        w = forecast(prof["lat"], prof["lon"], 10)
    except Exception:
        return
    plan = field_plan(w)
    theme.section("A", "Field planner", "Your next <em>seven days.</em>",
                  "Built from the live forecast with simple, transparent rules: spray when rain chance &lt; 30 %, wind &lt; 15 km/h "
                  "and it's below 35 °C; irrigate when rain &lt; 2 mm and evaporation ≥ 4 mm; flag heat, frost, heavy rain and wind.")
    cards = []
    for p in plan:
        tags = "".join(f"<span class='tg {c}'>{t}</span>" for t, c in p["alerts"])
        tags += "<span class='tg leaf'>Good to spray</span>" if p["spray"] else "<span class='tg dim'>Don't spray</span>"
        tags += "<span class='tg gold'>Irrigate</span>" if p["irrigate"] else ""
        cards.append(f"""<div class="day"><div class="dw">{p['date']:%a}</div><div class="dd">{p['date']:%d %b}</div>
          <div class="dt">{p['tmax']:.0f}°<small>/{p['tmin']:.0f}°</small></div><div class="ds">{html.escape(p['sky'])}</div>
          <div class="dm">Rain {p['rain']:.1f} mm · {p['prob']:.0f}%<br>Wind {p['wind']:.0f} km/h · ET₀ {p['et0']:.1f}</div>
          <div class="tgs">{tags}</div></div>""")
    st.html(f"<div class='week reveal'>{''.join(cards)}</div>")
    spray_days = [f"{p['date']:%a}" for p in plan if p["spray"]]
    irr_days = [f"{p['date']:%a}" for p in plan if p["irrigate"]]
    st.caption(f"Best spray days: {', '.join(spray_days) or 'none this week'} · Irrigation needed: {', '.join(irr_days) or 'no'}")

    left, right = st.columns([1, 1], gap="large")
    with left:
        with st.container(key="panel_soil"):
            st.markdown("#### Soil under your farm")
            soil = soil_profile(prof["lat"], prof["lon"])
            props = soil.get("properties") or {}
            if not props:
                st.html("<p class='dek'>SoilGrids has no modelled value for this exact point (common for towns and water). "
                        "Try pinning a nearby field.</p>")
            else:
                g = lambda k: _num((props.get(k) or {}).get("0-5cm"))
                ph, clay, sand, silt, soc = g("pH (water)"), g("Clay"), g("Sand"), g("Silt"), g("Organic carbon")
                ph_txt = ("strongly acidic — lime helps" if ph and ph < 5.5 else "slightly acidic" if ph and ph < 6.5 else
                          "neutral — ideal for most crops" if ph and ph <= 7.5 else "alkaline — watch zinc/iron" if ph else "—")
                tex = ("clayey — holds water, drains slowly" if (clay or 0) >= 35 else "sandy — drains fast, needs frequent water"
                       if (sand or 0) >= 60 else "loamy — balanced")
                m = st.columns(3)
                m[0].metric("pH", f"{ph:.1f}" if ph else "—")
                m[1].metric("Org. carbon g/kg", f"{soc:.0f}" if soc else "—")
                m[2].metric("Clay %", f"{clay:.0f}" if clay else "—")
                bars = "".join(f"<div style='flex:{v or 0.01};background:{c}' title='{n} {v:.0f}%'></div>"
                               for n, v, c in [("Clay", clay or 0, "#d4693f"), ("Silt", silt or 0, "#e8b04a"), ("Sand", sand or 0, "#f2ead9")])
                st.html(f"<div class='texture'>{bars}</div><div class='cap'><span>Clay · Silt · Sand</span><span>ISRIC SoilGrids, 0–5 cm</span></div>"
                        f"<p class='dek' style='margin-top:.8rem'>Your topsoil is <b>{ph_txt}</b> and <b>{tex}</b>."
                        + (" <i>(Measured at the nearest farmland, about 5 km from your pin.)</i>" if soil.get("nearby") else "") + "</p>")
    with right:
        with st.container(key="panel_season"):
            st.markdown("#### Season calendar")
            month = dt.date.today().month
            seasons = [("Kharif", 6, 10, "#a9d46f"), ("Rabi", 10, 3, "#e8b04a"), ("Zaid", 3, 6, "#8fc3d6")]
            rows = ""
            for name, a, b, col in seasons:
                cells = "".join(
                    f"<i class='{'on' if (a <= mth <= b if a <= b else (mth >= a or mth <= b)) else ''}{' now' if mth == month else ''}' "
                    f"style='--c:{col}'></i>" for mth in range(1, 13))
                rows += f"<div class='srow'><b>{name}</b><div class='months'>{cells}</div></div>"
            labels = "".join(f"<span{' class=now' if i + 1 == month else ''}>{m}</span>" for i, m in enumerate("JFMAMJJASOND"))
            note = tools.STATE_NOTES.get(prof.get("state", ""), "Pin a farm in India to see regional crop notes.")
            st.html(f"<div class='season'>{rows}<div class='srow'><b></b><div class='months lab'>{labels}</div></div></div>"
                    f"<p class='dek' style='margin-top:1rem'><b>{html.escape(prof.get('state') or '')}</b> — {html.escape(note)}</p>"
                    f"<p class='dek'>Now: <b>{prompts.season_for()}</b>.</p>")

    # ── 48-hour outlook + fungal disease risk ──
    h = w["hourly"]
    hh = pd.DataFrame({"time": pd.to_datetime(h["time"]), "temp": h.get("temperature_2m"), "rh": h.get("relative_humidity_2m"),
                       "rain": h.get("precipitation_probability"), "wet": h.get("leaf_wetness_probability")})
    now = (pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(seconds=w.get("utc_offset_seconds", 0))).floor("h")  # farm-local time
    hh = hh[hh["time"] >= now - pd.Timedelta(hours=1)].head(48)
    risky = hh[(hh["rh"] >= 85) & (hh["temp"].between(15, 30))]
    hours = len(risky)
    level, col, why = (("High", "clay", "long humid, mild spells — ideal for blight, mildew and leaf spot")
                       if hours >= 10 else ("Moderate", "gold", "some humid hours — scout lower leaves")
                       if hours >= 4 else ("Low", "leaf", "air stays too dry for most fungal spores to infect"))
    theme.section("C", "Next 48 hours", "Disease risk, <em>hour by hour.</em>",
                  "Fungal diseases need leaf wetness or humidity of at least 85 % at 15–30 °C for several hours. AgroNova counts those "
                  "hours in the live hourly forecast. It's a standard rule of thumb, not a lab test.")
    c1, c2 = st.columns([1, 2.2], gap="large")
    with c1:
        with st.container(key="panel_risk"):
            st.markdown("#### Fungal disease risk")
            st.html(f"<div class='risk {col}'><b>{level}</b><span>{hours} risky hours in the next 48</span></div>"
                    f"<p class='dek' style='margin-top:.8rem'>{why.capitalize()}.</p>"
                    + ("<p class='dek'>Plan a preventive spray (e.g. copper or mancozeb, label dose) in a dry window, and "
                       "improve airflow.</p>" if level != "Low" else "<p class='dek'>No preventive fungicide needed right now. Keep scouting weekly.</p>"))
    with c2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hh["time"], y=hh["rh"], name="Humidity %", line=dict(color=SKY, width=2, shape="spline"),
                                 fill="tozeroy", fillcolor="rgba(143,195,214,.07)"))
        fig.add_trace(go.Scatter(x=hh["time"], y=hh["temp"], name="Temp °C", yaxis="y2", line=dict(color=GOLD, width=2.5, shape="spline")))
        if hh["rain"].notna().any():
            fig.add_trace(go.Bar(x=hh["time"], y=hh["rain"], name="Rain chance %", marker_color="rgba(212,105,63,.35)"))
        fig.add_hrect(y0=85, y1=100, fillcolor="rgba(212,105,63,.08)", line_width=0)
        fig.update_layout(**PLOT_LAYOUT, height=300, title="Humidity, temperature & rain chance",
                          yaxis2=dict(overlaying="y", side="right", showgrid=False), barmode="overlay")
        fig.update_yaxes(range=[0, 100], selector=dict(anchor="x"))
        st.plotly_chart(fig, width="stretch", config=NOBAR)

    # ── Crop fit check (transparent rules) ──
    soil = soil_profile(prof["lat"], prof["lon"])
    props = soil.get("properties") or {}
    ph = _num((props.get("pH (water)") or {}).get("0-5cm"))
    clay = _num((props.get("Clay") or {}).get("0-5cm"))
    d = w["daily"]
    tmean = sum((a + b) / 2 for a, b in zip(d["temperature_2m_max"], d["temperature_2m_min"])) / len(d["time"])
    season_now = prompts.season_for().split(" ")[0]
    water_low = any(x in (prof.get("irrigation") or "").lower() for x in ("rain", "pond")) or "Low water" in (prof.get("prefs") or [])
    theme.section("D", "Crop fit check", "What suits <em>this</em> soil, now?",
                  f"Each crop is scored on four transparent factors: the current {season_now} season, your soil pH "
                  f"({ph if ph else 'unknown'}), the 10-day mean temperature ({tmean:.0f} °C) and water needs"
                  f"{' (rain-fed / low water)' if water_low else ''}. Ask AgroNova for varieties and a full plan.")
    rows = []
    def closeness(x, lo_, hi_, slack):
        """1.0 at the centre of the ideal range, ~0.6 at its edges, falling to 0 `slack` units outside it."""
        mid, half = (lo_ + hi_) / 2, max((hi_ - lo_) / 2, 0.01)
        if lo_ <= x <= hi_:
            return 1 - 0.4 * abs(x - mid) / half
        return max(0.0, 0.6 * (1 - (lo_ - x if x < lo_ else x - hi_) / slack))

    for name, lo, hi, seasons, tlo, thi, water, light in CROPS:
        in_season = season_now in seasons
        s_season = 40 if in_season else 30 if "perennial" in seasons else 6
        s_ph = round(25 * closeness(ph, lo, hi, 1.5)) if ph else 15
        s_t = round(20 * closeness(tmean, tlo, thi, 8))
        s_w = {"low": 15, "medium": 11, "high": 6}[water] if not water_low else {"low": 15, "medium": 8, "high": 2}[water]
        if light and clay and clay >= 40:
            s_w = max(0, s_w - 6)
        score = min(100, s_season + s_ph + s_t + s_w)
        notes = [("in season" if in_season else "year-round crop" if "perennial" in seasons else f"best in {'/'.join(seasons)}"),
                 (f"pH {lo}–{hi}" + (" ✓" if ph and lo <= ph <= hi else " ✗" if ph else " (soil pH unknown)")),
                 (f"{tlo}–{thi} °C" + (" ✓" if tlo <= tmean <= thi else " ✗")), f"{water} water"]
        if light and clay and clay >= 40:
            notes.append("prefers lighter soil")
        rows.append((score, name, notes))
    rows.sort(reverse=True)
    bars = "".join(
        f"""<div class="fit"><b>{html.escape(n)}</b><div class="fbar"><i style="width:{sc}%;background:{'#a9d46f' if sc >= 75 else '#e8b04a' if sc >= 50 else '#d4693f'}"></i></div>
        <span class="fs">{sc}</span><span class="fn">{html.escape(' · '.join(nt))}</span></div>""" for sc, n, nt in rows[:8])
    st.html(f"<div class='fits reveal'>{bars}</div>")

    st.html("<div class='kicker' style='margin:2.4rem 0 .8rem'><b>E</b><span>Ask AgroNova about this farm</span></div>")
    qs = [f"What should I sow next on my farm in {prof.get('district') or 'my district'}?",
          "Use my 7-day forecast to plan irrigation and spraying.",
          "Read my soil profile and give a fertilizer plan for 1 acre.",
          f"What are mandi prices for {prof.get('crop') or 'onion'} near me this week?"]
    cols = st.columns(4)
    for i, q in enumerate(qs):
        if cols[i].button(q, key=f"farmq{i}", width="stretch", icon=":material/arrow_outward:"):
            st.session_state.queued = {"text": q, "attachments": []}
            st.switch_page(PAGES["chat"])


def weather_dashboard(lat: float, lon: float):
    try:
        w = forecast(lat, lon, 10)
    except Exception as e:
        st.error(f"Weather service unavailable: {e}")
        return
    cur, d, h = w["current"], w["daily"], w["hourly"]
    label, _ = tools.describe_code(cur["weather_code"])
    with st.container(key="panel_wx"):
        st.markdown(f"#### Live at your farm — {label}")
        m = st.columns(4)
        m[0].metric("Temperature", f"{cur['temperature_2m']:.0f}°", f"feels {cur['apparent_temperature']:.0f}°", delta_color="off")
        m[1].metric("Humidity", f"{cur['relative_humidity_2m']}%")
        m[2].metric("Rain · 10 d", f"{sum(x or 0 for x in d['precipitation_sum']):.0f} mm")
        m[3].metric("Wind", f"{cur['wind_speed_10m']:.0f}", "km/h", delta_color="off")
        days = pd.to_datetime(d["time"])
        fig = go.Figure()
        fig.add_trace(go.Bar(x=days, y=d["precipitation_sum"], name="Rain mm", yaxis="y2",
                             marker=dict(color="rgba(143,195,214,.45)", line=dict(width=0)), hovertemplate="%{y:.1f} mm"))
        fig.add_trace(go.Scatter(x=days, y=d["temperature_2m_max"], name="High °C", mode="lines+markers",
                                 line=dict(color=GOLD, width=2.5, shape="spline"), marker=dict(size=6)))
        fig.add_trace(go.Scatter(x=days, y=d["temperature_2m_min"], name="Low °C", mode="lines", fill="tonexty",
                                 fillcolor="rgba(232,176,74,.08)", line=dict(color=LEAF, width=2, shape="spline")))
        fig.update_layout(**PLOT_LAYOUT, height=300, title="Ten days of sky",
                          yaxis2=dict(overlaying="y", side="right", showgrid=False, rangemode="tozero"))
        st.plotly_chart(fig, width="stretch", config=NOBAR)
        sm = pd.DataFrame({"time": pd.to_datetime(h["time"]), "Top 1 cm": h["soil_moisture_0_to_1cm"],
                           "3–9 cm": h["soil_moisture_3_to_9cm"]}).iloc[:24 * 7]
        fig2 = go.Figure()
        for col, c in [("Top 1 cm", LEAF), ("3–9 cm", SKY)]:
            fig2.add_trace(go.Scatter(x=sm["time"], y=sm[col], name=col, mode="lines", line=dict(color=c, width=2.2, shape="spline")))
        top = max([v for v in sm[["Top 1 cm", "3–9 cm"]].to_numpy().ravel() if v == v] or [0.4])
        fig2.update_layout(**PLOT_LAYOUT, height=230, title="Soil moisture, m³/m³")
        fig2.update_yaxes(range=[0, max(0.1, top * 1.4)])
        st.plotly_chart(fig2, width="stretch", config=NOBAR)
        st.caption("Open-Meteo live forecast · refreshed every 10 minutes")


# ═════════════════════════════ CHAT ═════════════════════════════
QUICK = ["What should I sow this month on my farm?", "Will it rain this week? Plan my irrigation.",
         "Today's onion price at Lasalgaon mandi?", "Check my soil and suggest fertilizer for 1 acre of maize.",
         "Organic fix for aphids on mustard?", "Which drip irrigation subsidies can I get?"]


def page_chat():
    track_page("chat")
    msgs = st.session_state.messages
    top = st.columns([3, 1, 1], vertical_alignment="center")
    with top[0]:
        location_chip()
    if top[1].button("Change farm", icon=":material/map:", width="stretch"):
        st.switch_page(PAGES["map"])
    if top[2].button("New chat", icon=":material/add:", width="stretch", disabled=not msgs):
        st.session_state.messages = []
        st.rerun()

    if not msgs:
        greeting = "Good morning" if dt.datetime.now().hour < 12 else "Good afternoon" if dt.datetime.now().hour < 17 else "Good evening"
        st.html(f"""<div class="reveal" style="margin:4rem 0 1rem"><div class="kicker"><b>03</b><span>AgroNova AI</span></div>
          <h1 class="display">{greeting}. <em>What's growing?</em></h1>
          <p class="dek">Ask about sowing, pests, rain, soil or market prices. AgroNova checks live weather and soil data,
          searches the web for prices and schemes, does exact calculations, looks at crop photos, listens to voice notes,
          and can read its answers aloud in your language.</p></div>""")
        cols = st.columns(3)
        for i, q in enumerate(QUICK):
            if cols[i % 3].button(q, key=f"q{i}", width="stretch"):
                st.session_state.queued = {"text": q, "attachments": []}
                st.rerun()

    for i, m in enumerate(msgs):
        with st.chat_message(m["role"], avatar=AV_USER if m["role"] == "user" else AV_AI):
            if m["role"] == "user":
                for a in m.get("attachments", []):
                    (st.image(a["data"], width=260) if a["mime"].startswith("image") else st.audio(a["data"]))
                st.markdown(m["content"])
            else:
                if m.get("tools"):
                    st.html(tool_chips(m["tools"]))
                if m.get("thoughts"):
                    with st.expander("Thinking"):
                        st.markdown(m["thoughts"])
                st.markdown(m["content"])
                if m.get("images"):
                    st.html(gallery_html(m["images"]))
                if m.get("sources"):
                    st.html(sources_html(m["sources"]))
                u = m.get("usage", {})
                meta = f"{llm.MODEL_LABELS.get(m.get('model', ''), m.get('model', '')).split(' (')[0]} · {u.get('seconds', '?')} s"
                if u.get("tool_calls"):
                    meta += f" · {u['tool_calls']} live lookups"
                c0, c1, c2, c3 = st.columns([1.3, 4, 1.1, 1.4], vertical_alignment="center")
                with c0:
                    auto = bool(m.get("autospeak")) and i == len(msgs) - 1 and not m.get("spoken")
                    speak_button(m["content"], key=m["id"], autoplay=auto, lang=m.get("voice_lang"))
                    if auto:
                        m["spoken"] = True
                c1.caption(meta)
                with c2:
                    fb = st.feedback("thumbs", key=f"fb_{m['id']}")
                    if fb is not None and m.get("rated") != fb:
                        m["rated"] = fb
                        state.log("feedback", rating="up" if fb == 1 else "down", feature="chat")
                is_last = i == len(msgs) - 1
                if is_last and c3.button("Retry", icon=":material/refresh:", key=f"re_{m['id']}"):
                    msgs.pop()
                    st.session_state.regen = True
                    st.rerun()
                if is_last and m.get("followups"):
                    st.html("<div class='kicker' style='margin:1.2rem 0 .5rem'><span>Ask next</span></div>")
                    fcols = st.columns(len(m["followups"]))
                    for j, q in enumerate(m["followups"]):
                        if fcols[j].button(q, key=f"fu_{m['id']}_{j}", width="stretch", icon=":material/subdirectory_arrow_right:"):
                            st.session_state.queued = {"text": q, "attachments": []}
                            st.rerun()

    value = st.chat_input("Ask about your crops, or attach a photo or voice note",
                          accept_file="multiple", file_type=["png", "jpg", "jpeg", "webp"], accept_audio=True)
    pending = None
    if value:
        atts = [{"data": f.getvalue(), "mime": f.type or "image/jpeg"} for f in (value.get("files") or [])]
        audio = value.get("audio")
        if audio:
            atts.append({"data": audio.getvalue(), "mime": audio.type or "audio/wav"})
        text = (value.get("text") or "").strip()
        if not text:
            text = "(Voice message: please transcribe it and answer.)" if audio else "Please look at this photo and diagnose any problem."
        pending = {"text": text, "attachments": atts}
    elif st.session_state.get("queued"):
        pending = st.session_state.pop("queued")

    if pending:
        msgs.append({"role": "user", "content": pending["text"], "attachments": pending["attachments"]})
        with st.chat_message("user", avatar=AV_USER):
            for a in pending["attachments"]:
                (st.image(a["data"], width=260) if a["mime"].startswith("image") else st.audio(a["data"]))
            st.markdown(pending["text"])
        generate_reply()
    elif st.session_state.pop("regen", False) and msgs and msgs[-1]["role"] == "user":
        generate_reply()


def generate_reply():
    client = client_or_warn()
    if not client:
        return
    with st.chat_message("assistant", avatar=AV_AI):
        msg = render_stream(llm.stream_agent(client, system_prompt(), st.session_state.messages, state.settings()), st.container())
        if msg["content"] and msg["content"] != llm.REFUSAL:
            last_user = st.session_state.messages[-1]
            voice = next((a for a in last_user.get("attachments", []) or [] if a["mime"].startswith("audio")), None)
            if voice is not None:                       # asked by voice → answer is spoken back automatically
                msg["autospeak"] = True
                heard = (voice.get("lang") or "").title()
                msg["voice_lang"] = next((v for k, v in LANG_CODES.items() if heard and k in heard), None)
            msg["followups"] = llm.suggest_followups(client, st.session_state.messages[-1]["content"], msg["content"],
                                                     "the same language as the farmer's question" if st.session_state.get("language", "").startswith("Auto")
                                                     else st.session_state.get("language", "English"))
    st.session_state.messages.append(msg)
    u = msg["usage"]
    state.log("chat", feature="chat", latency_s=u.get("seconds", ""), tokens_in=u.get("input", ""),
              tokens_out=u.get("output", ""), tool_calls=u.get("tool_calls", 0),
              detail=st.session_state.messages[-2]["content"][:120])
    st.rerun()


# ═════════════════════════════ FEATURE STUDIO ═════════════════════════════
def page_studio():
    track_page("studio")
    theme.page_header("04", "Feature Studio", "Six modules, <em>one</em> careful prompt each.",
                      "Fill in a few details. AgroNova builds a structured prompt for your region, fetches live data and "
                      "returns a formatted plan with the reason for each step.", theme.IMG_SEEDLING, "Seedlings · Unsplash")
    keys = list(prompts.FEATURES)
    choice = st.pills("Module", keys, format_func=lambda k: prompts.FEATURES[k]["title"],
                      default=st.session_state.get("studio_feat", "crop"), key="studio_feat", label_visibility="collapsed") or "crop"
    f = prompts.FEATURES[choice]
    st.html(f"""<div class="mod reveal"><img src="{f['img']}" alt=""/><div><div class="kicker"><b>0{keys.index(choice) + 1}</b>
      <span>Module</span></div><div class="ti">{f['title']}</div><div class="de">{f['tagline']}</div></div></div>""")

    prof = st.session_state.profile
    left, right = st.columns([1, 1.55], gap="large")
    with left:
        with st.container(key="panel_studio_form"):
            st.markdown("#### Your situation")
            location_chip()
            place = st.text_input("Location", state.place_label() or "", placeholder="District, state or country",
                                  help="Defaults to your pinned farm. Type another place to override it.")
            crop = st.text_input("Crop", prof.get("crop", ""), placeholder="Wheat")
            stage = st.text_input("Crop stage or situation", prof.get("stage", ""), placeholder="Flowering")
            c1, c2 = st.columns(2)
            size = c1.text_input("Farm size", prof.get("farm_size", "") or "1 acre")
            water = c2.text_input("Water", prof.get("irrigation", "") or "Rain-fed")
            prefs = st.multiselect("Preferences", ["Organic only", "Low cost", "Low water", "High market value", "Quick harvest"],
                                   default=prof.get("prefs", []))
            extra = st.text_area("What you see" if choice == "pest" else "Anything else (optional)", height=90, key=f"extra_{choice}")
            photo = st.file_uploader("Crop photo (optional)", type=["png", "jpg", "jpeg", "webp"]) if choice == "pest" else None
            go_btn = st.button(f"Generate {f['title'].lower()} plan", type="primary", width="stretch", icon=":material/auto_awesome:")
        st.markdown("#### Or try a storyboard prompt")
        sample = None
        for i, q in enumerate(f["samples"]):
            if st.button(q, key=f"s_{choice}_{i}", width="stretch"):
                sample = q
    with right:
        out = st.container(key="panel_studio_out")
        ran = bool(sample or go_btn)
        with out:
            st.markdown("#### The plan")
            if choice == "weather" and prof["lat"] is not None and not ran:
                weather_dashboard(prof["lat"], prof["lon"])
            elif not ran and st.session_state.get("last_studio_feat") != choice:
                ex = (baseline().get("modules") or {}).get(choice)
                if ex:
                    st.html(f"<span class='badge'>Example answer · saved live run · {baseline_label()}</span>"
                            f"<p class='dek' style='margin:0 0 .8rem'>Farmer asked: <b>“{html.escape(ex['prompt'])}”</b></p>")
                    if ex.get("tools"):
                        st.html(tool_chips([{"label": TOOL_LABELS.get(t, t), "args": {}, "ms": 0} for t in dict.fromkeys(ex["tools"])]))
                    st.markdown(ex["answer"])
                    st.caption("Fill in your situation, or tap a storyboard prompt, to get a live plan for your own farm.")
                else:
                    st.html("<p class='h2' style='font-size:2rem'>Your plan will <em>appear here.</em></p>"
                            "<p class='dek'>It streams in live, with tables, steps and a short reason for each recommendation.</p>")
        if ran:
            client = client_or_warn()
            if client:
                if sample:
                    prompt = sample + (f"\n(Context: my farm is in {state.place_label()}.)" if state.place_label() and not any(
                        w in sample for w in ["India", "Kenya", "Ghana", "Italy", "Canada"]) else "")
                else:
                    prompt = f["template"].format(place=place or "not specified — ask or assume and state it",
                                                  month=dt.date.today().strftime("%B"), stage=stage or "not specified",
                                                  crop=crop or "not specified", prefs=", ".join(prefs) or "none",
                                                  size=size, water=water, extra=extra or "")
                atts = [{"data": photo.getvalue(), "mime": photo.type}] if photo else []
                with out:
                    with st.expander("Engineered prompt sent to the model"):
                        st.code(prompt, language="markdown")
                    msg = render_stream(llm.stream_agent(client, system_prompt(), [{"role": "user", "content": prompt, "attachments": atts}],
                                                         state.settings()), st.container())
                u = msg["usage"]
                state.log("feature", feature=choice, latency_s=u.get("seconds", ""), tokens_in=u.get("input", ""),
                          tokens_out=u.get("output", ""), tool_calls=u.get("tool_calls", 0), detail=(sample or crop)[:120])
                st.session_state.last_studio = (prompt, msg)
                st.session_state.last_studio_feat = choice
        elif st.session_state.get("last_studio") and st.session_state.get("last_studio_feat") == choice:
            _, m = st.session_state.last_studio
            with out:
                if m.get("tools"):
                    st.html(tool_chips(m["tools"]))
                st.markdown(m["content"])
                if m.get("images"):
                    st.html(gallery_html(m["images"]))
                if m.get("sources"):
                    st.html(sources_html(m["sources"]))
                speak_button(m["content"], key=f"studio_{m['id']}")
        if st.session_state.get("last_studio"):
            if st.button("Continue in chat", icon=":material/forum:", width="stretch"):
                p, m = st.session_state.last_studio
                st.session_state.messages += [{"role": "user", "content": p, "attachments": []}, m]
                st.switch_page(PAGES["chat"])


# ═════════════════════════════ VALIDATION LAB ═════════════════════════════
def _readability(text: str) -> float:
    words = re.findall(r"\w+", text)
    return round(len(words) / max(1, len(re.findall(r"[.!?\n]+", text))), 1)


def page_validation():
    track_page("validation")
    theme.page_header("05", "Validation Lab", "Test it, score it, <em>improve it.</em>",
                      "Runs prompts from India, Ghana, Canada and Kenya and checks each answer for the expected agronomy. "
                      "A second model pass grades it on the feedback checklist, and an A/B test compares prompt versions.",
                      theme.IMG_FARMERS, "Field trial · Unsplash")
    tab1, tab2, tab3 = st.tabs(["Regional suite", "Prompt A/B", "Reviewer checklist"])
    with tab1:
        st.dataframe(pd.DataFrame(prompts.VALIDATION_SUITE)[["region", "prompt"]], width="stretch", hide_index=True)
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        n = c1.slider("Prompts to run", 1, len(prompts.VALIDATION_SUITE), 3)
        if c2.button("Run the suite", type="primary", icon=":material/play_arrow:", width="stretch"):
            client = client_or_warn()
            if client:
                s, rows = state.settings(), []
                with st.status("Running validation…", expanded=True) as stat:
                    for case in prompts.VALIDATION_SUITE[:n]:
                        st.write(f"{case['region']} — generating")
                        sysp = prompts.SYSTEM_PROMPT + "\n\n" + prompts.farm_context({}, "English")
                        ans, u = llm.run_to_text(client, sysp, case["prompt"], s)
                        st.write(f"{case['region']} — grading")
                        judge = llm.parse_json(llm.complete(client, prompts.JUDGE_PROMPT.format(q=case["prompt"], a=ans[:6000]),
                                                            llm.Settings(model=llm.FAST_MODEL, temperature=0.0, max_tokens=800)))
                        hits = [k for k in case["expect"] if k.lower() in ans.lower()]
                        rows.append({"region": case["region"], "prompt": case["prompt"], "answer": ans,
                                     "keyword_match_%": round(100 * len(hits) / len(case["expect"])), "matched": ", ".join(hits),
                                     "words/sentence": _readability(ans), "tools": ", ".join(u.get("tools", [])),
                                     "latency_s": u.get("seconds"), "region_score": judge.get("region"),
                                     "reasoning": judge.get("reasoning"), "simple": judge.get("simple"),
                                     "balanced": judge.get("balanced"), "safe": judge.get("safe"),
                                     "hallucination_risk": judge.get("hallucination_risk"), "fix": judge.get("fix")})
                        state.log("validation", feature="validation", latency_s=u.get("seconds"), detail=case["region"])
                    stat.update(label="Validation complete", state="complete", expanded=False)
                st.session_state.validation = rows
        rows_v = st.session_state.validation or baseline().get("validation") or []
        if rows_v and not st.session_state.validation:
            st.html(f"<span class='badge'>Showing the saved baseline run · {baseline_label()} · judged by gpt-oss-20b</span>")
        if rows_v:
            df = pd.DataFrame(rows_v)
            crit = ["region_score", "reasoning", "simple", "balanced", "safe"]
            m = st.columns(4)
            m[0].metric("Prompts tested", len(df))
            m[1].metric("Keyword match", f"{df['keyword_match_%'].mean():.0f}%")
            m[2].metric("Judge score", f"{pd.to_numeric(df[crit].stack(), errors='coerce').mean():.2f}")
            m[3].metric("Latency", f"{pd.to_numeric(df['latency_s'], errors='coerce').mean():.1f}s")
            fig = go.Figure()
            for k, (_, r) in enumerate(df.iterrows()):
                vals = [pd.to_numeric(r[c], errors="coerce") or 0 for c in crit]
                fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=["Region", "Reasoning", "Simple", "Balanced", "Safe", "Region"],
                                              fill="toself", name=r["region"], opacity=.6, line=dict(color=SERIES[k % 6])))
            fig.update_layout(**{k: v for k, v in PLOT_LAYOUT.items() if k not in ("xaxis", "yaxis")}, height=440,
                              polar=dict(bgcolor="rgba(0,0,0,0)", radialaxis=dict(range=[0, 5], gridcolor=RULE, linecolor=RULE),
                                         angularaxis=dict(gridcolor=RULE, linecolor=RULE)), title="Checklist scores by region")
            st.plotly_chart(fig, width="stretch", config=NOBAR)
            st.dataframe(df.drop(columns=["answer"]), width="stretch", hide_index=True)
            for r in rows_v:
                with st.expander(f"{r['region']} — {r['prompt']}"):
                    st.markdown(r["answer"])
                    st.caption(f"Judge suggestion: {r.get('fix') or '—'}")
            st.download_button("Download results (CSV)", df.to_csv(index=False), "agronova_validation.csv", "text/csv",
                               icon=":material/download:")

    with tab2:
        st.markdown("This runs the same question two ways. **A** is a naive prompt: no system prompt, high temperature, "
                    "no tools. **B** is the optimised AgroNova prompt: system prompt, live tools and structured output.")
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        q = c1.text_input("Question", "What to grow in Rajasthan in August?")
        if c2.button("Run A/B", type="primary", icon=":material/compare_arrows:", width="stretch"):
            client = client_or_warn()
            if client:
                s = state.settings()
                a_cfg = llm.Settings(model=s.model, temperature=1.2, max_tokens=s.max_tokens, thinking=False, tools=False)
                with st.spinner("Running both variants…"):
                    a_txt, a_u = llm.run_to_text(client, "", q, a_cfg)
                    b_txt, b_u = llm.run_to_text(client, prompts.SYSTEM_PROMPT + "\n\n" + prompts.farm_context({}, "English"), q, s)
                    js = [llm.parse_json(llm.complete(client, prompts.JUDGE_PROMPT.format(q=q, a=t[:6000]),
                                                      llm.Settings(model=llm.FAST_MODEL, temperature=0, max_tokens=800))) for t in (a_txt, b_txt)]
                st.session_state.ab = {"q": q, "a": (a_txt, a_u, js[0]), "b": (b_txt, b_u, js[1])}
                state.log("ab_test", feature="validation", detail=q[:100])
        ab = st.session_state.get("ab") or baseline().get("ab")
        if ab:
            if not st.session_state.get("ab"):
                st.html(f"<span class='badge'>Showing the saved baseline A/B run · {baseline_label()}</span>")
            crit = ["region", "reasoning", "simple", "balanced", "safe"]
            fig = go.Figure()
            for lab, key, col in [("A · naive", "a", CLAY), ("B · optimised", "b", GOLD)]:
                fig.add_trace(go.Bar(x=crit, y=[ab[key][2].get(c, 0) for c in crit], name=lab, marker_color=col))
            fig.update_layout(**PLOT_LAYOUT, barmode="group", height=320, title="Judge scores, 1–5", yaxis_range=[0, 5])
            st.plotly_chart(fig, width="stretch", config=NOBAR)
            ca, cb = st.columns(2, gap="large")
            for col, lab, key in [(ca, "A — naive prompt", "a"), (cb, "B — optimised prompt", "b")]:
                with col:
                    with st.container(key=f"panel_ab_{key}"):
                        st.markdown(f"#### {lab}")
                        st.caption(f"{ab[key][1].get('seconds', '?')} s · tools: {', '.join(ab[key][1].get('tools', [])) or 'none'} · "
                                   f"hallucination risk: {ab[key][2].get('hallucination_risk', '?')}")
                        st.markdown(ab[key][0])

    with tab3:
        last = next((m for m in reversed(st.session_state.messages) if m["role"] == "assistant"), None)
        if not last:
            st.info("Ask something in AgroNova AI first, then review the answer here.")
        else:
            with st.expander("Latest answer"):
                st.markdown(last["content"])
            res = {k: st.checkbox(lbl, key=f"chk_{k}_{last['id']}") for k, lbl in prompts.CHECKLIST}
            score = sum(res.values())
            st.progress(score / len(res), text=f"Checklist score {score} / {len(res)}")
            if st.button("Save review", icon=":material/save:"):
                state.log("checklist", feature="validation", rating=str(score), detail=";".join(k for k, v in res.items() if v))
                st.toast("Review saved to the usage log", icon=":material/check:")


# ═════════════════════════════ USAGE MONITOR ═════════════════════════════
def page_monitor():
    track_page("monitor")
    theme.page_header("06", "Usage", "Who asks what, <em>and how well</em> it answers.",
                      "Every chat, module run, location lock, rating and validation is logged, so the team can follow the "
                      "pilot across devices.", theme.IMG_GRAIN, "Grain · Unsplash")
    st.markdown("#### System status — checked live")
    checks = system_status()
    st.html("<div class='health'>" + "".join(
        f"<div class='hc{'' if ok else ' bad'}'><b>{html.escape(name)}</b><span>{html.escape(info)}</span></div>"
        for name, ok, info in checks) + "</div>")
    if st.button("Re-check now", icon=":material/refresh:"):
        system_status.clear()
        st.rerun()
    try:
        df = pd.read_csv(state.LOG_PATH)
    except Exception:
        df = pd.DataFrame(st.session_state.get("session_log", []))
    if df.empty:
        st.html("<p class='h2' style='font-size:2rem'>Nothing logged <em>yet.</em></p><p class='dek'>Try the chat or a Feature Studio module, then come back.</p>")
        return
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    st.markdown("#### Pilot activity")
    pv = df[df["event"] == "page_view"]["feature"].value_counts()
    scope = st.segmented_control("Scope", ["All sessions", "This session"], default="All sessions", label_visibility="collapsed")
    if scope == "This session":
        df = df[df["session"] == st.session_state.sid]
    q = df[df["event"].isin(["chat", "feature"])]
    fb = df[df["event"] == "feedback"]
    m = st.columns(5)
    m[0].metric("AI queries", len(q))
    m[1].metric("Sessions", df["session"].nunique())
    m[2].metric("Latency", f"{pd.to_numeric(q['latency_s'], errors='coerce').mean():.1f}s" if len(q) else "—")
    m[3].metric("Live lookups", int(pd.to_numeric(q["tool_calls"], errors="coerce").fillna(0).sum()))
    m[4].metric("Thumbs up", f"{(fb['rating'] == 'up').mean() * 100:.0f}%" if len(fb) else "—")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        by = df.groupby([pd.Grouper(key="ts", freq="h"), "event"]).size().reset_index(name="n")
        fig = go.Figure()
        for ev, g in by.groupby("event"):
            fig.add_trace(go.Scatter(x=g["ts"], y=g["n"], name=ev, mode="lines+markers", line=dict(shape="spline", width=2)))
        fig.update_layout(**PLOT_LAYOUT, height=320, title="Activity over time")
        st.plotly_chart(fig, width="stretch", config=NOBAR)
    with c2:
        if len(q):
            feat = q["feature"].fillna("chat").value_counts()
            fig = go.Figure(go.Pie(labels=feat.index, values=feat.values, hole=.72, marker=dict(colors=SERIES, line=dict(color="#0d0b08", width=3))))
            fig.update_layout(**{k: v for k, v in PLOT_LAYOUT.items() if k not in ("xaxis", "yaxis")}, height=320, title="Module usage")
        else:
            fig = go.Figure(go.Bar(x=pv.index, y=pv.values, marker=dict(color=SERIES[: len(pv)] or GOLD)))
            fig.update_layout(**PLOT_LAYOUT, height=320, title="Page views")
        st.plotly_chart(fig, width="stretch", config=NOBAR)
    reg = df["region"].replace("", pd.NA).dropna().value_counts().head(10)
    if len(reg):
        fig = go.Figure(go.Bar(x=reg.values, y=reg.index, orientation="h", marker=dict(color=GOLD)))
        fig.update_layout(**PLOT_LAYOUT, height=300, title="Top farm locations")
        st.plotly_chart(fig, width="stretch", config=NOBAR)
    st.dataframe(df.sort_values("ts", ascending=False), width="stretch", hide_index=True)
    st.download_button("Export usage log", df.to_csv(index=False), "agronova_usage.csv", "text/csv", icon=":material/download:")


@st.cache_data(ttl=120, show_spinner=False)
def system_status() -> list[tuple[str, bool, str]]:
    """Live health checks of every service the app depends on (cached 2 min)."""
    import requests
    out = []

    def timed(name, fn):
        t = time.time()
        try:
            info = fn()
            out.append((name, True, f"{info} · {int((time.time() - t) * 1000)} ms"))
        except Exception as e:
            out.append((name, False, f"{type(e).__name__}"))

    key = state.api_key()
    if key:
        timed("AI models (Groq)", lambda: f"{len(llm.list_models(llm.make_client(key)))} models online")
    else:
        out.append(("AI models (Groq)", False, "no key set on the server"))
    timed("Weather · Open-Meteo", lambda: requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": 20, "longitude": 73.8, "current": "temperature_2m"}, timeout=8).raise_for_status() or "forecast OK")
    timed("Place search", lambda: f"{len(tools.geocode('Nashik', 'IN', 1))} match")
    timed("Soil · ISRIC SoilGrids", lambda: requests.get("https://rest.isric.org/soilgrids/v2.0/properties/query", params={
        "lon": 85.1, "lat": 20.9, "property": "phh2o", "depth": "0-5cm", "value": "mean"}, timeout=10).raise_for_status() or "soil OK")
    b = baseline()
    out.append(("Saved baseline run", bool(b), f"{len(b.get('validation', []))} tests · {b.get('generated', '—')}" if b else "missing"))
    return out


# ═════════════════════════════ STORYBOARD (FA-1) ═════════════════════════════
def page_storyboard():
    track_page("storyboard")
    theme.page_header("07", "FA-1 Storyboard", "From problem <em>to product.</em>",
                      "The problem research, personas, the five core features with their prompts, the LLM API settings and "
                      "the UI flow this app implements.", theme.HERO_POSTER, "Wheat at sunrise · Unsplash")
    t1, t2, t5, t3, t6, t4 = st.tabs(["Problem & research", "Personas", "User journey", "Features & prompts",
                                      "Sample outputs", "LLM API"])
    with t5:
        st.html("""<div class="journey">
          <div><i>STEP 1</i><b>Pin the farm</b><span>Tap the India map, search a village or use GPS. Lock it.</span></div>
          <div><i>STEP 2</i><b>Describe the farm</b><span>Crop, stage, size, water source, preferences such as organic or low-cost.</span></div>
          <div><i>STEP 3</i><b>Ask, any way</b><span>Type, send a leaf photo or record a voice note, in any of 16 languages.</span></div>
          <div><i>STEP 4</i><b>AI fetches facts</b><span>Live weather, soil grids, crop calendar, web prices, exact calculations.</span></div>
          <div><i>STEP 5</i><b>Act with reasons</b><span>A one-line answer, steps with a <i>why</i>, safety notes, Listen and follow-ups.</span></div>
        </div>""")
        st.markdown("#### Prompt anatomy — what makes a good farming prompt")
        st.html("""<div class="anat">Recommend the 3–5 best crops to sow
          <mark class="k1">in Jodhpur, Rajasthan in August</mark> for
          <mark class="k2">a 2-acre rain-fed farm after a bajra crop</mark>,
          <mark class="k3">with only two irrigations available and low cost preferred</mark>.
          <mark class="k4">Answer as a table | Crop | Sow by | Water need | Why |, then 5 numbered field steps.</mark></div>
          <div class="legend"><span style="--c:#e8b04a">Location + time</span><span style="--c:#a9d46f">Crop / farm context</span>
          <span style="--c:#8fc3d6">Constraints</span><span style="--c:#f0a07c">Output format</span></div>""")
        st.markdown("Each Feature Studio template fills these four slots automatically from the farm profile. The system "
                    "prompt then adds the persona, honesty rules, tool use and safety. This structure is what reduces vague "
                    "or made-up answers (FA-1 Step 3).")
    with t6:
        mods = baseline().get("modules") or {}
        if not mods:
            st.info("Run `python tools_build_baseline.py` to save sample outputs.")
        else:
            st.html(f"<span class='badge'>Real outputs · saved live run · {baseline_label()}</span>")
            st.markdown("Formatted, reasoned answers for one storyboard prompt per feature (FA-2 Step 4).")
            for k, ex in mods.items():
                f = prompts.FEATURES.get(k, {})
                with st.expander(f"{f.get('title', k)} — “{ex['prompt']}”", expanded=(k == "crop")):
                    if ex.get("tools"):
                        st.html(tool_chips([{"label": TOOL_LABELS.get(t, t), "args": {}, "ms": 0} for t in dict.fromkeys(ex["tools"])]))
                    st.markdown(ex["answer"])
                    st.caption(f"{ex.get('seconds', '?')} s end-to-end")
    with t1:
        st.markdown("""
### Problem statement
Small and medium farmers in **semi-arid Maharashtra and Rajasthan**, and in pilot regions in **Ghana** and **Canada**, make
sowing, spraying and irrigation decisions with little timely, local advice in their own language. Erratic monsoons,
pest outbreaks and worn-out soils turn those decisions into costly guesses.

### Five regional challenges
| # | Challenge | Region | How generative AI helps |
|---|---|---|---|
| 1 | Erratic monsoon onset & dry spells | Marathwada, Rajasthan | Live-forecast-driven sowing & irrigation plans |
| 2 | Pink bollworm & sucking pests in cotton | Maharashtra, Telangana | Symptom/photo diagnosis + IPM-first treatment |
| 3 | Acidic, low-organic-carbon soils | Odisha, Jharkhand, Kenya | Soil-grid lookup → liming & fertilizer schedule |
| 4 | Groundwater depletion in rice–wheat | Punjab, Haryana | Crop diversification & water-saving practices |
| 5 | Frost / short seasons; bimodal rains | Canada, Ghana, Kenya | Region-aware crop calendars and harvest windows |

### Research summary
- **FAO**: climate-smart agriculture and integrated pest management cut input costs while protecting yields. Gaps in extension services are a key barrier.
- **World Bank**: agriculture employs about 45% of India's workforce, and climate variability is one of the biggest risks to productivity.
- **NABARD / NMSA (SDG vision)**: rain-fed farming covers about 51% of net sown area. Soil health and water-use efficiency are priorities.
- **Krishi Vigyan Kendras (KVKs)**: farmers trust district-level advice in their own language most. The assistant copies that
  style and always points farmers back to their KVK for serious cases.
- Supports **UN SDG 2 (Zero Hunger)** and **SDG 13 (Climate Action)**.
""")
    with t2:
        p1, p2 = st.columns(2, gap="large")
        for col, img, name, body in [
            (p1, theme.IMG_FARMERS, "Sunita Patil, 38 — Nashik, Maharashtra",
             "Farms 2.5 acres of onion and soybean, with a borewell that runs dry in April. Uses WhatsApp on her smartphone and prefers **Marathi**. "
             "She needs to know when to sow after the monsoon arrives, how to control thrips on onion without overspending, and when to irrigate."),
            (p2, theme.IMG_GREEN, "Kwame Mensah, 45 — Kumasi, Ghana",
             "Farms 4 acres of maize and cassava, rain-fed, with two seasons a year. Speaks **Twi and English**. He needs the planting date for the major season, "
             "fall armyworm control he can afford, and advice on soil fertility.")]:
            with col:
                st.html(f"<figure class='tilt' style='margin:0;border-radius:18px;overflow:hidden;aspect-ratio:4/3'>"
                        f"<img src='{img}' style='width:100%;height:100%;object-fit:cover;filter:sepia(.15)' alt=''/></figure>"
                        f"<h3 style='font-size:1.8rem;margin:1rem 0 .4rem'>{name}</h3>")
                st.markdown(body)
    with t3:
        for k, f in prompts.FEATURES.items():
            with st.expander(f"{f['title']} — {f['tagline']}", expanded=(k == "crop")):
                st.markdown("**How a farmer might ask**\n" + "\n".join(f"- “{s}”" for s in f["samples"]))
                st.markdown("**Engineered prompt template** (location, crop or stage, constraints, output format)")
                st.code(f["template"].strip(), language="markdown")
    with t4:
        st.markdown("""
**Integration:** the OpenAI-compatible chat API, through the `openai` Python SDK. The provider is picked from the key:
**Groq** (`gsk_…`, `base_url="https://api.groq.com/openai/v1"`, default model *openai/gpt-oss-120b*, plus Whisper for voice
notes) or **xAI Grok** (`xai-…`, `base_url="https://api.x.ai/v1"`). Every chat model your key can use appears in the sidebar,
best first. (The FA briefs name Gemini 1.5; the prompt engineering, parameters and tool use carry over unchanged, and only
the client library differs.)

| Parameter | What it does | AgroNova default | Why |
|---|---|---|---|
| `temperature` | Randomness / creativity | **0.6** | Practical, consistent advice; raise for brainstorming |
| `max_tokens` | Maximum answer length | **2048** | Room for tables + steps; lower = shorter answers |
| reasoning model | Model reasons before answering | **gpt-oss-120b** | Fewer mistakes on multi-factor questions |
| `tools` | Function calling | **weather, soil, crop calendar, geocode** | Grounds answers in live data, cuts hallucinations |
| `system` message | Persona + rules | AgroNova constitution | Format, safety, language, honesty |
""")
        st.code('''from openai import OpenAI

client = OpenAI(api_key="YOUR_GROQ_API_KEY", base_url="https://api.groq.com/openai/v1")
resp = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {"role": "system", "content": "You are an expert agronomist. Answer in bullets with a short 'why' for each."},
        {"role": "user", "content": "Suggest crops to plant in July in Tamil Nadu."},
    ],
    temperature=0.6,   # lower = more focused, higher = more creative
    max_tokens=1024,   # caps the length of the answer
)
print(resp.choices[0].message.content)''', language="python")


PAGES: dict = {}
