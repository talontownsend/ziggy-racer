"""Reboot-survivable runner for recordings/live_queue.json.

TALONSPC bugchecks every few days. A window interrupted mid-run must be recoverable from disk
alone, so every state transition is persisted BEFORE the action it describes, and the restore
obligations that ab_arm cannot honour (the watchdog dead-man, which ab_arm never touches) are
written to the queue file before arming rather than after.

Invariants
----------
* Restore obligations are honoured FIRST, before any new step, on every invocation.
* An obligation is recorded BEFORE the pin it describes is applied. Crash between the two
  leaves a harmless no-op obligation; the reverse order would leave the farm silently armed.
* A step is marked 'running' with a wall-clock stamp before its window starts, so a resumed
  run can tell "interrupted" from "never started".

Usage:
  python tools/run_queue.py --status     show queue state and outstanding obligations
  python tools/run_queue.py --recover    honour obligations only, then stop
  python tools/run_queue.py --run        honour obligations, then execute the next pending step
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, "recordings")
QUEUE = os.path.join(REC, "live_queue.json")
TUNE = os.path.join(REC, "tune.json")
WD = os.path.join(ROOT, "watchdog.ps1")


def load():
    with open(QUEUE) as f:
        return json.load(f)


def save(q):
    tmp = QUEUE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(q, f, indent=2)
    os.replace(tmp, QUEUE)          # atomic: a crash mid-write cannot corrupt the queue


def set_tune(keys):
    with open(TUNE) as f:
        t = json.load(f)
    t.update(keys)
    tmp = TUNE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(t, f, indent=1)
    os.replace(tmp, TUNE)


def set_deadman(keys):
    """Rewrite key=value inside watchdog.ps1's $addKeys. ab_arm CANNOT do this, which is why
    the dead-man and the live config desync at the end of every window (the pad_clamp failure)."""
    with open(WD, encoding="utf-8", errors="ignore") as f:
        s = f.read()
    missing = [k for k in keys if not re.search(rf"{re.escape(k)}=[0-9.]+", s)]
    if missing:
        # A key absent from $addKeys means the pin would be a SILENT NO-OP: the arm would not
        # survive a follower restart, and the window would be quietly voided rather than run.
        # Refuse loudly instead -- silent no-ops are the failure class that keeps recurring here.
        raise RuntimeError(f"watchdog.ps1 $addKeys has no entry for {missing}; "
                           f"add it (at its inert default) before arming.")
    for k, v in keys.items():
        s = re.sub(rf"{re.escape(k)}=[0-9.]+", f"{k}={v}", s, count=1)
    with open(WD, "w", encoding="utf-8", errors="ignore", newline="") as f:
        f.write(s)


def snapshot(tag):
    import shutil
    out = []
    for f in ("vtrim_net.npz", "vtrim_delta.npz"):
        src = os.path.join(REC, f)
        if os.path.exists(src):
            dst = os.path.join(REC, "snapshots", f.replace(".npz", f"_{tag}.npz"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            out.append(os.path.basename(dst))
    return out


def honour(q):
    """Apply every outstanding restore obligation, then clear them. Idempotent."""
    obs = q.get("restore_obligations", [])
    if not obs:
        return 0
    print(f"[recover] {len(obs)} outstanding restore obligation(s)")
    for o in obs:
        if o.get("tune"):
            set_tune(o["tune"]); print(f"  tune.json  <- {o['tune']}")
        if o.get("deadman"):
            set_deadman(o["deadman"]); print(f"  dead-man   <- {o['deadman']}")
    q["restore_obligations"] = []
    save(q)
    print("[recover] obligations cleared")
    return len(obs)


def status(q):
    print(f"queue {QUEUE}")
    ob = q.get("restore_obligations", [])
    print(f"  outstanding restore obligations: {len(ob)}")
    for o in ob:
        print(f"    {o}")
    for s in q["steps"]:
        extra = ""
        if s["status"] == "running":
            extra = f"  started {s.get('started_at','?')} (interrupted if no result)"
        if "result" in s:
            extra = f"  result {s['result']}"
        print(f"  [{s['status']:>9}] {s['id']}{extra}")


def run_next(q):
    step = next((s for s in q["steps"] if s["status"] == "pending"), None)
    if step is None:
        print("[run] nothing pending"); return 0
    dep = step.get("depends_on")
    if dep and next((x for x in q["steps"] if x["id"] == dep), {}).get("status") != "done":
        print(f"[run] {step['id']} blocked on {dep}"); return 2

    print(f"[run] {step['id']}")
    for script in step.get("preflight", []):
        # bare script paths, run with THIS interpreter -- "python" on PATH is the Store stub
        # on the laptop and would silently not be the venv.
        print(f"  preflight: {script}")
        if subprocess.run([sys.executable, script], cwd=ROOT).returncode != 0:
            print("  PREFLIGHT FAILED -- not arming"); return 3

    snaps = snapshot(step["snapshot_tag"])
    print(f"  learner snapshot -> {snaps}")

    # obligation FIRST, then the pin it describes
    q["restore_obligations"] = [{"step": step["id"], "tune": step["revert"],
                                 "deadman": step["deadman_restore"]}]
    step["status"] = "running"
    step["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save(q)
    set_deadman(step["deadman_pin"])
    print(f"  dead-man pinned {step['deadman_pin']}; obligation recorded")

    cmd = (f'"{sys.executable}" tools/ab_arm.py --label {step["id"]} '
           f"--arm '{json.dumps(step['arm'])}' --revert '{json.dumps(step['revert'])}' "
           f"--equil {step['equil_min']} --score {step['score_min']} "
           f"--abort-stalls {step['abort_stalls']} --abort-med {step['abort_med']} "
           f"--abort-lapmin {step['abort_lapmin']}")
    print(f"  {cmd}")
    p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
    print(p.stdout[-2000:] if p.stdout else "")
    m = re.search(r"RESULT_JSON (\{.*\})", p.stdout or "")
    step["result"] = json.loads(m.group(1)) if m else {"exit": p.returncode, "note": "no RESULT_JSON"}
    step["status"] = "done"
    save(q)

    honour(q)                      # restores tune + dead-man unconditionally
    print(f"  washout {step['washout_min']} min at baseline, then score the A-B-A")
    return 0


ap = argparse.ArgumentParser()
ap.add_argument("--status", action="store_true")
ap.add_argument("--recover", action="store_true")
ap.add_argument("--run", action="store_true")
a = ap.parse_args()
q = load()
if a.status:
    status(q)
elif a.recover:
    honour(q); status(q)
elif a.run:
    honour(q)                      # ALWAYS first
    sys.exit(run_next(q))
else:
    status(q)
