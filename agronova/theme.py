"""Visual system for AgroNova — "Field Journal".

Art direction: an editorial, cinematic field journal rather than a neon dashboard.
  * Palette: deep soil, parchment, harvest gold — with leaf green, clay and sky used sparingly.
  * Type: Instrument Serif for display, Inter Tight for UI, JetBrains Mono for data/labels.
  * Surfaces: solid, filled planes (no outline boxes), generous whitespace, numbered sections, hairline rules.
  * Motion: warm colour-graded farm footage crossfading behind every page, film grain, sunlit dust motes
    (Three.js), masked headline reveals, scroll-lit manifesto text and a cursor-following image preview.

The motion layer runs from a same-origin iframe and mounts once on the parent page
(guarded by `window.parent.__agronovaFX`), so it survives Streamlit reruns.
"""
from __future__ import annotations

import datetime as dt
import json
import html as _html

import streamlit as st
import streamlit.components.v1 as components

HERO_VIDEO = "https://assets.mixkit.co/videos/17120/17120-720.mp4"         # Mixkit: flying over a golden wheat field
HERO_POSTER = "https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=1800&q=70"
FIELD_VIDEO = "https://assets.mixkit.co/videos/827/827-720.mp4"            # Mixkit: road between green fields
IMG_FARMERS = "https://images.unsplash.com/photo-1605000797499-95a51c5269ae?w=1400&q=70"
IMG_GREEN = "https://images.unsplash.com/photo-1592982537447-7440770cbfc9?w=1400&q=70"
IMG_GRAIN = "https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?w=1400&q=70"
IMG_SOIL = "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?w=1400&q=70"
IMG_ROWS = "https://images.unsplash.com/photo-1586771107445-d3ca888129ff?w=1400&q=70"
IMG_SEEDLING = "https://images.unsplash.com/photo-1530836369250-ef72a3f5cda8?w=1400&q=70"
IMG_MARKET = "https://images.unsplash.com/photo-1464226184884-fa280b87c399?w=1400&q=70"

CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root{
  --ink:#0d0b08; --soil:#17130e; --soil2:#211b14; --soil3:#2b231a;
  --cream:#f2ead9; --mut:#a59c8a; --dim:#6f675a;
  --gold:#e8b04a; --gold2:#f3c978; --leaf:#a9d46f; --clay:#d4693f; --sky:#8fc3d6;
  --rule:rgba(242,234,217,.09);
  --serif:'Instrument Serif',Georgia,serif; --sans:'Inter Tight',system-ui,sans-serif; --mono:'JetBrains Mono',ui-monospace,monospace;
  --ease:cubic-bezier(.16,1,.3,1);
}
html,body{background:var(--ink)!important}
.stApp{background:transparent!important;color:var(--cream);font-family:var(--sans)}
[data-testid="stAppViewContainer"]{background:transparent!important}
[data-testid="stAppViewContainer"] > *{position:relative;z-index:2}
[data-testid="stHeader"]{background:rgba(13,11,8,.72)!important;backdrop-filter:blur(18px) saturate(1.2)}
[data-testid="stDecoration"]{display:none}
[data-testid="stMainBlockContainer"]{padding-top:5rem;padding-bottom:5rem;max-width:1240px}
:where(.stApp) :is(p,li,label){font-family:var(--sans)}
:where(.stApp) :is(p,li){color:#e6ddca;line-height:1.65}
h1,h2,h3{font-family:var(--serif)!important;font-weight:400!important;letter-spacing:-.01em;color:var(--cream)!important}
h4,h5{font-family:var(--mono)!important;font-size:.72rem!important;font-weight:500!important;letter-spacing:.16em;text-transform:uppercase;color:var(--gold)!important;margin-bottom:.8rem!important}
a{color:var(--gold2)!important;text-decoration-color:rgba(232,176,74,.35)!important;text-underline-offset:3px}
code{font-family:var(--mono)!important;background:var(--soil2)!important;color:var(--gold2)!important;border-radius:6px;padding:.1em .35em}
strong{color:var(--cream);font-weight:600}
hr{border-color:var(--rule)!important}
::selection{background:rgba(232,176,74,.35);color:var(--cream)}
::-webkit-scrollbar{width:9px;height:9px}::-webkit-scrollbar-thumb{background:var(--soil3);border-radius:9px}::-webkit-scrollbar-track{background:transparent}

/* ── navigation ── */
[data-testid="stTopNavLink"]{border-radius:999px!important;padding:.3rem .85rem!important;transition:background .4s var(--ease)!important}
[data-testid="stTopNavLink"] > span:first-child{display:none}
[data-testid="stTopNavLink"] p{font-family:var(--mono)!important;font-size:.68rem!important;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)!important}
[data-testid="stTopNavLink"]:hover{background:var(--soil2)!important}
[data-testid="stTopNavLink"][aria-current="page"]{background:var(--cream)!important}
[data-testid="stTopNavLink"][aria-current="page"] p{color:var(--ink)!important}
[data-testid="stSidebar"]{background:var(--soil)!important;border-right:0!important}
[data-testid="stSidebar"] h2{font-size:1.9rem!important}

/* ── surfaces: solid planes, no outlines ── */
div[class*="st-key-panel"],div[class*="st-key-glass"]{background:var(--soil)!important;border-radius:20px!important;padding:1.5rem 1.6rem!important;
  box-shadow:0 30px 80px -40px rgba(0,0,0,.8)}
div[class*="st-key-panel"] div[class*="st-key-panel"]{background:var(--soil2)!important}
[data-testid="stVerticalBlockBorderWrapper"]{border:0!important;background:var(--soil)!important;border-radius:20px!important}

/* ── buttons ── */
.stButton > button,.stDownloadButton > button,[data-testid="stFormSubmitButton"] > button,[data-testid="stPageLink"] a{
  border:0!important;border-radius:999px!important;background:var(--soil2)!important;color:var(--cream)!important;
  font-family:var(--sans)!important;font-weight:500!important;padding:.55rem 1.1rem!important;min-height:2.6rem;
  transition:background .35s var(--ease),transform .35s var(--ease),color .35s!important}
.stButton > button:hover,.stDownloadButton > button:hover,[data-testid="stFormSubmitButton"] > button:hover,[data-testid="stPageLink"] a:hover{
  background:var(--soil3)!important;transform:translateY(-1px)}
.stButton > button:active{transform:translateY(0) scale(.98)}
.stButton > button p,[data-testid="stPageLink"] a span{color:inherit!important;font-weight:500}
.stButton > button[data-testid="stBaseButton-primary"],[data-testid="stFormSubmitButton"] > button[data-testid="stBaseButton-primaryFormSubmit"]{
  background:var(--gold)!important;color:var(--ink)!important}
