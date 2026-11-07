"""
app.py - OrbitGuard web server (stateless: works locally and on Vercel).

Run locally:  python app.py   then open http://127.0.0.1:5000
Every request carries what it needs (limit, start time, event), so no server memory or
database is required between requests.
"""
import math
import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from flask import Flask, jsonify, render_template, request
from sgp4.api import Satrec, SatrecArray

from analyst import generate_briefing
from conjunction import find_conjunctions, risk_score
from orbits import julian_dates, load_catalog, propagate_all, select_objects, teme_to_geo

BASE = os.path.dirname(os.path.abspath(__file__))
STEP_S = 30  # propagation step for screening (seconds)
MAX_EVENTS = 400

# On Vercel the CDN serves public/**; locally Flask serves the same folder.
app = Flask(__name__, static_folder=os.path.join(BASE, "public", "static"), static_url_path="/static")


def bad(msg, code=400):
    return jsonify({"error": msg}), code


def arg_float(name, default, lo, hi, src=None):
    src = request.args if src is None else src
    try:
        return max(lo, min(hi, float(src.get(name, default))))
    except (TypeError, ValueError):
        return default


def parse_time(s):
    try:
        s = str(s).strip().replace(" ", "+")  # "+" in a URL query arrives as a space
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


_SATS = {}  # limit -> (objects, SatrecArray); cached per server instance


def selection(limit):
    cat = load_catalog()
    key = (int(limit), len(cat), cat[0]["line1"] if cat else "")
    if key not in _SATS:
        objs = select_objects(cat, int(limit))
        _SATS.clear()
        _SATS[key] = (objs, SatrecArray([Satrec.twoline2rv(o["line1"], o["line2"]) for o in objs]) if objs else None)
    return _SATS[key]


def by_norad(norad):
    return next((o for o in load_catalog() if o["norad_id"] == norad), None)


def propagate_window(objs, start, seconds, step):
    valid, pos, vel, times, jd = propagate_all(objs, start, minutes=seconds / 60, step_s=step)
    return valid, pos, vel, times, jd


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.svg")


@app.post("/api/run")
def run():
    limit = int(arg_float("limit", 1500, 50, 3000))
    hours = arg_float("hours", 24, 1, 48)
    threshold = arg_float("threshold", 10, 1, 50)
    t0 = time.time()
    objs, _ = selection(limit)
    if not objs:
        return bad("No orbit data available (data/ is empty and CelesTrak could not be reached).", 503)
    start = datetime.now(timezone.utc).replace(microsecond=0)
    valid, pos, vel, times, _ = propagate_all(objs, start, minutes=hours * 60, step_s=STEP_S)
    t1 = time.time()
    events = find_conjunctions(pos, vel, times, valid, step_s=STEP_S, threshold_km=threshold)
    t2 = time.time()
    for n, e in enumerate(events, 1):
        e["id"] = n
        for k in ("a_idx", "b_idx", "k", "t_offset_s"):
            e.pop(k, None)
    return jsonify({
        "summary": {
            "objects": len(valid), "debris": sum(o["is_debris"] for o in valid),
            "dropped": len(objs) - len(valid), "events": len(events), "hours": hours,
            "threshold_km": threshold, "limit": limit, "start_utc": start.isoformat(),
            "seconds": {"propagate": round(t1 - t0, 2), "screen": round(t2 - t1, 2)},
        },
        "events": events[:MAX_EVENTS],
    })


@app.get("/api/positions")
def positions():
    limit = int(arg_float("limit", 1500, 50, 3000))
    start = parse_time(request.args.get("start", ""))
    if not start:
        return bad("start (ISO time of the run) is required")
    when = start + timedelta(minutes=arg_float("t", 0, 0, 48 * 60))
    objs, sats = selection(limit)
    if not objs:
        return bad("No orbit data available", 503)
    jd, fr = julian_dates(when, 1, 1)
    e, r, _ = sats.sgp4(jd, fr)
    ok = (e[:, 0] == 0) & np.isfinite(r[:, 0]).all(axis=1)
    lat, lon, alt = teme_to_geo(r[ok, 0, :], jd[0] + fr[0])
    keep = [o for o, g in zip(objs, ok) if g]
    return jsonify({
        "time_utc": when.isoformat(), "ids": [o["norad_id"] for o in keep], "names": [o["name"] for o in keep],
        "debris": [int(o["is_debris"]) for o in keep],
        "lat": np.round(lat, 3).tolist(), "lon": np.round(lon, 3).tolist(), "alt": np.round(alt, 1).tolist(),
    })


@app.get("/api/track/<int:norad>")
def track(norad):
    """Ground-fixed orbit path, 50 minutes either side of time `at`."""
    obj = by_norad(norad)
    at = parse_time(request.args.get("at", ""))
    if not obj:
        return bad("unknown object", 404)
    if not at:
        return bad("at (ISO time) is required")
    valid, pos, _, _, jd = propagate_window([obj], at - timedelta(minutes=50), 101 * 60, 60)
    if not valid:
        return bad("orbit could not be propagated (decayed TLE?)", 422)
    lat, lon, alt = teme_to_geo(pos[0], jd)
    return jsonify({"lat": lat.round(3).tolist(), "lon": lon.round(3).tolist(), "alt": alt.round(1).tolist(), "center": 50})


