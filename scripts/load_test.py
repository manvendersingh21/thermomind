#!/usr/bin/env python3
"""Concurrency / load test for the ThermoMind API (read-only decision support; no app code touched).

Usage: python scripts/load_test.py --base http://127.0.0.1:8040 --pid <server pid> [--skip-live] [--out results.json]
Phases: 1 GET/POST bursts, 2 offline investigations, 3 review storm, 4 live Meta pair, 5 RSS.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

DS = "ds_uci_551"


def rss_kb(pid: int) -> int | None:
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else float("nan")


def timed(client, method, url, **kw):
    t = time.perf_counter()
    try:
        r = client.request(method, url, **kw)
        return r.status_code, time.perf_counter() - t, r
    except Exception as exc:  # noqa: BLE001
        return f"EXC:{type(exc).__name__}", time.perf_counter() - t, None


def phase1(base, n=50):
    preview = {"dataset_id": DS, "scenario_id": "S02_INTAKE_RESTRICTION", "year": 2014,
               "start_index": 1200, "end_index": 1320, "measurements": ["AFDP", "TEY", "CDP"]}
    reqs = []
    for i in range(n):
        k = i % 5
        if k == 0:
            reqs.append(("GET", "/api/health", None))
        elif k == 1:
            reqs.append(("GET", f"/api/datasets/{DS}/series?measure=AFDP&year={2011 + i % 5}&start={i * 100}&limit=500", None))
        elif k == 2:
            reqs.append(("GET", f"/api/datasets/{DS}/series?measure=TEY&year=2014&start=0&limit=2000&include_expected=true", None))
        elif k == 3:
            p = dict(preview, scenario_id=["S01_NORMAL", "S02_INTAKE_RESTRICTION", "S03_SENSOR_INCONSISTENCY", "S04_AMBIENT_SHIFT"][i % 4],
                     start_index=1200 + (i % 7) * 50, end_index=1320 + (i % 7) * 50)
            reqs.append(("POST", "/api/scenarios/preview", p))
        else:
            reqs.append(("GET", "/api/models/evaluation", None))
    with httpx.Client(base_url=base, timeout=120, limits=httpx.Limits(max_connections=100)) as c:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(n) as ex:
            res = list(ex.map(lambda q: (q[1].split("?")[0], *timed(c, q[0], q[1], json=q[2])[:2]), reqs))
        wall = time.perf_counter() - t0
    by = {}
    for path, st, lat in res:
        by.setdefault(path, []).append((st, lat))
    out = {"n": n, "wall_s": round(wall, 2), "non_2xx": [(p, s) for p, s, _ in res if not (isinstance(s, int) and 200 <= s < 300)],
           "overall": {"p50_ms": round(pct([l for _, _, l in res], 50) * 1e3), "p95_ms": round(pct([l for _, _, l in res], 95) * 1e3),
                       "max_ms": round(max(l for _, _, l in res) * 1e3)}, "by_endpoint": {}}
    for p, v in by.items():
        ls = [l for _, l in v]
        out["by_endpoint"][p] = {"n": len(v), "p50_ms": round(pct(ls, 50) * 1e3), "p95_ms": round(pct(ls, 95) * 1e3)}
    return out


def create(c, body):
    st, lat, r = timed(c, "POST", "/api/investigations", json=body)
    return st, lat, (r.json() if r is not None and st == 200 else (r.text[:300] if r is not None else None))


def verify_cases(c, case_ids):
    problems = []
    for cid in case_ids:
        st, _, r = timed(c, "GET", f"/api/investigations/{cid}")
        if st != 200:
            problems.append((cid, "get", st))
            continue
        inv = r.json()
        st, _, r2 = timed(c, "GET", f"/api/investigations/{cid}/evidence")
        evs = r2.json() if st == 200 else []
        if st != 200 or not evs:
            problems.append((cid, "evidence_list", st, len(evs)))
        ids = {e["evidence_id"] for e in evs}
        for eid in list(ids)[:5]:
            st, _, _ = timed(c, "GET", f"/api/investigations/{cid}/evidence/{eid}")
            if st != 200:
                problems.append((cid, "evidence_get", eid, st))
        rep = inv.get("report")
        if rep:
            cited = set(json.dumps(rep).split('"'))
            cited = {s for s in cited if s.startswith("ev_")}
            miss = cited - ids
            if miss:
                problems.append((cid, "report_cites_unknown_evidence", sorted(miss)[:5]))
    return problems


def phase2(base):
    scen = ["S01_NORMAL", "S02_INTAKE_RESTRICTION", "S03_SENSOR_INCONSISTENCY", "S04_AMBIENT_SHIFT"]
    bodies = [{"dataset_id": DS, "scenario_id": scen[i % 4], "year": 2011 + i % 5, "start_index": 1200 + 137 * i,
               "end_index": 1320 + 137 * i + 20 * (i % 3), "use_meta": False, "seed": 100 + i} for i in range(8)]
    with httpx.Client(base_url=base, timeout=300, limits=httpx.Limits(max_connections=100)) as c:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(8) as ex:
            res = list(ex.map(lambda b: create(c, b), bodies))
        wall = time.perf_counter() - t0
        ids = [r[2]["case_id"] for r in res if r[0] == 200]
        problems = verify_cases(c, ids)
        _, _, lr = timed(c, "GET", "/api/investigations")
        listed = {i["case_id"] for i in lr.json()} if lr is not None else set()
    return {"n": 8, "wall_s": round(wall, 2), "statuses": [r[0] for r in res], "inv_status": [r[2]["status"] if r[0] == 200 else r[2] for r in res],
            "latency_s": [round(r[1], 2) for r in res], "case_ids": ids, "all_in_list": set(ids) <= listed, "verify_problems": problems}


def phase3(base, case_id, n=20):
    decisions = ["accepted", "rejected", "more_data_requested"]
    with httpx.Client(base_url=base, timeout=120, limits=httpx.Limits(max_connections=100)) as c:
        with ThreadPoolExecutor(n) as ex:
            res = list(ex.map(lambda i: (i, *timed(c, "POST", f"/api/investigations/{case_id}/review",
                                                   json={"decision": decisions[i % 3], "reviewer": f"rev{i}", "comment": f"c{i}"})[:2]), range(n)))
        before = None
        st, _, r = timed(c, "GET", f"/api/investigations/{case_id}")
        inv = r.json()
    rv = inv.get("review")
    ok_ids = {f"rev{i}" for i, s, _ in res if s == 200}
    return {"n": n, "statuses": sorted({str(s) for _, s, _ in res}), "count_500": sum(1 for _, s, _ in res if s == 500 or (isinstance(s, str))),
            "p95_ms": round(pct([l for *_, l in res], 95) * 1e3), "final_review": rv,
            "final_reviewer_among_successful": bool(rv and rv["reviewer"] in ok_ids),
            "final_fields_coherent": bool(rv and rv["decision"] == decisions[int(rv["reviewer"][3:]) % 3] and rv["comment"] == "c" + rv["reviewer"][3:]),
            "status_unchanged_and_report_present": inv["status"] in ("completed", "needs_review"),
            "report_status": (inv.get("report") or {}).get("status")}


def phase4(base):
    bodies = [{"dataset_id": DS, "scenario_id": s, "use_meta": True} for s in ("S02_INTAKE_RESTRICTION", "S03_SENSOR_INCONSISTENCY")]
    out = {}
    with httpx.Client(base_url=base, timeout=600) as c:
        hb = {"stop": False, "lat": []}

        def heartbeat():
            while not hb["stop"]:
                st, lat, _ = timed(c, "GET", "/api/health")
                hb["lat"].append((st, lat))
                time.sleep(2)
        th = threading.Thread(target=heartbeat, daemon=True)
        th.start()
        t0 = time.perf_counter()
        with ThreadPoolExecutor(2) as ex:
            res = list(ex.map(lambda b: create(c, b), bodies))
        out["wall_s"] = round(time.perf_counter() - t0, 1)
        hb["stop"] = True
        th.join()
        out["runs"] = [{"scenario": b["scenario_id"], "http": r[0], "latency_s": round(r[1], 1),
                        "status": r[2]["status"] if r[0] == 200 else r[2]} for b, r in zip(bodies, res)]
        ids = [r[2]["case_id"] for r in res if r[0] == 200]
        out["verify_problems"] = verify_cases(c, ids)
        for cid in ids:
            inv = c.get(f"/api/investigations/{cid}").json()
            out.setdefault("details", []).append({"case_id": cid, "mode": (inv.get("report") or {}).get("mode"),
                                                  "meta_used": inv.get("meta_used"), "error": inv.get("error"),
                                                  "n_events": len(inv.get("events", []))})
        out["health_during"] = {"n": len(hb["lat"]), "non_200": [s for s, _ in hb["lat"] if s != 200],
                                "p95_ms": round(pct([l for _, l in hb["lat"]], 95) * 1e3), "max_ms": round(max([l for _, l in hb["lat"]] or [0]) * 1e3)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8040")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--skip-live", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    R = {"rss_kb_start": rss_kb(a.pid)}
    print("phase1", flush=True); R["phase1_bursts"] = phase1(a.base); print(json.dumps(R["phase1_bursts"]), flush=True)
    R["rss_kb_after_p1"] = rss_kb(a.pid)
    print("phase2", flush=True); R["phase2_offline"] = phase2(a.base); print(json.dumps(R["phase2_offline"]), flush=True)
    R["rss_kb_after_p2"] = rss_kb(a.pid)
    ids = R["phase2_offline"]["case_ids"]
    if ids:
        print("phase3", flush=True); R["phase3_reviews"] = phase3(a.base, ids[0]); print(json.dumps(R["phase3_reviews"]), flush=True)
    if not a.skip_live:
        print("phase4 (long)", flush=True); R["phase4_live"] = phase4(a.base); print(json.dumps(R["phase4_live"]), flush=True)
    R["rss_kb_end"] = rss_kb(a.pid)
    if a.out:
        json.dump(R, open(a.out, "w"), indent=2)
    print(json.dumps({k: v for k, v in R.items() if k.startswith("rss")}))


if __name__ == "__main__":
    sys.exit(main())
