# PROJECT: OrbitGuard
Value: predict and explain space-debris collision risks for any tracked satellite, offline, in seconds.
Primary journey: 1. Run analysis → 2. pick the top-risk event → 3. see both orbits meet on the globe + an AI briefing + test a dodge maneuver.
Wow moment: the camera flies to a pulsing red closest-approach point where two orbit lines cross, then the "simulate burn" turns CRITICAL into LOW.
Mode: solo, offline (playbook v4.0, Solo library E7).

## Features
| ID | Feature | P | Status | Acceptance check |
|---|---|---|---|---|
| F1 | Load real TLEs (stations, active, 3 debris clouds) | P0 | ✅ | `python orbits.py` prints counts + ISS at 400-430 km |
| F2 | Vectorised SGP4 propagation | P0 | ✅ | 1,500 objects × 24 h in < 5 s |
| F3 | Conjunction screening (k-d tree + TCA) | P0 | ✅ | matches 1 s brute force to 0.001 km |
| F4 | Risk score + probability | P0 | ✅ | labels by miss distance |
| F5 | 3D globe + event list + tracks | P0 | ✅ | click event → tracks + marker within 2 s |
| F6 | AI briefing (Ollama) with fallback | P0 | ✅ | always returns 4 headed sections |
| F7 | Time slider + playback | P1 | ✅ | |
| F8 | Maneuver simulator | P1 | ✅ | |
| F9 | Stats dashboard | P1 | ✅ | |
| F10 | Kessler cascade mode | P2 | ⏳ next | |

## Architecture
Browser (three.js, Chart.js; keeps run state) ⇄ stateless Flask `app.py` (Vercel function) ⇄ `orbits.py` (TLEs from data/ or CelesTrak, SGP4) → `conjunction.py` (k-d tree, TCA, risk); `analyst.py` → Ollama (optional).
DB: none (stateless so it runs on serverless). GitHub Action refreshes data/ daily.

## Status
Works for real: everything in F1-F9 · Mocked: nothing (AI falls back to rules when Ollama is off) · Smoke test: 11/11 pass.
Known limits: TLE accuracy is about 1 km; the probability model is simplified; the maneuver model is a first-order approximation.

## Decisions
- D1: k-d tree instead of a hand-written grid: same idea (spatial index), faster and fewer bugs.
- D2: 30 s steps + screening radius `threshold + 15.5 km/s × 15 s`, then analytic TCA inside the window. This catches fast head-on passes that 1-minute sampling would miss.
- D3: Ignore pairs with relative speed < 0.05 km/s (docked or formation-flying objects).
- D4: AI is optional at runtime (rule-based fallback), so the demo never breaks.

## Cut list (if time is short)
1. F10 Kessler mode 2. stats modal 3. playback (keep slider)