.stButton > button[data-testid="stBaseButton-primary"]:hover,[data-testid="stFormSubmitButton"] > button[data-testid="stBaseButton-primaryFormSubmit"]:hover{background:var(--gold2)!important}
button[data-testid="stBaseButton-primary"] *,button[data-testid="stBaseButton-primaryFormSubmit"] *{color:var(--ink)!important}
[data-testid="stPageLink"] a{flex-direction:row-reverse;justify-content:space-between;padding-left:1.3rem!important}
/* pills / segmented */
[data-testid="stButtonGroup"] button{border:0!important;background:var(--soil2)!important;border-radius:999px!important;color:var(--mut)!important;
  font-family:var(--sans)!important;transition:background .3s,color .3s!important}
[data-testid="stButtonGroup"] button:hover{color:var(--cream)!important}
[data-testid="stButtonGroup"] button[aria-checked="true"],[data-testid="stButtonGroup"] button[kind*="Active"]{background:var(--cream)!important;color:var(--ink)!important}
[data-testid="stButtonGroup"] button[aria-checked="true"] *,[data-testid="stButtonGroup"] button[kind*="Active"] *{color:var(--ink)!important}

/* ── inputs ── */
[data-baseweb="input"],[data-baseweb="select"] > div,[data-baseweb="textarea"],.stNumberInput input{
  background:var(--soil2)!important;border:0!important;border-radius:12px!important;transition:box-shadow .3s}
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea{color:var(--cream)!important;font-family:var(--sans)!important}
[data-baseweb="input"]:focus-within,[data-baseweb="select"] > div:focus-within,[data-baseweb="textarea"]:focus-within{box-shadow:0 0 0 2px rgba(232,176,74,.55)!important}
[data-baseweb="tag"]{background:var(--soil3)!important;border-radius:999px!important}
[data-baseweb="popover"] ul,[data-baseweb="menu"]{background:var(--soil2)!important}
[data-testid="stWidgetLabel"] p{font-family:var(--mono)!important;font-size:.68rem!important;letter-spacing:.12em;text-transform:uppercase;color:var(--mut)!important}
[data-testid="stSlider"] [role="slider"]{background:var(--gold)!important;box-shadow:none!important}
[data-testid="stFileUploaderDropzone"]{background:var(--soil2)!important;border:1px dashed rgba(242,234,217,.15)!important;border-radius:14px!important}

/* ── tabs ── */
[data-testid="stTabs"] [data-baseweb="tab-list"]{gap:1.6rem;background:transparent;border-bottom:1px solid var(--rule)}
[data-testid="stTabs"] [data-baseweb="tab"]{padding:.7rem 0;background:transparent!important}
[data-testid="stTabs"] [data-baseweb="tab"] p{font-family:var(--mono)!important;font-size:.72rem!important;letter-spacing:.12em;text-transform:uppercase;color:var(--mut)}
[data-testid="stTabs"] [aria-selected="true"] p{color:var(--cream)!important}
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{background:var(--gold)!important;height:2px}
[data-testid="stTabs"] [data-baseweb="tab-border"]{display:none}
[data-testid="stTabPanel"]{padding-top:1.4rem;animation:fade .7s var(--ease)}

/* ── metrics: big serif numerals, ruled ── */
[data-testid="stMetric"]{padding:.2rem 0 .2rem 1rem;border-left:1px solid var(--rule)}
[data-testid="stMetricValue"]{font-family:var(--serif)!important;font-size:clamp(1.9rem,3vw,2.6rem)!important;line-height:1.05;color:var(--cream)!important}
[data-testid="stMetricLabel"] p{font-family:var(--mono)!important;font-size:.64rem!important;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)!important}
[data-testid="stMetricDelta"]{font-family:var(--mono)!important;font-size:.72rem!important}

/* ── chat: assistant writes on the page, user speaks in a bubble ── */
[data-testid="stChatMessage"]{background:transparent!important;border:0!important;padding:.4rem 0!important;margin-bottom:1.6rem;animation:fade .8s var(--ease) both;gap:1rem}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){flex-direction:row-reverse}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"]{
  background:var(--soil2);border-radius:22px 22px 6px 22px;padding:.9rem 1.2rem;max-width:min(78%,640px);margin-left:auto;flex:0 1 auto}
[data-testid="stChatMessageAvatarUser"],[data-testid="stChatMessageAvatarAssistant"],[data-testid="stChatMessageAvatarCustom"]{
  background:var(--soil2)!important;border-radius:50%!important;color:var(--gold)!important}
