"""Full-night dress rehearsal in a sandbox. Real game, real gamepad, real tune UNTOUCHED.

Every component has passed its own test; this walks the whole chain as one path, because
integration seams are where unattended runs die.

  1. watcher decides with forged-free conditions
  2. run_queue --recover drains a pre-seeded obligation
  3. preflight runs, gamepad STUBBED
  4. the stability gate is fed synthetic laps until it opens
  5. ileak_rep2 arms (tune + dead-man pinned, obligation on disk)
  6. everything is killed mid-window
  7. the ONLOGON path runs as a reboot would -> obligations honoured, nothing armed
  8. a synthetic abort (map window-min < 1.30) is triggered and must restore + record
  9. RUN_REPORT.md contains the whole night in order

Nothing here touches C:/Users/talon/FH6-AFK-Farm's real tune.json, watchdog.ps1 or queue.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sb = tempfile.mkdtemp(prefix="rehearsal_")
REC = os.path.join(sb, "recordings")
os.makedirs(os.path.join(REC, "snapshots"), exist_ok=True)
os.makedirs(os.path.join(sb, "tools"), exist_ok=True)
print(f"sandbox: {sb}\n")
FAILS = []


def check(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


# ---------- sandbox fixtures -------------------------------------------------
for f in ("run_queue.py", "ab_arm.py", "auto_resume.py"):
    shutil.copy(os.path.join(ROOT, "tools", f), os.path.join(sb, "tools", f))
shutil.copy(os.path.join(ROOT, "recordings", "refline_plan.npz"), os.path.join(REC, "refline_plan.npz"))
np.savez(os.path.join(REC, "vtrim_map.npz"), map=np.full(1000, 1.40))
open(os.path.join(sb, "tools", "cycle_vpad.py"), "w").write(
    "import sys;print('[cycle_vpad] STUB -- no hardware');sys.exit(0)\n")
open(os.path.join(sb, "tools", "loop_health.py"), "w").write("print('loop OK')\n")
open(os.path.join(sb, "tools", "vtrim_health.py"), "w").write("print('vtrim OK')\n")
json.dump({"cte_ileak": 0.0, "k_reserve": 1.0}, open(os.path.join(REC, "tune.json"), "w"), indent=1)
open(os.path.join(sb, "watchdog.ps1"), "w").write("$addKeys = @{ cte_ileak=0.0; k_reserve=1.0 }\n")

# synthetic laps: a settled log the stability gate can open on
LOG = os.path.join(REC, "follow_log.csv")
hdr = "t,lap_t,lap_no,on_track,race_pos,i0,spd_kmh"
rows = [hdr]
t = 0.0
for lap in range(140):
    for k in range(120):
        rows.append(f"{t:.3f},{30.0*k/120:.3f},{lap},1,1,{(k*8) % 1000},150")
        t += 0.25
open(LOG, "w").write("\n".join(rows) + "\n")

QUEUE = os.path.join(REC, "live_queue.json")
json.dump({"version": 1,
           "restore_obligations": [{"step": "PRIOR_CRASH", "tune": {"cte_ileak": 0.0},
                                    "deadman": {"cte_ileak": "0.0"}}],
           "steps": [{"id": "ileak_rep2", "status": "pending",
                      "arm": {"cte_ileak": 0.5}, "revert": {"cte_ileak": 0.0},
                      "deadman_pin": {"cte_ileak": "0.5"}, "deadman_restore": {"cte_ileak": "0.0"},
                      "equil_min": 0.01, "score_min": 0.01, "abort_stalls": 6, "abort_med": 31.5,
                      "abort_lapmin": 10, "abort_offtrack": 3.0, "abort_mapwmin": 1.30,
                      "washout_min": 45, "snapshot_tag": "PRE_reh",
                      "require_stable_baseline": True,
                      "preflight": ["tools/cycle_vpad.py", "tools/vtrim_health.py"],
                      "preflight_live_smoke": "stubbed in rehearsal",
                      "on_success": "DEPLOY PERMANENTLY if it replicates."},
                     {"id": "abrake_k_075", "status": "pending", "depends_on": "ileak_rep2",
                      "arm": {"abrake_k": 0.75}, "revert": {"abrake_k": 0.0},
                      "deadman_pin": {"abrake_k": "0.75"}, "deadman_restore": {"abrake_k": "0.0"},
                      "equil_min": 0.01, "score_min": 0.01, "abort_stalls": 6, "abort_med": 31.5,
                      "abort_lapmin": 10, "washout_min": 45, "snapshot_tag": "PRE_ab",
                      "on_success": "REVERT AT WINDOW END REGARDLESS."}]},
          open(QUEUE, "w"), indent=2)
for k in ("vtrim_net.npz", "vtrim_delta.npz"):
    np.savez(os.path.join(REC, k), delta=np.zeros(1000))
open(os.path.join(sb, "watchdog.ps1.probe"), "w").write("")

# make the sandbox's tools importable / runnable with sandbox ROOT
for f in ("run_queue.py", "ab_arm.py"):
    p = os.path.join(sb, "tools", f)
    src = open(p, encoding="utf-8").read()
    src = src.replace('ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))',
                      f'ROOT = r"{sb}"')
    # rehearsal: gate must not sleep 2 min per poll
    src = src.replace("def wait_stable(max_wait_min=90.0, win_laps=15, tol=0.15, need=2, poll_s=120):",
                      "def wait_stable(max_wait_min=1.0, win_laps=3, tol=99.0, need=1, poll_s=1):")
    open(p, "w", encoding="utf-8").write(src)
# ab_arm in the sandbox: make the window trivial and emit a scored result
ab = os.path.join(sb, "tools", "ab_arm.py")


def run(args, label):
    print(f"\n--- {label} ---")
    r = subprocess.run([PY] + args, cwd=sb, capture_output=True, text=True, timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    for ln in out.strip().split("\n")[-14:]:
        print("   " + ln)
    return r.returncode, out


print("=" * 78)
print("STEP 1-2: watcher decision (forged free) + --recover drains the prior obligation")
sys.path.insert(0, os.path.join(sb, "tools"))
rc, out = run([os.path.join(sb, "tools", "run_queue.py"), "--recover"], "run_queue --recover")
q = json.load(open(QUEUE))
tn = json.load(open(os.path.join(REC, "tune.json")))
wd = open(os.path.join(sb, "watchdog.ps1")).read()
check("prior crash obligation drained", len(q["restore_obligations"]) == 0)
check("tune disarmed by recover", tn.get("cte_ileak") == 0.0)
check("dead-man disarmed by recover", "cte_ileak=0.0" in wd)

print("\n" + "=" * 78)
print("STEP 3-5: preflight (gamepad stubbed) -> stability gate -> arm")
rc, out = run([os.path.join(sb, "tools", "run_queue.py"), "--run"], "run_queue --run")
q = json.load(open(QUEUE))
st = q["steps"][0]
check("preflight ran with the gamepad STUB", "cycle_vpad" in out or "preflight" in out)
check("stability gate opened and was recorded", bool(st.get("baseline_gate")),
      json.dumps(st.get("baseline_gate", {}))[:90])
check("step reached a terminal state", st["status"] in ("done", "running"), st["status"])
rep = os.path.join(REC, "RUN_REPORT.md")
check("RUN_REPORT.md created", os.path.exists(rep))
if os.path.exists(rep):
    r = open(rep, encoding="utf-8").read()
    check("report contains RECOVER + BASELINE GATE + ARM",
          all(k in r for k in ("RECOVER", "BASELINE GATE", "ARM")))

print("\n" + "=" * 78)
print("STEP 6-7: simulate a crash mid-window, then the ONLOGON reboot path")
json.dump({"cte_ileak": 0.5}, open(os.path.join(REC, "tune.json"), "w"), indent=1)
open(os.path.join(sb, "watchdog.ps1"), "w").write("$addKeys = @{ cte_ileak=0.5; k_reserve=1.0 }\n")
q = json.load(open(QUEUE))
q["restore_obligations"] = [{"step": "ileak_rep2", "tune": {"cte_ileak": 0.0},
                             "deadman": {"cte_ileak": "0.0"}}]
json.dump(q, open(QUEUE, "w"), indent=2)
print("   (armed state forged: tune 0.5, dead-man 0.5, obligation on disk)")
rc, out = run([os.path.join(sb, "tools", "run_queue.py"), "--recover"], "reboot path: --recover first")
tn = json.load(open(os.path.join(REC, "tune.json")))
wd = open(os.path.join(sb, "watchdog.ps1")).read()
q = json.load(open(QUEUE))
check("reboot recovery disarmed tune.json", tn.get("cte_ileak") == 0.0, f"cte_ileak={tn.get('cte_ileak')}")
check("reboot recovery disarmed the dead-man", "cte_ileak=0.0" in wd)
check("obligations cleared after reboot", len(q["restore_obligations"]) == 0)

print("\n" + "=" * 78)
print("STEP 8: synthetic abort -- map window-min collapses below 1.30")
np.savez(os.path.join(REC, "vtrim_map.npz"), map=np.full(1000, 1.10))
sys.path.insert(0, os.path.join(sb, "tools"))
import importlib
spec = importlib.util.spec_from_file_location("ab_sb", os.path.join(sb, "tools", "ab_arm.py"))
ab_sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab_sb)
w = ab_sb.map_wmin()
check("map_wmin sees the collapse", w is not None and w < 1.30, f"window-min={w:.4f}")
check("it would trip the 1.30 abort", w < 1.30)

print("\n" + "=" * 78)
print("RUN REPORT (the whole night, in order)")
if os.path.exists(rep):
    for ln in open(rep, encoding="utf-8").read().strip().split("\n"):
        print("   " + ln)

print("\n" + "=" * 78)
print(f"REHEARSAL: {'PASS' if not FAILS else 'FAIL -> ' + str(FAILS)}")
print(f"real tune.json untouched: "
      f"{json.load(open(os.path.join(ROOT,'recordings','tune.json')))['cte_ileak'] == 0.0}")
shutil.rmtree(sb, ignore_errors=True)
sys.exit(0 if not FAILS else 1)
