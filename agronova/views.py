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


LANG_CODES = {"English": "en-IN", "Hindi": "hi-IN", "Marathi": "mr-IN", "Tamil": "ta-IN", "Telugu": "te-IN",
              "Kannada": "kn-IN", "Bengali": "bn-IN", "Punjabi": "pa-IN", "Gujarati": "gu-IN", "Malayalam": "ml-IN",
              "Odia": "or-IN", "Kiswahili": "sw-KE", "Français": "fr-FR", "Português": "pt-BR", "Español": "es-ES",
              "Twi": "en-GH"}
CITE = re.compile(r"【[^】]*】")


def clean_answer(text: str) -> str:
    """Remove the model's raw browsing citation markers (sources are listed separately)."""
    return CITE.sub("", text)


def lang_code() -> str:
    lang = st.session_state.get("language", "English")
    return next((v for k, v in LANG_CODES.items() if k in lang), "en-IN")


def speak_button(text: str, key: str) -> None:
    """Read-aloud using the device's own voices (works offline, covers Indian languages)."""
    plain = re.sub(r"\|[-: |]+\|", " ", text)
    plain = re.sub(r"[#*_`>|]+", " ", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"\s+", " ", plain).strip()[:4000]
    payload = json.dumps(plain)
    st.iframe(f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500&display=swap" rel="stylesheet">
<style>html,body{{margin:0;background:transparent;overflow:hidden}}
button{{font:500 13px 'Inter Tight',sans-serif;color:#f2ead9;background:#211b14;border:0;border-radius:999px;height:34px;padding:0 14px;
cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:background .3s}}button:hover{{background:#2b231a}}
i{{width:7px;height:7px;border-radius:50%;background:#a59c8a}}button.on i{{background:#e8b04a;animation:p 1s infinite}}
@keyframes p{{50%{{opacity:.3}}}}</style></head><body>
<button id="b"><i></i><span>Listen</span></button>
<script>
const S=(window.parent&&window.parent.speechSynthesis)||window.speechSynthesis, U=(window.parent&&window.parent.SpeechSynthesisUtterance)||SpeechSynthesisUtterance;
const b=document.getElementById('b'), t=b.querySelector('span'), text={payload}, lang="{lang_code()}";
function reset(){{b.classList.remove('on');t.textContent='Listen';}}
b.onclick=()=>{{ if(S.speaking){{S.cancel();reset();return;}}
  const u=new U(text); u.lang=lang; u.rate=.97;
  const v=S.getVoices().find(v=>v.lang===lang)||S.getVoices().find(v=>v.lang.startsWith(lang.slice(0,2))); if(v) u.voice=v;
  u.onend=reset; u.onerror=reset; S.speak(u); b.classList.add('on'); t.textContent='Stop'; }};
</script></body></html>""", height=38)


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
        trace_ph, think_slot, answer_ph, src_ph = st.empty(), st.empty(), st.empty(), st.empty()
        answer_ph.html("<div class='typing'><i></i><i></i><i></i></div>")
    text, thoughts, trace, usage, status, think_ph, sources = "", "", [], {}, None, None, []
    t0, last = time.time(), 0.0
    for ev in events:
        if ev.kind == "sources":
            sources += ev.data
            src_ph.html(sources_html(sources))
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
            "sources": sources, "model": state.settings().model, "id": uuid.uuid4().hex[:10]}


def system_prompt(extra: str = "") -> str:
    return prompts.SYSTEM_PROMPT + "\n\n" + prompts.farm_context(st.session_state.profile, st.session_state.language) + extra


def location_chip() -> None:
    lab = state.place_label()
    if lab:
        p = st.session_state.profile
        st.html(f"<span class='loc on'>{html.escape(lab)} &nbsp;·&nbsp; {p['lat']:.3f}, {p['lon']:.3f}</span>")
    else:
        st.html("<span class='loc'>No farm pinned — set one in Farm Locator</span>")


def footer():
    st.html("""<footer class="foot2">
      <div class="mark">Agro<em>Nova</em></div>
      <div><h6>Data</h6><p>Groq API · gpt-oss</p><p>Open-Meteo forecast</p><p>ISRIC SoilGrids</p><p>2011 census districts</p></div>
      <div><h6>Imagery & note</h6><p>Footage: Mixkit · Photos: Unsplash · Maps: Esri, OSM</p>
        <p style="margin-top:.8rem">Guidance, not a guarantee. Confirm big decisions with your local KVK — Kisan Call Centre 1800-180-1551.</p></div>
    </footer>""")


# ═════════════════════════════ HOME ═════════════════════════════
def page_home():
    theme.hero()
    theme.ticker(["Crop recommendation", "Pest & disease doctor", "Weather-smart alerts", "Soil & fertilizer",
                  "Sustainable farming", "Sixteen languages", "Photo diagnosis", "Voice questions"])

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
      <div><b data-count="758">0</b><span>Districts on the map</span></div><div><b data-count="16">0</b><span>Answer languages</span></div>
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
                        "<p class='dek'>You'll get a 10-day forecast, a rain outlook and topsoil moisture for that exact point.</p>")
        else:
            weather_dashboard(prof["lat"], prof["lon"])


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
                if m.get("sources"):
                    st.html(sources_html(m["sources"]))
                u = m.get("usage", {})
                meta = f"{llm.MODEL_LABELS.get(m.get('model', ''), m.get('model', '')).split(' (')[0]} · {u.get('seconds', '?')} s"
                if u.get("tool_calls"):
                    meta += f" · {u['tool_calls']} live lookups"
                c0, c1, c2, c3 = st.columns([1.3, 4, 1.1, 1.4], vertical_alignment="center")
                with c0:
                    speak_button(m["content"], key=m["id"])
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
            msg["followups"] = llm.suggest_followups(client, st.session_state.messages[-1]["content"], msg["content"],
                                                     st.session_state.get("language", "English"))
    st.session_state.messages.append(msg)
    u = msg["usage"]
    state.log("chat", feature="chat", latency_s=u.get("seconds", ""), tokens_in=u.get("input", ""),
              tokens_out=u.get("output", ""), tool_calls=u.get("tool_calls", 0),
              detail=st.session_state.messages[-2]["content"][:120])
    st.rerun()


# ═════════════════════════════ FEATURE STUDIO ═════════════════════════════
def page_studio():
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
            elif not ran and not st.session_state.get("last_studio"):
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
        elif st.session_state.get("last_studio"):
            _, m = st.session_state.last_studio
            with out:
                if m.get("tools"):
                    st.html(tool_chips(m["tools"]))
                st.markdown(m["content"])
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
                                                            llm.Settings(model=s.model, temperature=0.0, max_tokens=600)))
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
        if st.session_state.validation:
            df = pd.DataFrame(st.session_state.validation)
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
            for r in st.session_state.validation:
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
                                                      llm.Settings(model=s.model, temperature=0, max_tokens=600))) for t in (a_txt, b_txt)]
                st.session_state.ab = {"q": q, "a": (a_txt, a_u, js[0]), "b": (b_txt, b_u, js[1])}
                state.log("ab_test", feature="validation", detail=q[:100])
        if st.session_state.get("ab"):
            ab = st.session_state.ab
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
    theme.page_header("06", "Usage", "Who asks what, <em>and how well</em> it answers.",
                      "Every chat, module run, location lock, rating and validation is logged, so the team can follow the "
                      "pilot across devices.", theme.IMG_GRAIN, "Grain · Unsplash")
    try:
        df = pd.read_csv(state.LOG_PATH)
    except Exception:
        df = pd.DataFrame(st.session_state.get("session_log", []))
    if df.empty:
        st.html("<p class='h2' style='font-size:2rem'>Nothing logged <em>yet.</em></p><p class='dek'>Try the chat or a Feature Studio module, then come back.</p>")
        return
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
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
        feat = q["feature"].fillna("chat").value_counts()
        fig = go.Figure(go.Pie(labels=feat.index, values=feat.values, hole=.72, marker=dict(colors=SERIES, line=dict(color="#0d0b08", width=3))))
        fig.update_layout(**{k: v for k, v in PLOT_LAYOUT.items() if k not in ("xaxis", "yaxis")}, height=320, title="Module usage")
        st.plotly_chart(fig, width="stretch", config=NOBAR)
    reg = df["region"].replace("", pd.NA).dropna().value_counts().head(10)
    if len(reg):
        fig = go.Figure(go.Bar(x=reg.values, y=reg.index, orientation="h", marker=dict(color=GOLD)))
        fig.update_layout(**PLOT_LAYOUT, height=300, title="Top farm locations")
        st.plotly_chart(fig, width="stretch", config=NOBAR)
    st.dataframe(df.sort_values("ts", ascending=False), width="stretch", hide_index=True)
    st.download_button("Export usage log", df.to_csv(index=False), "agronova_usage.csv", "text/csv", icon=":material/download:")


# ═════════════════════════════ STORYBOARD (FA-1) ═════════════════════════════
def page_storyboard():
    theme.page_header("07", "FA-1 Storyboard", "From problem <em>to product.</em>",
                      "The problem research, personas, the five core features with their prompts, the LLM API settings and "
                      "the UI flow this app implements.", theme.HERO_POSTER, "Wheat at sunrise · Unsplash")
    t1, t2, t3, t4 = st.tabs(["Problem & research", "Personas", "Features & prompts", "LLM API"])
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
