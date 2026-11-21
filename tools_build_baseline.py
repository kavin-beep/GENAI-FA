"""Generate data/baseline.json: a real, saved run of AgroNova's AI so pages have genuine results before anyone clicks.

Run:  python tools_build_baseline.py      (needs GROQ_API_KEY in .streamlit/secrets.toml or the environment)
Everything in the file is actual model output; the app labels it as a saved baseline run with its date and model.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from agronova import llm, prompts  # noqa: E402

key = os.environ.get("GROQ_API_KEY", "")
sec = ROOT / ".streamlit" / "secrets.toml"
if not key and sec.exists():
    key = tomllib.load(open(sec, "rb")).get("GROQ_API_KEY", "")
client = llm.make_client(key)
MAIN, JUDGE = "openai/gpt-oss-120b", llm.FAST_MODEL
S = llm.Settings(model=MAIN, temperature=0.6, max_tokens=1800)
J = llm.Settings(model=JUDGE, temperature=0.0, max_tokens=800, tools=False, web=False)
SYS = prompts.SYSTEM_PROMPT + "\n\n" + prompts.farm_context({}, "English")
CITE = re.compile(r"【[^】]*】")


def judge(q: str, a: str) -> dict:
    for _ in range(2):
        out = llm.parse_json(llm.complete(client, prompts.JUDGE_PROMPT.format(q=q, a=a[:6000]), J))
        if out:
            return out
    return {}


def run_case(case: dict) -> dict:
    ans, u = llm.run_to_text(client, SYS, case["prompt"], S)
    ans = CITE.sub("", ans)
    hits = [k for k in case["expect"] if k.lower() in ans.lower()]
    words = re.findall(r"\w+", ans)
    j = judge(case["prompt"], ans)
    print("  ✓", case["region"], flush=True)
    return {"region": case["region"], "prompt": case["prompt"], "answer": ans,
            "keyword_match_%": round(100 * len(hits) / len(case["expect"])), "matched": ", ".join(hits),
            "words/sentence": round(len(words) / max(1, len(re.findall(r"[.!?\n]+", ans))), 1),
            "tools": ", ".join(u.get("tools", [])), "latency_s": u.get("seconds"),
            "region_score": j.get("region"), "reasoning": j.get("reasoning"), "simple": j.get("simple"),
            "balanced": j.get("balanced"), "safe": j.get("safe"),
            "hallucination_risk": j.get("hallucination_risk"), "fix": j.get("fix")}


def run_module(key_: str) -> tuple[str, dict]:
    f = prompts.FEATURES[key_]
    q = f["samples"][0]
    ans, u = llm.run_to_text(client, SYS, q, S)
    print("  ✓ module", key_, flush=True)
    return key_, {"prompt": q, "answer": CITE.sub("", ans), "tools": u.get("tools", []), "seconds": u.get("seconds")}


def run_ab(q: str) -> dict:
    a_cfg = llm.Settings(model=MAIN, temperature=1.2, max_tokens=1800, thinking=False, tools=False, web=False)
    a_txt, a_u = llm.run_to_text(client, "", q, a_cfg)
    b_txt, b_u = llm.run_to_text(client, SYS, q, S)
    a_txt, b_txt = CITE.sub("", a_txt), CITE.sub("", b_txt)
    print("  ✓ A/B", flush=True)
    return {"q": q, "a": [a_txt, a_u, judge(q, a_txt)], "b": [b_txt, b_u, judge(q, b_txt)]}


def bad(text: str) -> bool:
    """An answer that is really an error/rate-limit message, or suspiciously short."""
    t = (text or "").strip()
    return len(t) < 300 or t.startswith(("⏳", "⚠️", "🔑", "🧩", "🌩️"))


def retry(fn, check, tries: int = 4, wait: int = 25):
    for i in range(tries):
        out = fn()
        if not check(out):
            return out
        print(f"    rate-limited / bad answer, waiting {wait * (i + 1)} s…", flush=True)
        time.sleep(wait * (i + 1))
    return out


if __name__ == "__main__":
    import time
    path = ROOT / "data" / "baseline.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    # Sequential on purpose: the Groq free tier has a per-minute token budget.
    print("validation suite…", flush=True)
    prev_v = {r["prompt"]: r for r in old.get("validation", [])}
    validation = []
    for case in prompts.VALIDATION_SUITE:
        r = prev_v.get(case["prompt"])
        if not r or bad(r["answer"]) or not r.get("region_score") or r.get("region_score") == 1:
            r = retry(lambda: run_case(case), lambda x: bad(x["answer"]))
            time.sleep(10)
        validation.append(r)
    print("modules…", flush=True)
    modules = {}
    for k in prompts.FEATURES:
        m = (old.get("modules") or {}).get(k)
        if not m or bad(m["answer"]):
            m = retry(lambda: run_module(k)[1], lambda x: bad(x["answer"]))
            time.sleep(10)
        modules[k] = m
    print("A/B…", flush=True)
    ab = old.get("ab")
    if not ab or bad(ab["b"][0]) or not ab["b"][2]:
        ab = retry(lambda: run_ab("What to grow in Rajasthan in August?"), lambda x: bad(x["b"][0]))
    out = {"generated": dt.date.today().isoformat(), "model": MAIN, "judge_model": JUDGE,
           "validation": validation, "modules": modules, "ab": ab}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved data/baseline.json")