[data-testid="stChatMessageAvatarAssistant"]{background:var(--gold)!important;color:var(--ink)!important}
[data-testid="stChatMessageContent"]{font-size:1.02rem}
[data-testid="stChatMessageContent"] p{color:#ece4d2}
[data-testid="stChatMessageContent"] table{border-collapse:collapse;font-size:.92rem;margin:.8rem 0}
[data-testid="stChatMessageContent"] th{font-family:var(--mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);background:transparent!important;border:0!important;border-bottom:1px solid var(--rule)!important}
[data-testid="stChatMessageContent"] td{border:0!important;border-bottom:1px solid var(--rule)!important;padding:.6rem .7rem!important}
[data-testid="stChatMessageContent"] blockquote{border-left:2px solid var(--clay);color:var(--mut)}
[data-testid="stChatInput"]{background:var(--soil2)!important;border:0!important;border-radius:24px!important;box-shadow:0 20px 60px -20px rgba(0,0,0,.9)}
[data-testid="stChatInput"]:focus-within{box-shadow:0 0 0 2px rgba(232,176,74,.45),0 20px 60px -20px rgba(0,0,0,.9)!important}
[data-testid="stChatInput"] textarea{font-family:var(--sans)!important;color:var(--cream)!important}
[data-testid="stBottom"] > div,[data-testid="stBottomBlockContainer"]{background:linear-gradient(0deg,var(--ink) 55%,transparent)!important}

/* ── expander / status ── */
[data-testid="stExpander"] details{background:var(--soil)!important;border:0!important;border-radius:14px!important}
[data-testid="stExpander"] summary p{font-family:var(--mono)!important;font-size:.72rem!important;letter-spacing:.08em;color:var(--mut)!important}
[data-testid="stExpander"] summary:hover p{color:var(--gold2)!important}
[data-testid="stStatusWidget"]{display:none}
[data-testid="stAlert"]{background:var(--soil)!important;border:0!important;border-radius:14px}
[data-testid="stCaption"],.stCaption{font-family:var(--mono)!important;font-size:.7rem!important;color:var(--dim)!important;letter-spacing:.04em}
[data-testid="stProgress"] > div > div > div{background:var(--gold)!important}
[data-testid="stDataFrame"]{border-radius:14px;overflow:hidden}

/* ── motion utilities ── */
@keyframes fade{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.reveal{opacity:0;transform:translateY(28px);transition:opacity 1.2s var(--ease),transform 1.4s var(--ease)}
.reveal.in{opacity:1;transform:none}
/* Fail-safe: if the motion script is ever late or blocked, content still fades in on its own after ~2 s */
.reveal:not(.in){animation:rvfb 1.1s 1.8s var(--ease) forwards}
@keyframes rvfb{to{opacity:1;transform:none}}
.tilt{will-change:transform;transition:transform .6s var(--ease)}
.mask{display:block;overflow:hidden}
.mask > span{display:inline-block;transform:translateY(105%);animation:maskup 1.4s var(--ease) forwards}
@keyframes maskup{to{transform:none}}

/* ── type helpers ── */
.kicker{font:500 .7rem var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--mut);display:flex;gap:.9rem;align-items:center}
.kicker b{color:var(--gold);font-weight:500}
.display{font-family:var(--serif);font-weight:400;font-size:clamp(2.6rem,6vw,5.4rem);line-height:.98;letter-spacing:-.02em;color:var(--cream);margin:.5rem 0 1rem}
.display em,.h2 em{font-style:italic;color:var(--gold2)}
.h2{font-family:var(--serif);font-size:clamp(2rem,4vw,3.4rem);line-height:1;letter-spacing:-.015em;color:var(--cream);margin:.4rem 0 .8rem}
.dek{color:var(--mut);font-size:1.06rem;line-height:1.65;max-width:560px}
.rule{height:1px;background:var(--rule);margin:2.4rem 0}

/* ── page header ── */
.phead{display:grid;grid-template-columns:1.35fr .9fr;gap:3rem;align-items:end;padding:1.2rem 0 2.2rem;margin-bottom:2rem;border-bottom:1px solid var(--rule)}
.phead figure{margin:0;position:relative;border-radius:18px;overflow:hidden;aspect-ratio:5/4}
.phead figure img{width:100%;height:100%;object-fit:cover;transform:scale(1.08);transition:transform 2.4s var(--ease);filter:saturate(.85) sepia(.12)}
.phead.in figure img,.phead figure:hover img{transform:scale(1)}
.phead figcaption{position:absolute;left:12px;bottom:12px;font:500 .62rem var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--cream);
  background:rgba(13,11,8,.55);backdrop-filter:blur(6px);padding:.35rem .6rem;border-radius:6px}
@media (max-width:860px){.phead{grid-template-columns:1fr;gap:1.4rem}.phead figure{aspect-ratio:16/9}}

/* ── hero (full-bleed) ── */
.hero{position:relative;width:100vw;margin-left:calc(50% - 50vw);margin-top:-5rem;height:calc(100vh - 2.6rem);min-height:620px;overflow:hidden;isolation:isolate;color:var(--cream)}
.hero video,.hero .poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:sepia(.28) saturate(.95) brightness(.72) contrast(1.06);
  transform:scale(1.12);animation:settle 3.2s var(--ease) forwards}
@keyframes settle{to{transform:scale(1.02)}}
.hero .shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(13,11,8,.55) 0%,rgba(13,11,8,0) 30%,rgba(13,11,8,.1) 55%,var(--ink) 100%),
  linear-gradient(90deg,rgba(13,11,8,.65) 0%,rgba(13,11,8,0) 60%)}
.hero .meta{position:absolute;top:5.4rem;left:clamp(1.2rem,4vw,3.4rem);right:clamp(1.2rem,4vw,3.4rem);display:flex;justify-content:space-between;gap:1rem;
  font:500 .66rem var(--mono);letter-spacing:.18em;text-transform:uppercase;color:rgba(242,234,217,.75);opacity:0;animation:fade 1.2s .2s var(--ease) forwards}
.hero .meta span:nth-child(2){display:none}
@media (min-width:900px){.hero .meta span:nth-child(2){display:inline}}
.hero .body{position:absolute;left:clamp(1.2rem,4vw,3.4rem);right:clamp(1.2rem,4vw,3.4rem);bottom:clamp(6rem,14vh,9rem);display:grid;grid-template-columns:1.6fr .8fr;gap:3rem;align-items:end}
.hero h1{font-family:var(--serif)!important;font-weight:400!important;font-size:clamp(3rem,8.4vw,8.2rem)!important;line-height:.9!important;letter-spacing:-.03em;margin:0!important;color:var(--cream)!important}
.hero h1 em{font-style:italic;color:var(--gold2)}
.hero h1 .mask:nth-child(2) > span{animation-delay:.12s}.hero h1 .mask:nth-child(3) > span{animation-delay:.24s}
.hero .side{opacity:0;animation:fade 1.4s .7s var(--ease) forwards}
.hero .side p{color:rgba(242,234,217,.82);font-size:1.02rem;margin:0 0 1.2rem}
.hero .cta{display:inline-flex;align-items:center;gap:.7rem;padding:.85rem 1.3rem;border-radius:999px;background:var(--cream);color:var(--ink)!important;text-decoration:none!important;
  font:600 .92rem var(--sans);transition:background .4s var(--ease),gap .4s var(--ease)}
.hero .cta:hover{background:var(--gold2);gap:1rem}
.hero .foot{position:absolute;left:0;right:0;bottom:0;display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid rgba(242,234,217,.12);
  background:rgba(13,11,8,.35);backdrop-filter:blur(10px);opacity:0;animation:fade 1.2s 1s var(--ease) forwards}
.hero .foot div{padding:1.1rem clamp(1.2rem,4vw,3.4rem);border-right:1px solid rgba(242,234,217,.08)}
.hero .foot b{display:block;font:400 1.9rem/1 var(--serif);color:var(--cream)}
.hero .foot span{font:500 .62rem var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--mut)}
@media (max-width:860px){.hero .body{grid-template-columns:1fr;gap:1.4rem;bottom:8.5rem}.hero .foot{grid-template-columns:repeat(2,1fr)}.hero .foot div:nth-child(n+3){display:none}}

