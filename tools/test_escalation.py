"""Offline test of the watchdog's disconnect-modal escalation, gamepad STUBBED.

Runs the REAL watchdog.ps1 in a sandbox against a log that never grows, with only these
substitutions: $root -> sandbox, the follower script -> a stub, the kill filter -> a pattern
that cannot match, and the timings compressed. Asserts:

  1. the ladder fires IN ORDER   -- plain restart first, gamepad cycle only on the second
  2. two failed full sequences   -> FAIL CLOSED
  3. fail-closed calls run_queue.py --recover and the obligation is actually honoured
  4. FARM_STOPPED.txt written and explains why
  5. nothing left armed

No real gamepad is touched and no real follower is started.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
PY = sys.executable
sb = tempfile.mkdtemp(prefix="wd_esc_")
print(f"sandbox: {sb}\n")
os.makedirs(os.path.join(sb, "recordings", "snapshots"), exist_ok=True)
os.makedirs(os.path.join(sb, "tools"), exist_ok=True)

# stalled log: exists, never grows
log = os.path.join(sb, "recordings", "follow_log.csv")
open(log, "w").write("t,x\n" + "0,0\n" * 50)
old = time.time() - 9999
os.utime(log, (old, old))

# queue with an OUTSTANDING obligation + an ARMED dead-man, so --recover has real work
json.dump({"version": 1,
           "restore_obligations": [{"step": "SIM", "tune": {"cte_ileak": 0.0},
                                    "deadman": {"cte_ileak": "0.0"}}],
           "steps": [{"id": "dummy", "status": "pending", "arm": {}, "revert": {},
                      "deadman_pin": {}, "deadman_restore": {}, "snapshot_tag": "x"}]},
          open(os.path.join(sb, "recordings", "live_queue.json"), "w"), indent=2)
json.dump({"cte_ileak": 0.5}, open(os.path.join(sb, "recordings", "tune.json"), "w"), indent=1)
open(os.path.join(sb, "watchdog.ps1"), "w").write("$addKeys = @{ cte_ileak=0.5 }\n")
shutil.copy(os.path.join(ROOT, "tools", "run_queue.py"), os.path.join(sb, "tools", "run_queue.py"))

# stubs
calls = os.path.join(sb, "calls.log")
open(os.path.join(sb, "tools", "cycle_vpad.py"), "w").write(
    f"open(r'{calls}','a').write('CYCLE_VPAD\\n')\nprint('[cycle_vpad] STUB, no hardware touched')\n")
open(os.path.join(sb, "stub_follower.py"), "w").write(
    f"open(r'{calls}','a').write('FOLLOWER_LAUNCH\\n')\n")
open(os.path.join(sb, "press_enter.py"), "w").write("pass\n")

wd = open(os.path.join(ROOT, "watchdog.ps1"), encoding="utf-8", errors="ignore").read()
wd = wd.replace('$root = "C:\\Users\\talon\\FH6-AFK-Farm"', f'$root = "{sb}"')
wd = wd.replace('"$root\\follow.py"', '"$root\\stub_follower.py"')
wd = wd.replace("'*follow.py*'", "'*NEVERMATCH_SENTINEL*'")     # never kill a real process
wd = wd.replace("$age -gt 180", "$age -gt 1").replace("$cool -gt 360", "$cool -gt 0")
wd = wd.replace("-gt $g0 + 2000", "-gt $g0 + 999999999")        # growth never resumes
wd = re.sub(r"Start-Sleep -Seconds \d+", "Start-Sleep -Milliseconds 150", wd)
open(os.path.join(sb, "watchdog_test.ps1"), "w", encoding="utf-8").write(wd)

print("running the stubbed watchdog against a permanently stalled log...\n")
try:
    subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    os.path.join(sb, "watchdog_test.ps1")],
                   cwd=sb, capture_output=True, text=True, timeout=240)
except subprocess.TimeoutExpired:
    print("  (timed out -- watchdog did not exit; that alone is a FAIL)\n")

wl = os.path.join(sb, "watchdog.log")
txt = open(wl).read() if os.path.exists(wl) else ""
for ln in txt.strip().split("\n"):
    print("   " + ln.strip())
seq = open(calls).read().strip().split("\n") if os.path.exists(calls) else []

print("\n=== ASSERTIONS ===")
ok = True


def check(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"   {detail}" if detail else ""))


first_cycle = seq.index("CYCLE_VPAD") if "CYCLE_VPAD" in seq else -1
first_launch = seq.index("FOLLOWER_LAUNCH") if "FOLLOWER_LAUNCH" in seq else -1
check("stage 0 is a plain restart (follower launched before any gamepad cycle)",
      first_launch >= 0 and (first_cycle < 0 or first_launch < first_cycle),
      f"order={seq}")
check("stage 1 cycles the gamepad", first_cycle >= 0, f"cycles={seq.count('CYCLE_VPAD')}")
check("escalation logged in order",
      txt.find("escalating: next attempt cycles") < txt.find("escalation: cycling the virtual gamepad")
      if "escalation: cycling" in txt else False)
check("failed twice then FAILED CLOSED", "FAIL CLOSED" in txt)
check("watchdog exited (did not keep thrashing)", "wrote" in txt and "exiting" in txt)

q = json.load(open(os.path.join(sb, "recordings", "live_queue.json")))
check("restore obligations honoured (queue drained)", len(q.get("restore_obligations", [])) == 0,
      f"remaining={len(q.get('restore_obligations', []))}")
t = json.load(open(os.path.join(sb, "recordings", "tune.json")))
check("tune.json disarmed by --recover", t.get("cte_ileak") == 0.0, f"cte_ileak={t.get('cte_ileak')}")
dm = open(os.path.join(sb, "watchdog.ps1")).read()
check("dead-man disarmed by --recover", "cte_ileak=0.0" in dm, dm.strip())
why = os.path.join(sb, "recordings", "FARM_STOPPED.txt")
check("FARM_STOPPED.txt written", os.path.exists(why))
if os.path.exists(why):
    w = open(why).read()
    check("it explains why and what to do", "controller-disconnect" in w and "--recover" in w)
    print("\n--- FARM_STOPPED.txt ---")
    for ln in w.strip().split("\n"):
        print("   " + ln)

print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
shutil.rmtree(sb, ignore_errors=True)
sys.exit(0 if ok else 1)
