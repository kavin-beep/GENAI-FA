"""LLM engine with a Claude-style agent loop — Groq or xAI Grok, picked automatically from the key.

Both providers speak the OpenAI chat-completions protocol, so we use the `openai` SDK with their base URLs:
  * Groq      (keys start with `gsk_`) → https://api.groq.com/openai/v1   (gpt-oss, Qwen, Llama, Kimi + Whisper)
  * xAI Grok  (keys start with `xai-`) → https://api.x.ai/v1

What makes it behave like Claude:
  * streamed tokens, so the answer types out live
  * visible reasoning (reasoning models stream it) shown in a collapsible panel
  * autonomous multi-step tool use (weather / soil / crop calendar / geocoding)
  * multi-turn memory, voice-note transcription, image understanding where the model supports it
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from openai import OpenAI

from .tools import TOOL_SPECS, TOOLS, run_tool

PROVIDERS = {
    "groq": {"name": "Groq", "base_url": "https://api.groq.com/openai/v1", "console": "console.groq.com/keys",
             "preferred": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "moonshotai/kimi-k2-instruct-0905",
                           "llama-3.3-70b-versatile", "openai/gpt-oss-20b"],
             "skip": ("guard", "whisper", "orpheus", "tts", "playai", "distil", "compound")},
    "xai": {"name": "xAI Grok", "base_url": "https://api.x.ai/v1", "console": "console.x.ai",
            "preferred": ["grok-4-1-fast-reasoning", "grok-4-fast-reasoning", "grok-4", "grok-3-mini", "grok-3"],
            "skip": ("image", "imagine", "video", "embed", "tts", "audio")},
}
PREFERRED_MODELS = PROVIDERS["groq"]["preferred"] + PROVIDERS["xai"]["preferred"]
MAX_TOOL_ROUNDS = 5
WHISPER = "whisper-large-v3-turbo"
VISION_MODELS = ["qwen/qwen3.8-27b", "meta-llama/llama-4-maverick-17b-128e-instruct", "meta-llama/llama-4-scout-17b-16e-instruct"]
FAST_MODEL = "openai/gpt-oss-20b"
FALLBACK_CHAIN = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]   # separate rate budgets per model                      # quick side-tasks: follow-ups, grading
GUARD_MODEL = "meta-llama/llama-prompt-guard-2-86m"    # jailbreak / prompt-injection classifier
GUARD_THRESHOLD = 0.9
# Groq-hosted server-side tools for gpt-oss models: live web search + a Python sandbox
BUILTIN_TOOLS = [{"type": "browser_search"}, {"type": "code_interpreter"}]
REFUSAL = ("I can't follow that request: it looks like an attempt to override how I work. "
           "I'm glad to help with your farm, though. Ask me about crops, pests, weather, soil or market prices.")

# Friendly names for the model picker
MODEL_LABELS = {
    "openai/gpt-oss-120b": "AgroNova Pro — deep reasoning (gpt-oss-120b)",
    "openai/gpt-oss-20b": "AgroNova Swift — fastest (gpt-oss-20b)",
    "qwen/qwen3.8-27b": "AgroNova Vision — sees photos (Qwen 3.8)",
}


@dataclass
class Event:
    kind: str           # thought | text | tool_call | tool_result | sources | usage | error | done
    data: Any = None


@dataclass
class Settings:
    model: str = "openai/gpt-oss-120b"
    temperature: float = 0.6
    max_tokens: int = 1400
    thinking: bool = True
    tools: bool = True
    web: bool = True          # built-in web search + code interpreter (Groq gpt-oss)
    guard: bool = True        # prompt-injection screening
    extra: dict = field(default_factory=dict)


def builtin_ok(client, model: str) -> bool:
    return getattr(client, "_agro_provider", "") == "groq" and "gpt-oss" in model


def guard_score(client, text: str) -> float:
    """Probability (0–1) that the message is a jailbreak / prompt-injection attempt. 0 if unavailable."""
    if getattr(client, "_agro_provider", "") != "groq" or not text.strip():
        return 0.0
    try:
        r = client.chat.completions.create(model=GUARD_MODEL, messages=[{"role": "user", "content": text[:2000]}])
        return float((r.choices[0].message.content or "0").strip())
    except Exception:
        return 0.0


def suggest_followups(client, question: str, answer: str, language: str) -> list[str]:
    """Three short, natural next questions the farmer might ask (Claude-style suggestion chips)."""
    model = FAST_MODEL if getattr(client, "_agro_provider", "") == "groq" else None
    if not model:
        return []
    prompt = (f"A farmer asked: {question[:600]}\nThe assistant answered: {answer[:2500]}\n\n"
              f"Write 3 short follow-up questions (max 9 words each) the farmer would naturally ask next, in {language}. "
              'Reply with ONLY a JSON array of 3 strings.')
    try:
        r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}],
                                           temperature=0.5, max_tokens=500)
        txt = r.choices[0].message.content or "[]"
        a, b = txt.find("["), txt.rfind("]")
        out = json.loads(txt[a:b + 1])
        return [str(x).strip() for x in out if str(x).strip()][:3]
    except Exception:
        return []


def _builtin_events(t: dict) -> tuple[dict | None, list[dict]]:
    """Turn one completed Groq executed_tool into a UI step + any sources it surfaced."""
    typ, args = t.get("type", ""), t.get("arguments") or ""
    try:
        a = json.loads(args) if isinstance(args, str) and args.strip().startswith("{") else {}
    except json.JSONDecodeError:
        a = {}
    srcs = [{"title": r.get("title", ""), "url": r.get("url", "")}
            for r in ((t.get("search_results") or {}).get("results") or []) if r.get("url")]
    if typ == "browser_search":
        return {"name": "web_search", "label": "Searching the web", "args": {"query": a.get("query", "")}}, srcs[:6]
    if typ == "browser.open":
        url = srcs[0]["url"] if srcs else str(a.get("id", ""))
        host = url.split("/")[2] if url.startswith("http") else ""
        return ({"name": "web_open", "label": "Reading", "args": {"query": host}} if host else None), srcs[:1]
    if t.get("code_results") is not None or t.get("name") == "python" or typ == "code_interpreter":
        return {"name": "code", "label": "Running a calculation", "args": {}}, []
    return None, []


def provider_for(key: str) -> str:
    return "xai" if key.strip().startswith("xai-") else "groq"


def make_client(api_key: str) -> OpenAI:
    prov = provider_for(api_key)
    c = OpenAI(api_key=api_key.strip(), base_url=PROVIDERS[prov]["base_url"], timeout=120, max_retries=4)
    c._agro_provider = prov  # remembered for model ranking and voice transcription
    return c


def list_models(client: OpenAI) -> list[str]:
    cfg = PROVIDERS[getattr(client, "_agro_provider", "groq")]
    names = [m.id for m in client.models.list().data if not any(x in m.id.lower() for x in cfg["skip"])]
    ranked = [p for p in cfg["preferred"] if p in names]
    return ranked + sorted(set(names) - set(ranked), reverse=True)


def transcribe(client: OpenAI, audio: bytes, mime: str = "audio/wav") -> str:
    """Speech-to-text for voice notes (Groq Whisper). Returns '' if the provider has no speech-to-text."""
    if getattr(client, "_agro_provider", "") != "groq":
        return ""
    ext = "webm" if "webm" in mime else "mp3" if ("mpeg" in mime or "mp3" in mime) else "wav"
    r = client.audio.transcriptions.create(model=WHISPER, file=(f"voice.{ext}", audio, mime), response_format="verbose_json")
    text = (r if isinstance(r, str) else getattr(r, "text", "")) or ""
    lang = getattr(r, "language", None) or (getattr(r, "model_extra", None) or {}).get("language") or ""
    transcribe.last_language = str(lang).strip().title()   # Whisper's language detection, e.g. "Hindi", "Tamil"
    return text.strip()


def _tools() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["parameters"]}} for t in TOOL_SPECS]


def to_messages(system: str, history: list[dict], vision: bool = True) -> list[dict]:
    """Session chat history → OpenAI-style messages (text + images as data URLs + voice transcripts)."""
    msgs: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in history:
        if m["role"] != "user":
            if m.get("content"):
                msgs.append({"role": "assistant", "content": m["content"]})
            continue
        parts: list[dict] = []
        note = ""
        for att in m.get("attachments", []) or []:
            if att["mime"].startswith("image") and vision:
                b64 = base64.b64encode(att["data"]).decode()
                parts.append({"type": "image_url", "image_url": {"url": f"data:{att['mime']};base64,{b64}"}})
            elif att["mime"].startswith("image"):
                note += "\n\n[A photo was attached, but this model cannot see images. Ask the farmer to describe the symptoms.]"
            elif att["mime"].startswith("audio"):
                if att.get("transcript"):
                    spoken = att.get("lang") or "the language it was spoken in"
                    note += (f"\n\n[Voice note transcript (spoken in {spoken}): \"{att['transcript']}\". Answer in "
                             f"{spoken}, in that language's own script, unless a different reply language is set. "
                             f"Your answer will be read aloud, so keep sentences short and clear.]")
                else:
                    note += "\n\n[A voice note was attached but could not be transcribed. Politely ask the farmer to type it.]"
        parts.append({"type": "text", "text": (m.get("content") or "") + note})
        msgs.append({"role": "user", "content": parts if len(parts) > 1 else parts[0]["text"]})
    return msgs


def friendly_error(e: Exception) -> str:
    s = str(e)
    low = s.lower()
    code = getattr(e, "status_code", None)
    if code in (401, 403) or "invalid api key" in low or "incorrect api key" in low or "unauthorized" in low:
        return "🔑 The API key was rejected. Check it (console.groq.com/keys or console.x.ai), paste it again and save."
    if code == 429 or "rate limit" in low or "quota" in low or "credits" in low:
        return "⏳ Rate limit reached on the free tier. Wait a minute, or pick a smaller model in the sidebar."
    if code == 404 or ("model" in low and ("not found" in low or "does not exist" in low or "decommissioned" in low)):
        return "🧩 That model isn't available for this key. Pick another model in the sidebar."
    if code in (500, 502, 503) or "overloaded" in low:
        return "🌩️ The model is busy right now. Please retry in a few seconds."
    return f"⚠️ {type(e).__name__}: {s[:400]}"


def _extra(obj, name):
    v = getattr(obj, name, None)
    if v is None and getattr(obj, "model_extra", None):
        v = obj.model_extra.get(name)
    return v


def _reasoning(delta) -> str | None:
    """xAI streams `reasoning_content`; Groq (gpt-oss, Qwen) streams `reasoning`."""
    return _extra(delta, "reasoning_content") or _extra(delta, "reasoning")


def stream_agent(client: OpenAI, system: str, history: list[dict], s: Settings) -> Iterator[Event]:
    """Run the agent loop, yielding events for the UI to render live."""
    vision, use_tools, want_usage = True, s.tools, True
    usage = {"input": 0, "output": 0, "thoughts": 0, "tool_calls": 0}
    t0 = time.time()

    # Voice notes → text with Whisper, cached on the attachment so it runs once per note
    for m in history:
        for att in m.get("attachments", []) or []:
            if att["mime"].startswith("audio") and "transcript" not in att:
                yield Event("tool_call", {"name": "transcribe", "label": "Transcribing voice note", "args": {}})
                t1 = time.time()
                try:
                    transcribe.last_language = ""
                    att["transcript"] = transcribe(client, att["data"], att["mime"])
                    att["lang"] = getattr(transcribe, "last_language", "")
                except Exception:
                    att["transcript"] = ""
                yield Event("tool_result", {"name": "transcribe", "result": {"text": att["transcript"]},
                                            "ms": int((time.time() - t1) * 1000)})
    messages = to_messages(system, history, vision)

    # Safety screen: Llama Prompt Guard flags jailbreak / prompt-injection attempts before the model sees them
    if s.guard and history and history[-1]["role"] == "user":
        last = history[-1]
        said = " ".join([last.get("content") or ""] + [a.get("transcript", "") for a in last.get("attachments", []) or []])
        t1 = time.time()
        score = guard_score(client, said)
        if score >= GUARD_THRESHOLD:
            yield Event("tool_call", {"name": "guard", "label": "Safety check — blocked", "args": {}})
            yield Event("tool_result", {"name": "guard", "result": {"score": score}, "ms": int((time.time() - t1) * 1000)})
            yield Event("text", REFUSAL)
            usage["seconds"] = round(time.time() - t0, 2)
            yield Event("usage", usage)
            yield Event("done")
            return

    # Photo in the latest message + a text-only model → hand this turn to a vision model (Claude-style: just works)
    model = s.model
    last_atts = (history[-1].get("attachments") or []) if history else []
    if any(a["mime"].startswith("image") for a in last_atts) and getattr(client, "_agro_provider", "") == "groq" \
            and not any(v in model for v in ("qwen", "llama-4", "vision")):
        model = VISION_MODELS[0]
        yield Event("tool_call", {"name": "vision", "label": "Looking at your photo", "args": {"query": model}})
        yield Event("tool_result", {"name": "vision", "result": {"model": model}, "ms": 0})

    use_web = s.web and builtin_ok(client, model)
    seen_sources: set[str] = set()
    tried: set[str] = set()
    for _round in range(MAX_TOOL_ROUNDS + 1):
        calls: dict[int, dict] = {}
        text_buf = ""
        emitted = False
        try:
            kw: dict[str, Any] = dict(model=model, messages=messages, stream=True, temperature=s.temperature,
                                      max_tokens=s.max_tokens)
            if want_usage:
                kw["stream_options"] = {"include_usage": True}
            tools_list = (_tools() if use_tools else []) + (BUILTIN_TOOLS if use_web else [])
            if tools_list:
                kw["tools"] = tools_list
                kw["tool_choice"] = "auto"
            for chunk in client.chat.completions.create(**kw):
                u = chunk.usage
                xg = _extra(chunk, "x_groq") or {}
                if u is None and isinstance(xg, dict) and xg.get("usage"):
                    usage["input"] = xg["usage"].get("prompt_tokens") or usage["input"]
                    usage["output"] = xg["usage"].get("completion_tokens") or usage["output"]
                elif u is not None:
                    usage["input"] = u.prompt_tokens or usage["input"]
                    usage["output"] = u.completion_tokens or usage["output"]
                    det = getattr(u, "completion_tokens_details", None)
                    if det is not None:
                        usage["thoughts"] = getattr(det, "reasoning_tokens", 0) or usage["thoughts"]
                if not chunk.choices:
                    continue
                d = chunk.choices[0].delta
                r = _reasoning(d)
                if r and s.thinking:
                    yield Event("thought", r)
                for t in _extra(d, "executed_tools") or []:
                    if not isinstance(t, dict) or "output" not in t:   # each tool arrives twice; act on the finished one
                        continue
                    step, srcs = _builtin_events(t)
                    if step:
                        usage["tool_calls"] += 1
                        yield Event("tool_call", step)
                        yield Event("tool_result", {"name": step["name"], "result": {}, "ms": 0})
                    fresh = [x for x in srcs if x["url"] not in seen_sources]
                    seen_sources.update(x["url"] for x in fresh)
                    if fresh:
                        yield Event("sources", fresh)
                if d.content:
                    emitted = True
                    text_buf += d.content
                    yield Event("text", d.content)
                for tc in d.tool_calls or []:
                    c = calls.setdefault(tc.index if tc.index is not None else len(calls), {"id": "", "name": "", "args": ""})
                    if tc.id:
                        c["id"] = tc.id
                    if tc.function and tc.function.name:
                        c["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        c["args"] += tc.function.arguments
        except Exception as e:  # graceful downgrade for models without usage-streaming / vision / tools
            low = str(e).lower()
            if not emitted and want_usage and "stream_options" in low:
                want_usage = False
                continue
            rate_limited = getattr(e, "status_code", None) == 429 or "rate limit" in low
            if not emitted and use_web and rate_limited:
                use_web = False      # web search pages are token-heavy; retry the turn without them
                yield Event("tool_call", {"name": "fallback", "label": "Busy — answering without web search", "args": {}})
                yield Event("tool_result", {"name": "fallback", "result": {}, "ms": 0})
                time.sleep(2)
                continue
            if not emitted and rate_limited and getattr(client, "_agro_provider", "") == "groq":
                # Each Groq model has its own per-minute token budget → hand the turn to the next model in line
                chain = [m for m in FALLBACK_CHAIN if m != model and m not in tried]
                if chain:
                    tried.add(model)
                    model = chain[0]
                    use_web = use_web and builtin_ok(client, model)
                    yield Event("tool_call", {"name": "fallback", "label": "Busy — switching to " +
                                              MODEL_LABELS.get(model, model).split(" (")[0], "args": {}})
                    yield Event("tool_result", {"name": "fallback", "result": {"model": model}, "ms": 0})
                    usage["model"] = model
                    continue
            if not emitted and rate_limited and _round < 2:
                time.sleep(6 * (_round + 1))   # brief backoff, then try once more
                continue
            if not emitted and use_web and ("browser" in low or "code_interpreter" in low or "built-in" in low):
                use_web = False
                continue
            if not emitted and model != s.model and ("model" in low or getattr(e, "status_code", 0) == 404):
                model = s.model  # vision model not available for this key → fall back
                continue
            if not emitted and vision and ("image" in low or "vision" in low or "content must be a string" in low):
                vision = False
                messages = to_messages(system, history, vision)
                continue
            if not emitted and use_tools and ("tool" in low or "function" in low):
                use_tools = False
                continue
            yield Event("error", friendly_error(e))
            break

        if not calls:
            break
        ordered = [calls[i] for i in sorted(calls)]
        for i, c in enumerate(ordered):
            c["id"] = c["id"] or f"call_{_round}_{i}"
        messages.append({"role": "assistant", "content": text_buf or None, "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"}} for c in ordered]})
        for c in ordered:
            try:
                args = json.loads(c["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            usage["tool_calls"] += 1
            yield Event("tool_call", {"name": c["name"], "label": TOOLS.get(c["name"], {}).get("label", c["name"]), "args": args})
            t1 = time.time()
            result = run_tool(c["name"], args)
            yield Event("tool_result", {"name": c["name"], "result": result, "ms": int((time.time() - t1) * 1000)})
            if c["name"] == "find_reference_images" and isinstance(result, dict) and result.get("images"):
                yield Event("images", result["images"])
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, default=str)[:12000]})
    usage["seconds"] = round(time.time() - t0, 2)
    yield Event("usage", usage)
    yield Event("done")


def complete(client: OpenAI, prompt: str, s: Settings, system: str | None = None) -> str:
    """One-shot, non-streaming call (used by the validation judge)."""
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    r = client.chat.completions.create(model=s.model, messages=msgs, temperature=s.temperature, max_tokens=s.max_tokens)
    return r.choices[0].message.content or ""


def run_to_text(client: OpenAI, system: str, prompt: str, s: Settings) -> tuple[str, dict]:
    """Run the full agent (tools included) and collect the final text."""
    text, usage, tools_used = [], {}, []
    for ev in stream_agent(client, system, [{"role": "user", "content": prompt}], s):
        if ev.kind == "text":
            text.append(ev.data)
        elif ev.kind == "tool_call":
            tools_used.append(ev.data["name"])
        elif ev.kind == "usage":
            usage = ev.data
        elif ev.kind == "error":
            text.append(f"\n\n{ev.data}")
    usage["tools"] = tools_used
    return "".join(text), usage


def parse_json(s: str) -> dict:
    s = s.strip().strip("`")
    if s.lower().startswith("json"):
        s = s[4:]
    a, b = s.find("{"), s.rfind("}")
    try:
        return json.loads(s[a:b + 1])
    except Exception:
        return {}