/* ── gold ticker stamp ── */
.ticker{width:100vw;margin-left:calc(50% - 50vw);background:var(--gold);color:var(--ink);overflow:hidden;padding:.9rem 0;margin-top:0;margin-bottom:5rem;transform:rotate(-1.2deg) scale(1.02)}
.ticker .t{display:flex;gap:2.4rem;width:max-content;animation:tick 40s linear infinite}
.ticker span{font:400 1.7rem var(--serif);white-space:nowrap;color:var(--ink)}
.ticker span i{font-style:normal;font-size:1rem;vertical-align:middle;margin-left:2.4rem}
@keyframes tick{to{transform:translateX(-50%)}}

/* ── editorial feature index ── */
.idx{border-top:1px solid var(--rule)}
.idx .row{display:grid;grid-template-columns:4rem 1.3fr 1.6fr 2rem;gap:1.4rem;align-items:center;padding:1.6rem .4rem;border-bottom:1px solid var(--rule);
  transition:padding .6s var(--ease),background .6s var(--ease);cursor:default;position:relative}
.idx .row:hover{padding-left:1.4rem;background:linear-gradient(90deg,rgba(232,176,74,.07),transparent 70%)}
.idx .n{font:500 .72rem var(--mono);color:var(--dim);letter-spacing:.1em}
.idx .ti{font:400 clamp(1.6rem,3vw,2.5rem)/1 var(--serif);color:var(--cream);transition:color .4s}
.idx .row:hover .ti{color:var(--gold2)}
.idx .de{color:var(--mut);font-size:.95rem;line-height:1.5}
.idx .ar{font-size:1.2rem;color:var(--dim);transition:transform .5s var(--ease),color .4s}
.idx .row:hover .ar{transform:translateX(6px) rotate(-45deg);color:var(--gold)}
.idx .th{display:none}
@media (max-width:760px){.idx .row{grid-template-columns:2.4rem 1fr;}.idx .de{grid-column:2}.idx .ar{display:none}
  .idx .th{display:block;grid-column:1/-1;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:12px}}
#agro-preview{position:fixed;left:0;top:0;width:300px;height:380px;border-radius:14px;overflow:hidden;pointer-events:none;z-index:50;opacity:0;
  transform:translate3d(-50%,-50%,0) scale(.85);transition:opacity .45s var(--ease),transform .6s var(--ease);will-change:transform,opacity}
#agro-preview.on{opacity:1}
#agro-preview img{width:100%;height:100%;object-fit:cover;filter:sepia(.15)}

/* ── manifesto: words light up as you scroll ── */
.manifesto{font:400 clamp(2rem,4.6vw,4rem)/1.12 var(--serif);letter-spacing:-.015em;margin:6rem 0;max-width:1100px}
.manifesto .w{color:var(--cream);opacity:.14;transition:opacity .5s ease,color .5s ease}
.manifesto .w.lit{opacity:1}
.manifesto .w.g.lit{color:var(--gold2);font-style:italic}

/* ── media + captions ── */
.duo{display:grid;grid-template-columns:1.15fr 1fr;gap:4rem;align-items:center;margin:6rem 0}
.duo.flip{grid-template-columns:1fr 1.15fr}
.duo figure{margin:0;position:relative;border-radius:20px;overflow:hidden;aspect-ratio:4/5}
.duo figure video,.duo figure img{width:100%;height:100%;object-fit:cover;filter:sepia(.18) saturate(.92)}
.cap{display:flex;justify-content:space-between;margin-top:.7rem;font:500 .62rem var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.steps{margin-top:2rem}
.steps div{display:grid;grid-template-columns:3rem 1fr;gap:1rem;padding:1.15rem 0;border-top:1px solid var(--rule)}
.steps div:last-child{border-bottom:1px solid var(--rule)}
.steps i{font:500 .7rem var(--mono);color:var(--gold);font-style:normal;padding-top:.3rem}
.steps b{display:block;font:500 1.05rem var(--sans);color:var(--cream);margin-bottom:.2rem}
.steps span{color:var(--mut);font-size:.93rem}
@media (max-width:860px){.duo,.duo.flip{grid-template-columns:1fr;gap:2rem}.duo figure{aspect-ratio:4/3}}
.strip{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:1rem;margin:2rem 0 6rem}
.strip figure{margin:0}.strip img{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:14px;filter:sepia(.15) saturate(.9)}
.strip figure:first-child img{aspect-ratio:auto;height:100%;max-height:520px}
@media (max-width:760px){.strip{grid-template-columns:1fr 1fr}.strip figure:first-child{grid-column:1/-1}}
.bignums{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);margin:2rem 0}
.bignums div{padding:1.8rem 1.2rem;border-right:1px solid var(--rule)}.bignums div:last-child{border-right:0}
.bignums b{display:block;font:400 clamp(2.6rem,5vw,4.4rem)/1 var(--serif);color:var(--cream)}
.bignums span{font:500 .64rem var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--mut)}
@media (max-width:760px){.bignums{grid-template-columns:1fr 1fr}.bignums div:nth-child(2){border-right:0}}

/* ── module banner (feature studio) ── */
.mod{display:grid;grid-template-columns:auto 1fr;gap:1.6rem;align-items:center;margin:1.2rem 0 1.6rem}
.mod img{width:120px;height:120px;object-fit:cover;border-radius:16px;filter:sepia(.15)}
.mod .ti{font:400 2.4rem/1 var(--serif);color:var(--cream)}.mod .de{color:var(--mut);margin-top:.4rem}

/* ── chat bits ── */
.trace{display:flex;flex-wrap:wrap;gap:.45rem;margin:.1rem 0 .8rem}
.trace span{font:500 .7rem var(--mono);padding:.38rem .7rem;border-radius:999px;background:var(--soil2);color:var(--mut);display:inline-flex;align-items:center;gap:.45rem;animation:fade .5s var(--ease) both}
.trace span:before{content:"";width:6px;height:6px;border-radius:50%;background:var(--gold);animation:pulse 1s ease-in-out infinite}
.trace span.ok{color:#d9cfbb}.trace span.ok:before{background:var(--leaf);animation:none}
@keyframes pulse{50%{opacity:.25}}
.typing{display:inline-flex;gap:6px;padding:.6rem 0}.typing i{width:6px;height:6px;border-radius:50%;background:var(--cream);opacity:.3;animation:dots 1.2s infinite}
.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}
@keyframes dots{40%{opacity:1;transform:translateY(-3px)}}
.loc{display:inline-flex;align-items:center;gap:.6rem;font:500 .7rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
.loc:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--dim)}
.loc.on{color:var(--cream)}.loc.on:before{background:var(--leaf);box-shadow:0 0 0 4px rgba(169,212,111,.15)}

