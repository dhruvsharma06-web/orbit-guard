"""
conjunction.py - find close approaches ("conjunctions") between objects.

Why not check every pair at every timestep?  With n objects that is n^2/2 pairs:
1,500 objects -> ~1.1 million pairs x 2,880 timesteps = 3 billion distance checks.

Instead, at each timestep we build a spatial index (a k-d tree, the tree version of a
3D grid) and only ask it for pairs that are already close.  That is about O(n log n)
per step, so a full day runs in seconds.

Objects in orbit move ~7.5 km/s, so relative speeds reach 15 km/s.  Between two
30-second samples a pair can close ~450 km, so we screen with a generous radius
(threshold + v_rel_max * dt / 2) and then find the exact time of closest approach
(TCA) assuming straight-line relative motion inside that window.
"""
import math
import time

import numpy as np
from scipy.spatial import cKDTree

V_REL_MAX = 15.5  # km/s, maximum relative speed in LEO (head-on)


def risk_score(miss_km, rel_speed_kms, a_is_debris, b_is_debris):
    """0-100 score and a label. Closer, faster and debris-involved = worse."""
    score = 100.0 * math.exp(-miss_km / 2.0) * (1.0 + rel_speed_kms / 30.0)
    if a_is_debris or b_is_debris:
        score *= 1.2
    score = round(min(score, 100.0), 1)
    if miss_km < 1:
        label = "CRITICAL"
    elif miss_km < 2:
        label = "HIGH"
    elif miss_km < 5:
        label = "MEDIUM"
    else:
        label = "LOW"
    return score, label


def collision_probability(miss_km, combined_radius_m=10.0, sigma_km=1.0):
    """
    Simplified 2D Gaussian collision probability (EDUCATIONAL, not operational).
    Real operators use full covariance matrices from tracking data.
    P ~ (r^2 / (2 sigma^2)) * exp(-d^2 / (2 sigma^2))
    """
    r = combined_radius_m / 1000.0
    return (r * r / (2 * sigma_km ** 2)) * math.exp(-miss_km ** 2 / (2 * sigma_km ** 2))


def find_conjunctions(positions, velocities, times, objects, step_s=30,
                      threshold_km=10.0, min_rel_speed=0.05):
    """
    positions/velocities: arrays [n_obj, n_time, 3] (km, km/s).
    Returns events sorted by risk_score (highest first).
    Pairs with tiny relative speed (formation flying / docked) are ignored.
    """
    n_obj, n_t, _ = positions.shape
    screen = threshold_km + V_REL_MAX * step_s / 2.0
    half = step_s / 2.0
    best = {}  # (i, j) -> event dict with the smallest miss distance

    for k in range(n_t):
        pts = positions[:, k, :]
        pairs = cKDTree(pts).query_pairs(screen, output_type="ndarray")
        if len(pairs) == 0:
            continue
        a, b = pairs[:, 0], pairs[:, 1]
        dr = pts[b] - pts[a]
        dv = velocities[b, k] - velocities[a, k]
        dv2 = np.einsum("ij,ij->i", dv, dv)
        # time of closest approach for straight-line relative motion, inside +/- dt/2
        t_star = np.where(dv2 > 1e-12, -np.einsum("ij,ij->i", dr, dv) / np.maximum(dv2, 1e-12), 0.0)
        t_star = np.clip(t_star, -half, half)
        miss = np.linalg.norm(dr + dv * t_star[:, None], axis=1)
        speed = np.sqrt(dv2)
        hit = (miss < threshold_km) & (speed > min_rel_speed)
        for i, j, m, s, ts in zip(a[hit], b[hit], miss[hit], speed[hit], t_star[hit]):
            key = (int(i), int(j))
            if key not in best or m < best[key]["miss_km"]:
                best[key] = {"a_idx": key[0], "b_idx": key[1], "k": k,
                             "miss_km": float(m), "rel_speed_kms": float(s), "t_offset_s": float(ts)}

    events = []
    for ev in best.values():
        oa, ob = objects[ev["a_idx"]], objects[ev["b_idx"]]
        tca = times[ev["k"]].timestamp() + ev["t_offset_s"]
        score, label = risk_score(ev["miss_km"], ev["rel_speed_kms"], oa["is_debris"], ob["is_debris"])
        events.append({
            **ev,
            "a_name": oa["name"], "b_name": ob["name"],
            "a_id": oa["norad_id"], "b_id": ob["norad_id"],
            "a_debris": oa["is_debris"], "b_debris": ob["is_debris"],
            "tca_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tca)),
            "tca_minute": round(ev["k"] * step_s / 60 + ev["t_offset_s"] / 60, 2),
            "risk_score": score, "risk_label": label,
            "probability": collision_probability(ev["miss_km"]),
        })
    events.sort(key=lambda e: (-e["risk_score"], e["miss_km"]))
    return events


if __name__ == "__main__":
    from datetime import datetime, timezone
    from orbits import load_tles, propagate_all

    t0 = time.time()
    objs = load_tles()
    pri = [o for o in objs if "ISS" in o["name"] or o["is_debris"]]
    rest = [o for o in objs if o not in pri]
    chosen = (pri + rest)[:400]
    valid, pos, vel, times, _ = propagate_all(chosen, datetime.now(timezone.utc), minutes=360, step_s=30)
    t1 = time.time()
    events = find_conjunctions(pos, vel, times, valid, step_s=30, threshold_km=20)
    t2 = time.time()
    print(f"{len(valid)} objects | propagate {t1 - t0:.1f}s | screen {t2 - t1:.1f}s | {len(events)} events")
    print(f"{'A':28} {'B':28} {'TCA (UTC)':22} {'miss km':>8} {'v km/s':>7} {'risk':>6}  label")
    for e in events[:10]:
        print(f"{e['a_name'][:27]:28} {e['b_name'][:27]:28} {e['tca_utc']:22} "
              f"{e['miss_km']:8.2f} {e['rel_speed_kms']:7.2f} {e['risk_score']:6.1f}  {e['risk_label']}")
