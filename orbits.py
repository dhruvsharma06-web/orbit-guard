"""
orbits.py - load TLE files and propagate orbits with SGP4.

TLE = "two-line element set", the standard text format for satellite orbits:
    NAME
    1 25544U 98067A   ...   (line 1: id, epoch, drag terms)
    2 25544  51.6439 ...    (line 2: inclination, RAAN, eccentricity, ...)
SGP4 is the official model for turning a TLE into a position/velocity at any time.
Positions come out in the TEME frame (Earth-centred, inertial-ish), in km and km/s.
"""
import glob
import os
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4.api import Satrec, SatrecArray, jday

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
R_EARTH = 6371.0  # km, spherical Earth is fine for visualisation

# CelesTrak groups used when data/ has no TLE files (e.g. a fresh Vercel deploy)
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?GROUP={}&FORMAT=tle"
GROUPS = {"stations": "stations", "active": "active", "cosmos-2251-debris": "cosmos-2251-debris",
          "iridium-33-debris": "iridium-33-debris", "fengyun-1c-debris": "1999-025"}
CACHE_DIR = os.path.join(tempfile.gettempdir(), "orbitguard-tle")
CACHE_HOURS = 6


def tle_folder():
    """data/ if it holds TLE files, otherwise a /tmp cache downloaded from CelesTrak."""
    if glob.glob(os.path.join(DATA_DIR, "*.txt")):
        return DATA_DIR
    os.makedirs(CACHE_DIR, exist_ok=True)
    for fname, group in GROUPS.items():
        path = os.path.join(CACHE_DIR, fname + ".txt")
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_HOURS * 3600:
            continue
        try:
            req = urllib.request.Request(CELESTRAK.format(group), headers={"User-Agent": "OrbitGuard/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
            if body.lstrip()[:1] not in (b"<", b"") and b"\n1 " in body:
                with open(path, "wb") as f:
                    f.write(body)
        except Exception as e:  # keep any older cached copy
            print(f"[tle] could not download {group}: {e}")
    return CACHE_DIR


_CATALOG = {"key": None, "objects": []}


def load_catalog():
    """Cached load_tles() for the active folder; reloads when files change."""
    folder = tle_folder()
    files = sorted(glob.glob(os.path.join(folder, "*.txt")))
    key = (folder, tuple((f, os.path.getmtime(f)) for f in files))
    if key != _CATALOG["key"]:
        _CATALOG.update(key=key, objects=load_tles(folder))
    return _CATALOG["objects"]


def select_objects(objects, limit):
    """Deterministic selection: stations + debris first, then other satellites."""
    pri = [o for o in objects if "ISS" in o["name"] or o["is_debris"]]
    ids = {o["norad_id"] for o in pri}
    return (pri + [o for o in objects if o["norad_id"] not in ids])[:limit]


def load_tles(folder=DATA_DIR):
    """Read every .txt TLE file in `folder`. Returns a list of object dicts (no duplicates)."""
    objects, seen = [], set()
    for path in sorted(glob.glob(os.path.join(folder, "*.txt"))):
        fname = os.path.basename(path)
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = [ln.rstrip() for ln in f if ln.strip()]
        i = 0
        while i + 2 < len(lines):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            if l1.startswith("1 ") and l2.startswith("2 "):
                try:
                    norad = int(l1[2:7])
                except ValueError:
                    i += 1
                    continue
                if norad not in seen:
                    seen.add(norad)
                    objects.append({
                        "name": name,
                        "norad_id": norad,
                        "source_file": fname,
                        "line1": l1,
                        "line2": l2,
                        "is_debris": (" DEB" in name.upper()) or ("debris" in fname.lower()),
                    })
                i += 3
            else:
                i += 1
    return objects


def julian_dates(start_utc, n_steps, step_s):
    """Julian date split into (jd, fr) arrays, as SGP4 wants it."""
    jd0, fr0 = jday(start_utc.year, start_utc.month, start_utc.day,
                    start_utc.hour, start_utc.minute,
                    start_utc.second + start_utc.microsecond / 1e6)
    fr = fr0 + np.arange(n_steps) * step_s / 86400.0
    jd = np.full(n_steps, jd0)
    return jd, fr


def propagate_all(objects, start_utc, minutes=1440, step_s=30):
    """
    Propagate every object at once (vectorised SatrecArray).
    Returns (valid_objects, positions[n, t, 3] km, velocities[n, t, 3] km/s, times, jd_full).
    Objects where SGP4 reports an error (e.g. decayed orbit) are dropped.
    """
    n_steps = int(minutes * 60 / step_s)
    jd, fr = julian_dates(start_utc, n_steps, step_s)
    sats = [Satrec.twoline2rv(o["line1"], o["line2"]) for o in objects]
    e, r, v = SatrecArray(sats).sgp4(jd, fr)
    ok = (e == 0).all(axis=1) & np.isfinite(r).all(axis=(1, 2))
    valid = [o for o, good in zip(objects, ok) if good]
    times = [start_utc + timedelta(seconds=k * step_s) for k in range(n_steps)]
    return valid, r[ok].astype(np.float32), v[ok].astype(np.float32), times, jd + fr


def gmst_rad(jd_full):
    """Greenwich Mean Sidereal Time (radians) - how far Earth has rotated."""
    d = jd_full - 2451545.0
    t = d / 36525.0
    deg = 280.46061837 + 360.98564736629 * d + 0.000387933 * t * t - t ** 3 / 38710000.0
    return np.radians(deg % 360.0)


def teme_to_geo(r, jd_full):
    """
    TEME position(s) [..., 3] km -> (lat_deg, lon_deg, alt_km).
    Rotate by GMST to get an Earth-fixed frame, then spherical coordinates.
    """
    th = gmst_rad(jd_full)
    x = r[..., 0] * np.cos(th) + r[..., 1] * np.sin(th)
    y = -r[..., 0] * np.sin(th) + r[..., 1] * np.cos(th)
    z = r[..., 2]
    lon = np.degrees(np.arctan2(y, x))
    lat = np.degrees(np.arctan2(z, np.hypot(x, y)))
    alt = np.sqrt(x * x + y * y + z * z) - R_EARTH
    return lat, lon, alt


if __name__ == "__main__":
    objs = load_tles()
    print(f"Loaded {len(objs)} objects, {sum(o['is_debris'] for o in objs)} debris")
    for o in objs[:5]:
        print(f"  {o['norad_id']:>6}  {o['name']}")
    iss = next((o for o in objs if "ISS (ZARYA)" in o["name"]), objs[0] if objs else None)
    if iss:
        now = datetime.now(timezone.utc)
        valid, pos, _, times, jdf = propagate_all([iss], now, minutes=90, step_s=60)
        if valid:
            lat, lon, alt = teme_to_geo(pos[0], jdf)
            print(f"\n{iss['name']} next 90 min:")
            for k in range(0, 90, 10):
                print(f"  {times[k]:%H:%M} UTC  lat {lat[k]:7.2f}  lon {lon[k]:8.2f}  alt {alt[k]:6.1f} km")
        else:
            print("SGP4 error for", iss["name"], "(TLE too old? re-download data)")
