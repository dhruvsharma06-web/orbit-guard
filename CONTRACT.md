# CONTRACT v2.0: OrbitGuard API (stateless)
All responses are JSON. Errors: `{"error": "message"}` with 400 (bad input), 404 (unknown object), 422 (orbit can't be propagated), 503 (no orbit data).
The server keeps no state between requests: the browser keeps the run summary + events and sends back what each call needs. This is what makes it run on Vercel serverless functions.

| Method | Path | Input | Output |
|---|---|---|---|
| POST | `/api/run?limit=1500&hours=24&threshold=10` | query (clamped: limit 50-3000, hours 1-48, threshold 1-50 km) | `{summary:{objects, debris, dropped, events, hours, threshold_km, limit, start_utc, seconds:{propagate, screen}}, events:[Event] (top 400)}` |
| GET | `/api/positions?limit=&start=<start_utc>&t=<minute>` | from summary | `{time_utc, ids[], names[], debris[], lat[], lon[], alt[]}` |
| GET | `/api/track/<norad_id>?at=<ISO time>` | | `{lat[], lon[], alt[], center}`: ±50 min at 1-min steps, `center`=50 |
| POST | `/api/brief` | `{event: Event}` | `{briefing}` |
| POST | `/api/maneuver` | `{event: Event, which:"a"|"b", delta_v_ms, lead_hours}` | `{shift_km, old_miss_km, new_miss_km, old_risk:[score,label], new_risk:[score,label]}` |
| POST | `/api/stats` | `{events, hours, limit, start_utc}` | `{miss_labels, miss_bins, hour_labels, per_hour, alt_labels, alt_active, alt_debris}` |

**Event** = `{id, a_id, b_id, a_name, b_name, a_debris, b_debris, tca_utc, tca_minute, miss_km, rel_speed_kms, risk_score, risk_label, probability}`
Risk labels: CRITICAL < 1 km · HIGH < 2 km · MEDIUM < 5 km · LOW otherwise.

## Changelog
v2.0 stateless API for Vercel (no SQLite / server memory); objects referenced by NORAD id; maneuver re-propagates at 1 s with exact TCA solve.
v1.0 initial (local, SQLite)
