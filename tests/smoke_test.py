"""End-to-end smoke test: python tests/smoke_test.py  (needs TLE files in data/ or internet)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

c = app.app.test_client()
checks = []


def check(name, ok):
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name)


r = c.post("/api/run?limit=300&hours=6")
res = r.get_json()
check("run analysis", r.status_code == 200 and res["summary"]["objects"] > 0)
s, ev = res["summary"], res["events"]
check("events list", isinstance(ev, list))
p = c.get(f"/api/positions?limit={s['limit']}&start={s['start_utc']}&t=30").get_json()
check("positions", len(p["ids"]) == s["objects"])
iss = [a for n, a in zip(p["names"], p["alt"]) if "ISS (ZARYA)" in n]
check("ISS altitude plausible", all(300 < a < 500 for a in iss))
check("positions needs start", c.get("/api/positions").status_code == 400)
if ev:
    e = ev[0]
    t = c.get(f"/api/track/{e['a_id']}?at={e['tca_utc']}").get_json()
    check("track", len(t["lat"]) > 10)
    b = c.post("/api/brief", json={"event": e}).get_json()
    check("briefing", "SITUATION" in b["briefing"].upper())
    m = c.post("/api/maneuver", json={"event": e, "delta_v_ms": 0.2}).get_json()
    check("maneuver re-propagation matches screening", abs(m["old_miss_km"] - e["miss_km"]) < 0.01)
check("bad brief -> 400", c.post("/api/brief", json={}).status_code == 400)
check("unknown track -> 404", c.get("/api/track/1?at=2026-01-01T00:00:00Z").status_code == 404)
st = c.post("/api/stats", json={"events": ev, "hours": 6, "limit": s["limit"], "start_utc": s["start_utc"]})
check("stats", st.status_code == 200)
check("frontend", c.get("/").status_code == 200 and c.get("/static/app.js").status_code == 200)
print(f"\n{sum(ok for _, ok in checks)}/{len(checks)} passed")
sys.exit(0 if all(ok for _, ok in checks) else 1)
