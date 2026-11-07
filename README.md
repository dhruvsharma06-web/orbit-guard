# 🛰️ OrbitGuard: Space Debris Collision Predictor

OrbitGuard loads **real orbit data for thousands of satellites and debris pieces**, predicts where each one will be for the next 24 hours, finds **close approaches (possible collisions)**, and shows them on an interactive 3D globe. A local AI (Ollama) writes mission-control briefings, and a maneuver simulator shows how a small thruster burn changes the risk. Runs locally (fully offline with Ollama) or on Vercel.

## Run locally
```
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 and click **RUN ANALYSIS**.
- Orbit data: uses the TLE files in `data/` (refreshed daily by a GitHub Action). If `data/` is empty, it downloads them from CelesTrak automatically.
- AI briefings use a local Ollama (`qwen3.5:4b`). Without Ollama, a rule-based briefing is shown. Point it elsewhere with the `OLLAMA_URL` / `OLLAMA_MODEL` environment variables.
- Test everything: `python tests/smoke_test.py`

## Deploy on Vercel
Import this repo at vercel.com/new and click Deploy; no settings are needed. Vercel detects the Flask `app` in `app.py`, serves `public/` from its CDN, and `vercel.json` gives the function 60 s / 2 GB.
The API is stateless (see `CONTRACT.md`), so it works on serverless functions. On Vercel, briefings use the rule-based fallback unless `OLLAMA_URL` points at a reachable Ollama server.

## What it does
| Feature | How |
|---|---|
| Orbit propagation | SGP4 (the official NORAD model), vectorised; 1,500 objects × 24 h at 30 s steps in about 1-2 s |
| Collision screening | k-d tree spatial index per timestep (no O(n²) all-pairs check) + exact time of closest approach by straight-line relative motion. Verified against brute force at 1 s resolution. |
| Risk | Miss distance, relative speed, debris involvement → score 0-100 + CRITICAL/HIGH/MEDIUM/LOW; simplified collision probability |
| Live data | GitHub Action pulls fresh CelesTrak TLEs every day → Vercel redeploys |
| 3D globe | three.js: Earth texture, satellites (cyan) + debris (orange), orbit tracks, pulsing closest-approach marker, time slider and playback, hover names |
| AI analyst | Local qwen3.5:4b writes a SITUATION / RISK / ACTION / WINDOW briefing |
| Maneuver simulator | Along-track Δv burn approximation → new miss distance and risk |
| Stats | Miss-distance histogram, events per hour, debris by altitude band |

## Stack
Python 3 · Flask · numpy · scipy · sgp4 · three.js · Chart.js · Ollama (qwen3.5:4b). Runs locally or on Vercel.

## Honest limits
- TLE accuracy is about 1 km, so real operators use precise ephemerides and covariance. The probability here is a simplified educational model.
- The maneuver model is a first-order along-track approximation.

## Files
`orbits.py` TLE loading/download + SGP4 · `conjunction.py` screening + risk · `analyst.py` AI briefing · `app.py` API · `templates/` + `public/static/` frontend · `.github/workflows/update-tle.yml` daily data refresh · `tests/smoke_test.py` · `PROJECT.md` · `CONTRACT.md` · `DEMO.md`