/* ── home: live hubs + ask ── */
.hubs{display:grid;grid-template-columns:repeat(6,1fr);gap:.7rem}
.hub{background:var(--soil);border-radius:16px;padding:1rem;display:flex;flex-direction:column;gap:.2rem;transition:transform .5s var(--ease),background .3s}
.hub:hover{transform:translateY(-4px);background:var(--soil2)}
.hn{font:400 1.45rem/1 var(--serif);color:var(--cream)}.hs{font:500 .62rem var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
.ht{font:400 2.3rem/1 var(--serif);color:var(--gold2);margin:.6rem 0 .1rem}.ht small{font-size:.9rem;color:var(--mut)}
.hk{font-size:.85rem;color:#e6ddca}.hm{font:400 .66rem/1.55 var(--mono);color:var(--mut);margin:.35rem 0 .5rem}
.hub .tg{align-self:flex-start}
@media (max-width:1000px){.hubs{grid-template-columns:repeat(2,1fr)}}
div.st-key-panel_ask{margin:-1.5rem 0 1rem;padding:2rem 2rem 1.6rem!important;background:linear-gradient(135deg,#211b14,#17130e)!important}
div.st-key-panel_ask [data-baseweb="input"]{background:var(--ink)!important;min-height:3.2rem}
div.st-key-panel_ask [data-baseweb="input"] input{font-size:1.05rem!important}
.month .steps{margin-top:0}

/* ── field planner week ── */
.week{display:grid;grid-template-columns:repeat(7,1fr);gap:.7rem;margin:.4rem 0 .6rem}
.day{background:var(--soil);border-radius:16px;padding:1rem .9rem;display:flex;flex-direction:column;gap:.25rem;transition:transform .5s var(--ease),background .3s}
.day:hover{transform:translateY(-4px);background:var(--soil2)}
.dw{font:500 .66rem var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--gold)}
.dd{font-size:.78rem;color:var(--dim)}
.dt{font:400 2rem/1 var(--serif);color:var(--cream);margin:.3rem 0 .1rem}.dt small{font-size:1rem;color:var(--mut)}
.ds{font-size:.82rem;color:#e6ddca}
.dm{font:400 .66rem/1.5 var(--mono);color:var(--mut);margin:.3rem 0}
.tgs{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:auto}
.tg{font:500 .6rem var(--mono);letter-spacing:.06em;text-transform:uppercase;padding:.25rem .45rem;border-radius:6px;background:var(--soil3);color:var(--mut)}
.tg.leaf{background:rgba(169,212,111,.14);color:var(--leaf)}.tg.gold{background:rgba(232,176,74,.16);color:var(--gold2)}
.tg.clay{background:rgba(212,105,63,.18);color:#f0a07c}.tg.sky{background:rgba(143,195,214,.16);color:var(--sky)}.tg.dim{opacity:.7}
@media (max-width:900px){.week{grid-template-columns:repeat(2,1fr)}}
.texture{display:flex;height:14px;border-radius:7px;overflow:hidden;margin-top:1rem;gap:2px}
.season{display:flex;flex-direction:column;gap:.55rem;margin-top:.4rem}
.srow{display:grid;grid-template-columns:4.2rem 1fr;align-items:center;gap:.6rem}
.srow b{font:500 .7rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
.months{display:grid;grid-template-columns:repeat(12,1fr);gap:3px}
.months i{height:16px;border-radius:4px;background:var(--soil3)}.months i.on{background:var(--c)}
.months i.now{outline:2px solid var(--cream);outline-offset:1px}
.months.lab span{font:500 .62rem var(--mono);text-align:center;color:var(--dim)}.months.lab span.now{color:var(--cream)}

/* ── disease risk + crop fit ── */
.risk{display:flex;flex-direction:column;gap:.2rem;padding:1rem 1.1rem;border-radius:14px;background:var(--soil2)}
.risk b{font:400 2.6rem/1 var(--serif)}.risk span{font:500 .66rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
.risk.leaf b{color:var(--leaf)}.risk.gold b{color:var(--gold2)}.risk.clay b{color:#f0a07c}
.fits{display:flex;flex-direction:column;gap:.15rem;margin-top:.4rem}
.fit{display:grid;grid-template-columns:12rem 1fr 2.6rem;grid-template-rows:auto auto;column-gap:1rem;align-items:center;padding:.7rem 0;border-bottom:1px solid var(--rule)}
.fit b{font:400 1.25rem var(--serif);color:var(--cream)}
.fbar{height:8px;border-radius:4px;background:var(--soil3);overflow:hidden}.fbar i{display:block;height:100%;border-radius:4px;transition:width 1.4s var(--ease)}
.fs{font:500 .9rem var(--mono);color:var(--cream);text-align:right}
.fn{grid-column:2/4;font:400 .66rem var(--mono);color:var(--dim);letter-spacing:.04em;margin-top:.25rem}
@media (max-width:760px){.fit{grid-template-columns:1fr 2.4rem}.fit .fbar{grid-column:1/3;grid-row:2}.fn{grid-column:1/3}}

/* ── status checks ── */
.health{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.7rem;margin:.4rem 0 1.6rem}
.hc{background:var(--soil);border-radius:14px;padding:.9rem 1rem;display:flex;flex-direction:column;gap:.2rem}
.hc b{font:500 .95rem var(--sans);color:var(--cream);display:flex;align-items:center;gap:.5rem}
.hc b:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--leaf);box-shadow:0 0 0 4px rgba(169,212,111,.15)}
.hc.bad b:before{background:var(--clay);box-shadow:0 0 0 4px rgba(212,105,63,.18)}
.hc span{font:400 .7rem var(--mono);color:var(--mut)}
.badge{display:inline-flex;align-items:center;gap:.5rem;font:500 .66rem var(--mono);letter-spacing:.12em;text-transform:uppercase;
  color:var(--gold2);background:rgba(232,176,74,.1);padding:.4rem .7rem;border-radius:999px;margin:.2rem 0 1rem}

/* ── journey + prompt anatomy ── */
.journey{display:grid;grid-template-columns:repeat(5,1fr);gap:.7rem;margin:1rem 0}
.journey div{background:var(--soil);border-radius:16px;padding:1.1rem 1rem;position:relative}
.journey div:not(:last-child):after{content:"→";position:absolute;right:-.7rem;top:50%;transform:translateY(-50%);color:var(--gold);font-size:1.1rem;z-index:2}
.journey i{font:500 .66rem var(--mono);color:var(--gold);font-style:normal;letter-spacing:.14em}
.journey b{display:block;font:400 1.35rem/1.1 var(--serif);color:var(--cream);margin:.4rem 0 .3rem}
.journey span{font-size:.84rem;color:var(--mut)}
@media (max-width:900px){.journey{grid-template-columns:1fr}.journey div:after{display:none}}
.anat{background:var(--soil);border-radius:16px;padding:1.3rem 1.4rem;font:400 1.05rem/1.9 var(--sans);color:#e6ddca}
.anat mark{background:none;padding:.1rem .35rem;border-radius:6px;color:var(--ink);font-weight:500}
.anat .k1{background:var(--gold)}.anat .k2{background:var(--leaf)}.anat .k3{background:var(--sky)}.anat .k4{background:#f0a07c}
.legend{display:flex;flex-wrap:wrap;gap:1rem;margin-top:.8rem;font:500 .66rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
.legend span:before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:.4rem;vertical-align:-1px;background:var(--c)}
.srcs{display:flex;flex-wrap:wrap;gap:.5rem;align-items:stretch;margin:1rem 0 .4rem}
.srcs .lab{font:500 .64rem var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--dim);align-self:center;margin-right:.3rem}
.srcs a{display:flex;flex-direction:column;gap:.1rem;max-width:230px;padding:.55rem .8rem;border-radius:12px;background:var(--soil2);
  text-decoration:none!important;transition:background .3s,transform .4s var(--ease);animation:fade .5s var(--ease) both}
.srcs a:hover{background:var(--soil3);transform:translateY(-2px)}
.srcs a b{font:500 .68rem var(--mono);color:var(--gold2);letter-spacing:.04em}
.srcs a span{font-size:.78rem;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.suggest{font:400 2.4rem/1.05 var(--serif);color:var(--cream);margin:2.2rem 0 1.2rem;max-width:720px}
.suggest em{color:var(--gold2)}

/* ── footer ── */
.foot2{margin-top:7rem;padding:3rem 0 1rem;border-top:1px solid var(--rule);display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:2rem}
.foot2 .mark{font:400 clamp(3rem,8vw,6.5rem)/.9 var(--serif);color:var(--cream);letter-spacing:-.03em}
.foot2 .mark em{color:var(--gold2)}
.foot2 h6{font:500 .64rem var(--mono)!important;letter-spacing:.16em;text-transform:uppercase;color:var(--dim)!important;margin:0 0 .8rem!important}
.foot2 p{font-size:.88rem;color:var(--mut);margin:.2rem 0}
@media (max-width:760px){.foot2{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.reveal,.mask > span{opacity:1;transform:none}.manifesto .w{opacity:1}}
</style>
"""

# Runs in the Streamlit page's own window (injected once as a <script> element), so it survives iframe rebuilds.
FX_CORE = r"""
(function(){
  const P = window, D = document;
  if (P.__agronovaFX) { P.__agronovaFX.refresh && P.__agronovaFX.refresh(); return; }
  P.__agronovaFX = { version: 3 };
  const reduce = P.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const touch = P.matchMedia('(pointer: coarse)').matches;

  /* 1 ── warm colour-graded farm footage, crossfading every 12 s ── */
  const CLIPS = [17120, 827, 17764, 47816, 23781, 45379];
  const Q = touch ? 360 : 720;
  const st = D.createElement('style');
  st.textContent = `
    #agro-video{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;background:#0d0b08}
    #agro-video video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;
      filter:sepia(.35) saturate(.9) brightness(.58) contrast(1.08);transform:scale(1.06);
      transition:opacity 2.6s cubic-bezier(.16,1,.3,1),transform 16s linear}
    #agro-video video.on{opacity:1;transform:scale(1.14)}
    #agro-veil{position:fixed;inset:0;z-index:0;pointer-events:none;
      background:linear-gradient(180deg,rgba(13,11,8,.35),rgba(13,11,8,.62) 45%,rgba(13,11,8,.9)),
                 radial-gradient(70% 60% at 85% 0%,rgba(232,176,74,.16),transparent 60%)}
    #agro-grain{position:fixed;inset:-50%;z-index:1;pointer-events:none;opacity:.09;mix-blend-mode:overlay;
      background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
      animation:agrain .9s steps(5) infinite}
    @keyframes agrain{20%{transform:translate(-3%,2%)}40%{transform:translate(2%,-3%)}60%{transform:translate(-2%,-1%)}80%{transform:translate(3%,3%)}}`;
  D.head.appendChild(st);
  const vwrap = D.createElement('div'); vwrap.id = 'agro-video';
  const veil = D.createElement('div'); veil.id = 'agro-veil';
  const grain = D.createElement('div'); grain.id = 'agro-grain';

  /* Robust two-player playlist:
     - each player loops, so a clip never "ends" into black
     - the next clip is preloaded right after every swap, and a swap only happens when it is ready
     - a single `busy` flag means swaps can never overlap (the old bug: overlapping swaps on slow networks)
     - a watchdog restarts a paused/stalled player and skips clips that error out
     - a still photo sits underneath, so the worst case is a warm image, never a black screen */
  vwrap.style.background = '#0d0b08 url(https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=1600&q=60) center/cover no-repeat';
  const mk = () => { const v = D.createElement('video'); v.muted = true; v.defaultMuted = true; v.playsInline = true; v.loop = true;
    v.setAttribute('muted',''); v.setAttribute('playsinline',''); v.setAttribute('loop',''); v.preload = 'auto'; vwrap.appendChild(v); return v; };
  const A = mk(), B = mk(); let idx = 0, cur = A, nxt = B, busy = false, lastT = -1, stuck = 0;
  const src = i => `https://assets.mixkit.co/videos/${CLIPS[i]}/${CLIPS[i]}-${Q}.mp4`;
  const play = v => { const p = v.play(); if (p && p.catch) p.catch(()=>{}); };
  function preload(){ nxt.src = src((idx + 1) % CLIPS.length); nxt.load(); }
  A.src = src(0);
  A.addEventListener('playing', ()=>{ A.classList.add('on'); preload(); }, {once:true});
  play(A);
  function swap(force){
    if (busy || D.hidden) return;
    if (nxt.readyState < 3 && !force) return;          // not buffered yet → keep the current clip looping, try next tick
    busy = true;
    const incoming = nxt, outgoing = cur;
    incoming.currentTime = 0; play(incoming);
    incoming.classList.add('on'); outgoing.classList.remove('on');
    cur = incoming; nxt = outgoing; idx = (idx + 1) % CLIPS.length; lastT = -1; stuck = 0;
    setTimeout(()=>{ outgoing.pause(); preload(); busy = false; }, 2800);   // after the crossfade, queue the following clip
  }
  [A,B].forEach(v=>v.addEventListener('error', ()=>{ if (v === nxt && !busy) { idx = (idx + 1) % CLIPS.length; preload(); } }));
  if (!reduce) P.setInterval(()=>swap(false), 13000);
  P.setInterval(()=>{                                     // watchdog
    if (D.hidden) return;
    if (cur.paused) play(cur);
    if (Math.abs(cur.currentTime - lastT) < 0.01) { if (++stuck >= 4 && nxt.readyState >= 2) swap(true); } else stuck = 0;
    lastT = cur.currentTime;
    if (!cur.classList.contains('on') && !busy) cur.classList.add('on');
  }, 2000);
  D.addEventListener('visibilitychange', ()=>{ if (D.hidden) { cur.pause(); } else { play(cur); } });
  ['pointerdown','touchstart','keydown'].forEach(ev=>D.addEventListener(ev, ()=>{ if (cur.paused) play(cur); }, {passive:true}));
  D.body.prepend(grain); D.body.prepend(veil); D.body.prepend(vwrap);

  /* 2 ── sunlit dust motes (Three.js): soft bokeh drifting through the light ── */
  const host = D.createElement('div'); host.id = 'agro-webgl';
  host.style.cssText = 'position:fixed;inset:0;z-index:1;pointer-events:none;opacity:0;transition:opacity 2.5s cubic-bezier(.16,1,.3,1)';
  veil.after(host);
  const mod = D.createElement('script'); mod.type = 'module';
  mod.textContent = `
    import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
    const host = document.getElementById('agro-webgl');
    const R = new THREE.WebGLRenderer({antialias:false, alpha:true, powerPreference:'low-power'});
    R.setPixelRatio(Math.min(devicePixelRatio, 1.5)); R.setSize(innerWidth, innerHeight); host.appendChild(R.domElement);
    const scene = new THREE.Scene(); const cam = new THREE.PerspectiveCamera(55, innerWidth/innerHeight, .1, 100); cam.position.z = 12;
    const N = __N__, pos = new Float32Array(N*3), seed = new Float32Array(N);
    for (let i=0;i<N;i++){ pos[i*3]=(Math.random()-.5)*30; pos[i*3+1]=(Math.random()-.5)*18; pos[i*3+2]=(Math.random()-.5)*14; seed[i]=Math.random(); }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos,3)); g.setAttribute('seed', new THREE.BufferAttribute(seed,1));
    const m = new THREE.ShaderMaterial({ transparent:true, depthWrite:false, blending:THREE.AdditiveBlending,
      uniforms:{t:{value:0}, px:{value:R.getPixelRatio()}, mouse:{value:new THREE.Vector2()}},
      vertexShader:\`attribute float seed; uniform float t; uniform float px; uniform vec2 mouse; varying float vS; varying float vZ;
        void main(){ vec3 p=position; float s=seed*6.2831;
          p.x += sin(t*.08+s)*1.6 + t*.12*(seed-.3); p.y += cos(t*.06+s*1.3)*1.1 + sin(t*.15+s)*.3;
          p.x = mod(p.x+15.,30.)-15.; p.xy += mouse*(.4+seed)*.6;
          vec4 mv = modelViewMatrix*vec4(p,1.); gl_Position = projectionMatrix*mv;
          gl_PointSize = (6. + 34.*seed*seed) * px / -mv.z; vS=seed; vZ=-mv.z; }\`,
      fragmentShader:\`varying float vS; varying float vZ; uniform float t;
        void main(){ float d=length(gl_PointCoord-.5); float core=smoothstep(.5,.0,d); float soft=pow(core,2.2);
          float tw=.6+.4*sin(t*.9+vS*50.); vec3 c=mix(vec3(1.,.82,.5), vec3(1.,.95,.8), vS);
          float a = soft * tw * mix(.55,.18,smoothstep(.6,1.,vS)) * smoothstep(22.,6.,vZ);
          gl_FragColor=vec4(c, a); }\`});
    scene.add(new THREE.Points(g, m));
    let mx=0,my=0,tx=0,ty=0; addEventListener('pointermove',e=>{ tx=e.clientX/innerWidth-.5; ty=.5-e.clientY/innerHeight; },{passive:true});
    addEventListener('resize',()=>{ R.setSize(innerWidth,innerHeight); cam.aspect=innerWidth/innerHeight; cam.updateProjectionMatrix(); });
    let run=true; document.addEventListener('visibilitychange',()=>{ run=!document.hidden; if(run) loop(); });
    const clock = new THREE.Clock();
    function loop(){ if(!run) return; requestAnimationFrame(loop); mx+=(tx-mx)*.03; my+=(ty-my)*.03;
      m.uniforms.t.value=clock.getElapsedTime(); m.uniforms.mouse.value.set(mx,my); R.render(scene,cam); }
    loop(); requestAnimationFrame(()=>host.style.opacity=1);
  `.replace('__N__', touch ? 260 : 700);
  if (!reduce) D.head.appendChild(mod);

  /* 3 ── cursor-following image preview for the editorial index ── */
  const pv = D.createElement('div'); pv.id = 'agro-preview'; pv.innerHTML = '<img alt="">'; D.body.appendChild(pv);
  let px=0,py=0,qx=0,qy=0,pvOn=false;
  if (!touch && !reduce){
    D.addEventListener('pointermove', e=>{ px=e.clientX; py=e.clientY;
      const row = e.target.closest && e.target.closest('.idx .row[data-img]');
      if (row){ const s=row.dataset.img; const im=pv.firstChild; if(im.getAttribute('src')!==s) im.src=s; if(!pvOn){ qx=px; qy=py; } pvOn=true; pv.classList.add('on'); }
      else if (pvOn){ pvOn=false; pv.classList.remove('on'); } }, {passive:true});
    (function f(){ qx+=(px-qx)*.12; qy+=(py-qy)*.12; const r=(px-qx)*.04;
      pv.style.transform=`translate3d(${qx+40}px,${qy-190}px,0) rotate(${Math.max(-8,Math.min(8,r))}deg) scale(${pvOn?1:.85})`; P.requestAnimationFrame(f); })();
  }

  /* 4 ── subtle tilt on figures marked .tilt ── */
  if (!touch && !reduce) D.addEventListener('pointermove', e=>{
    const c = e.target.closest && e.target.closest('.tilt');
    D.querySelectorAll('.tilt[data-t]').forEach(t=>{ if(t!==c){ t.removeAttribute('data-t'); t.style.transform=''; } });
    if (!c) return; const r=c.getBoundingClientRect(); const x=(e.clientX-r.left)/r.width-.5, y=(e.clientY-r.top)/r.height-.5;
    c.dataset.t=1; c.style.transform=`perspective(1200px) rotateY(${x*5}deg) rotateX(${-y*5}deg)`; }, {passive:true});

  /* 5 ── reveals, count-ups, manifesto word lighting, video autoplay fix ── */
  function show(el){ el.classList.add('in');
    el.querySelectorAll('[data-count]').forEach(n=>{ const to=parseFloat(n.dataset.count); const t0=performance.now();
      (function step(t){ const k=Math.min(1,(t-t0)/2000), e=1-Math.pow(1-k,4); n.textContent=Math.round(to*e).toLocaleString(); if(k<1) P.requestAnimationFrame(step); })(t0); }); }
  function scan(){ const H=P.innerHeight;
    D.querySelectorAll('.reveal:not(.in)').forEach(el=>{ const r=el.getBoundingClientRect(); if(r.height>0 && r.top<H*.88 && r.bottom>0) show(el); });
    D.querySelectorAll('.manifesto').forEach(m=>{ const r=m.getBoundingClientRect(); const ws=m.querySelectorAll('.w');
      const k=Math.max(0,Math.min(1,(H*.85-r.top)/(r.height+H*.35))); const n=Math.round(k*ws.length*1.1);
      ws.forEach((w,i)=>w.classList.toggle('lit', i<n)); });
    D.querySelectorAll('video[autoplay]:not([data-agro])').forEach(v=>{ v.dataset.agro=1; v.muted=true; v.defaultMuted=true; v.playsInline=true;
      const go=()=>v.play().catch(()=>{}); if(v.readyState>=2) go(); else v.addEventListener('canplay',go,{once:true}); });
    if (!D.hidden) D.querySelectorAll('video[autoplay][data-agro]').forEach(v=>{ if (v.paused && v.readyState>=2) v.play().catch(()=>{}); }); }
  let q=false; D.addEventListener('scroll',()=>{ if(q) return; q=true; P.requestAnimationFrame(()=>{ q=false; scan(); }); },{capture:true,passive:true});
  P.setInterval(()=>{ P.__agronovaFX.beat = Date.now(); try { scan(); } catch (e) {} }, 350);
  P.__agronovaFX.refresh = scan;
  new P.MutationObserver(()=>{ clearTimeout(P.__agroT); P.__agroT=setTimeout(scan,50); }).observe(D.body,{childList:true,subtree:true});
  scan();
})();
"""

# The helper iframe only (1) hides itself and (2) injects FX_CORE into the page once. It holds no timers of its own.
FX_JS = """
<script>
(function(){
  try { const fe = window.frameElement; if (fe) fe.style.cssText = 'position:fixed;width:0;height:0;border:0;opacity:0;pointer-events:none'; } catch (e) {}
  const P = window.parent, D = P.document;
  if (P.__agronovaFX) { try { P.__agronovaFX.refresh && P.__agronovaFX.refresh(); } catch (e) {} return; }
  const s = D.createElement('script');
  s.id = 'agronova-fx-core';
  s.textContent = __CORE__;
  D.head.appendChild(s);
})();
</script>
""".replace("__CORE__", json.dumps(FX_CORE).replace("</", "<\\/"))


def inject() -> None:
    """Global styles + the persistent motion layer. Call once per run, before page content."""
    st.markdown(CSS, unsafe_allow_html=True)
    with st.container(key="fxloader", height=1, border=False):
        if hasattr(st, "iframe"):
            st.iframe(FX_JS, height=1)
        else:
            components.html(FX_JS, height=0)
    st.markdown("<style>.st-key-fxloader{position:absolute!important;width:0;height:0;overflow:hidden;opacity:0;pointer-events:none}</style>",
                unsafe_allow_html=True)


def hero() -> None:
    today = dt.date.today()
    st.html(f"""
<section class="hero">
  <img class="poster" src="{HERO_POSTER}" alt="Wheat field at sunrise" />
  <video autoplay muted loop playsinline preload="auto" poster="{HERO_POSTER}"><source src="{HERO_VIDEO}" type="video/mp4" /></video>
  <div class="shade"></div>
  <div class="meta"><span>AgroNova · Field Intelligence</span><span>20°00′N &nbsp; 73°47′E &nbsp; · &nbsp; Nashik</span><span>Vol. 01 — {today:%d %b %Y}</span></div>
  <div class="body">
    <h1><span class="mask"><span>Advice that</span></span><span class="mask"><span><em>reads the sky</em></span></span><span class="mask"><span>before it speaks.</span></span></h1>
    <div class="side">
      <p>AgroNova is a thinking farm assistant. It checks live weather, real soil maps and your pinned field, then answers in your
      language with clear steps and the reason behind each one.</p>
      <a class="cta" href="#ask">Ask AgroNova <span>↓</span></a>
    </div>
  </div>
  <div class="foot">
    <div><b>758</b><span>Districts mapped</span></div><div><b>37</b><span>Languages · all 22 Indian</span></div>
    <div><b>06</b><span>Expert modules</span></div><div><b>Live</b><span>Weather · soil · web search</span></div>
  </div>
</section>""")


def ticker(words: list[str]) -> None:
    items = "".join(f"<span>{_html.escape(w)}<i>✳</i></span>" for w in words * 2)
    st.html(f"<div class='ticker'><div class='t'>{items}</div></div>")


def page_header(num: str, kicker: str, title: str, dek: str, img: str, caption: str = "") -> None:
    """Editorial page opener: index + kicker, serif headline, dek, and a captioned photograph."""
    st.html(f"""<header class="phead reveal">
      <div><div class="kicker"><b>{num}</b><span>{kicker}</span></div>
        <h1 class="display">{title}</h1><p class="dek">{dek}</p></div>
      <figure class="tilt"><img src="{img}" alt=""/>{f'<figcaption>{caption}</figcaption>' if caption else ''}</figure>
    </header>""")


def section(num: str, kicker: str, title: str, dek: str = "") -> None:
    st.html(f"""<div class="reveal" style="margin:5rem 0 2rem"><div class="kicker"><b>{num}</b><span>{kicker}</span></div>
      <h2 class="h2">{title}</h2>{f'<p class="dek">{dek}</p>' if dek else ''}</div>""")


def manifesto(text: str, gold: set[str]) -> None:
    words = "".join(f"<span class='w{' g' if w.strip('.,').lower() in gold else ''}'>{_html.escape(w)}</span> " for w in text.split())
    st.html(f"<p class='manifesto'>{words}</p>")