@app.post("/api/brief")
def brief():
    ev = (request.get_json(silent=True) or {}).get("event")
    need = ("a_name", "a_id", "b_name", "b_id", "tca_utc", "miss_km", "rel_speed_kms", "risk_score", "risk_label", "probability")
    if not isinstance(ev, dict) or any(k not in ev for k in need):
        return bad("event with the fields from /api/run is required")
    return jsonify({"briefing": generate_briefing(ev)})


def closest(ra, va, rb, vb, half=0.5):
    """Smallest miss distance: straight-line relative motion solved inside each 1 s sample."""
    dr, dv = (rb - ra).astype(np.float64), (vb - va).astype(np.float64)
    dv2 = np.maximum(np.einsum("ij,ij->i", dv, dv), 1e-12)
    t = np.clip(-np.einsum("ij,ij->i", dr, dv) / dv2, -half, half)
    return float(np.linalg.norm(dr + dv * t[:, None], axis=1).min())


@app.post("/api/maneuver")
def maneuver():
    """
    Along-track burn approximation (Clohessy-Wiltshire style): a small along-track delta-v
    made dt seconds before TCA shifts the object along its track by ~3*dv*dt at TCA.
    Both orbits are re-propagated at 1-second resolution around TCA. Educational only.
    """
    d = request.get_json(silent=True) or {}
    ev = d.get("event") or {}
    tca = parse_time(ev.get("tca_utc", ""))
    a, b = by_norad(int(ev.get("a_id", -1))), by_norad(int(ev.get("b_id", -1)))
    if not (tca and a and b):
        return bad("event not found in the current catalogue", 404)
    dv_ms = arg_float("delta_v_ms", 0.1, 0.001, 5.0, d)
    lead_h = arg_float("lead_hours", 2, 0.1, 24, d)
    me, other = (a, b) if d.get("which", "a") == "a" else (b, a)
    valid, pos, vel, _, _ = propagate_window([me, other], tca - timedelta(seconds=90), 181, 1)
    if len(valid) < 2:
        return bad("orbit could not be propagated", 422)
    shift_km = 3 * (dv_ms / 1000.0) * lead_h * 3600
    u = vel[0] / np.linalg.norm(vel[0], axis=1, keepdims=True)
    old = closest(pos[0], vel[0], pos[1], vel[1])
    new = closest(pos[0] + u * shift_km, vel[0], pos[1], vel[1])
    new_score, new_label = risk_score(new, float(ev["rel_speed_kms"]), a["is_debris"], b["is_debris"])
    return jsonify({
        "shift_km": round(shift_km, 2), "old_miss_km": round(old, 3), "new_miss_km": round(new, 3),
        "old_risk": [ev.get("risk_score"), ev.get("risk_label")], "new_risk": [new_score, new_label],
    })


@app.post("/api/stats")
def stats():
    d = request.get_json(silent=True) or {}
    events = d.get("events") or []
    hours = int(math.ceil(arg_float("hours", 24, 1, 48, d)))
    limit = int(arg_float("limit", 1500, 50, 3000, d))
    miss_bins, per_hour = [0] * 10, [0] * hours
    for e in events:
        try:
            miss_bins[min(9, int(float(e["miss_km"])))] += 1
            per_hour[min(hours - 1, int(float(e["tca_minute"]) // 60))] += 1
        except (KeyError, TypeError, ValueError):
            continue
    objs, sats = selection(limit)
    start = parse_time(d.get("start_utc", "")) or datetime.now(timezone.utc)
    jd, fr = julian_dates(start, 1, 1)
    e, r, _ = sats.sgp4(jd, fr)
    ok = e[:, 0] == 0
    _, _, alt = teme_to_geo(r[ok, 0, :], jd[0] + fr[0])
    edges = list(range(200, 2001, 200))
    active, debris = [0] * (len(edges) - 1), [0] * (len(edges) - 1)
    for a_km, o in zip(alt, [o for o, g in zip(objs, ok) if g]):
        bnd = int((a_km - 200) // 200)
        if 0 <= bnd < len(active):
            (debris if o["is_debris"] else active)[bnd] += 1
    return jsonify({
        "miss_labels": [f"{i}-{i + 1}" for i in range(10)], "miss_bins": miss_bins,
        "hour_labels": list(range(hours)), "per_hour": per_hour,
        "alt_labels": [f"{edges[i]}-{edges[i + 1]}" for i in range(len(edges) - 1)],
        "alt_active": active, "alt_debris": debris,
    })


if __name__ == "__main__":
    print("OrbitGuard running at http://127.0.0.1:5000")
    app.run(debug=True, use_reloader=False)
