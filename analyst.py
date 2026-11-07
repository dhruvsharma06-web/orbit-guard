"""
analyst.py - turns a conjunction event into a mission-control briefing using the local
LLM (Ollama). If Ollama isn't running, it falls back to a rule-based briefing so the app
always works.
"""
import json
import os
import re
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/generate"
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b-q4_K_M")

PROMPT = """You are a spacecraft collision-avoidance analyst at mission control.
Write a short briefing (max 150 words) with exactly these headings:
SITUATION, RISK ASSESSMENT, RECOMMENDED ACTION, MANEUVER WINDOW.
Use only the numbers in the event data. Do not invent numbers or object details.
Event data:
{event}"""


def _event_view(e):
    keys = ["a_name", "a_id", "a_debris", "b_name", "b_id", "b_debris", "tca_utc",
            "miss_km", "rel_speed_kms", "risk_score", "risk_label", "probability"]
    return {k: e[k] for k in keys if k in e}


def rule_based_briefing(e):
    """Deterministic fallback when the LLM is unavailable."""
    action = {
        "CRITICAL": "Plan an avoidance maneuver now and confirm with fresh tracking data.",
        "HIGH": "Request updated tracking; prepare a contingency maneuver.",
        "MEDIUM": "Monitor; re-screen with the next orbit data update.",
        "LOW": "No action needed; routine monitoring.",
    }[e["risk_label"]]
    return (
        f"SITUATION\n{e['a_name']} ({e['a_id']}) and {e['b_name']} ({e['b_id']}) reach closest "
        f"approach at {e['tca_utc']}.\n\n"
        f"RISK ASSESSMENT\nMiss distance {e['miss_km']:.2f} km at {e['rel_speed_kms']:.2f} km/s relative "
        f"speed. Risk score {e['risk_score']}/100 ({e['risk_label']}), estimated probability "
        f"{e['probability']:.2e}.\n\n"
        f"RECOMMENDED ACTION\n{action}\n\n"
        f"MANEUVER WINDOW\nBest executed 1-2 orbits (about 1.5-3 hours) before {e['tca_utc']}, "
        f"when a small along-track burn shifts the arrival time most efficiently.\n\n"
        f"(Rule-based briefing: run locally with Ollama for an AI-written one.)"
    )


def generate_briefing(event):
    body = json.dumps({
        "model": MODEL, "stream": False,
        "prompt": PROMPT.format(event=json.dumps(_event_view(event), indent=1)),
        "options": {"temperature": 0.3},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, body, {"Content-Type": "application/json"})
    try:
        timeout = 180 if "localhost" in OLLAMA_URL else 25
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = json.loads(r.read()).get("response", "")
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return text or rule_based_briefing(event)
    except Exception:
        return rule_based_briefing(event)
