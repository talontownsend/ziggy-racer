"""Auto-resume watcher: start the live queue only when the machine is genuinely free.

FAIL CLOSED IS THE WHOLE DESIGN. Every check defaults to "hold" on any error, any ambiguity,
any unexpected state. A watcher that dies, hangs, or cannot answer a question must leave the
farm DOWN, never armed. It arms nothing itself -- it only invokes run_queue.py, which records
its restore obligation to disk BEFORE applying any pin, so even a crash mid-arm is recoverable
by `run_queue.py --recover`.

START CONDITIONS (all must hold simultaneously):
  1. No process from GAMES is running at all -- not merely idle, minimized or backgrounded.
     A running game means the user's session is in use even if they stepped away.
  2. Keyboard/mouse idle >= IDLE_MIN minutes.
  3. The foreground window does not belong to any process in GAMES.
  4. The queue has at least one pending step.
  5. No check raised an exception.

Every poll is appended to recordings/auto_resume_log.jsonl with its decision and the reasons,
so it can be audited afterwards for why it fired or held.

Reboot survival: state lives in recordings/auto_resume_state.json, same as the queue. The
process itself is restarted by the Scheduled Task registered in tools/register_auto_resume.ps1;
on restart it re-reads state and resumes polling. It never assumes it is the only instance --
a lock file with a liveness stamp prevents two watchers racing.

Usage:
  python tools/auto_resume.py --watch          poll forever (what the Scheduled Task runs)
  python tools/auto_resume.py --once           evaluate once, print the decision, do nothing
  python tools/auto_resume.py --simulate-free  evaluate with idle forged, to test the logic
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(ROOT, "recordings")
STATE = os.path.join(REC, "auto_resume_state.json")
LOG = os.path.join(REC, "auto_resume_log.jsonl")
LOCK = os.path.join(REC, "auto_resume.lock")
QUEUE = os.path.join(REC, "live_queue.json")
REPORT = os.path.join(REC, "liveness_report.txt")

POLL_S = 420          # 7 min
IDLE_MIN = 30.0       # required continuous idle before starting
LOCK_STALE_S = 1800

# Interactive titles whose presence means the session is in use. Substring match, case-insensitive.
GAMES = ["rocketleague", "forzahorizon", "forza", "cs2", "csgo", "valorant", "apex",
         "fortniteclient", "overwatch", "leagueoflegends", "dota2", "minecraft", "javaw",
         "gta5", "rdr2", "eldenring", "cyberpunk2077", "helldivers", "baldursgate3"]

PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

PROBE = r'''
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W {
 [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
 [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO p);
 [DllImport("kernel32.dll")] public static extern uint GetTickCount();
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 public static double IdleSec(){ LASTINPUTINFO i=new LASTINPUTINFO(); i.cbSize=(uint)Marshal.SizeOf(i);
   if(!GetLastInputInfo(ref i)) return -1; return (GetTickCount()-i.dwTime)/1000.0; }
 public static uint FgPid(){ uint p=0; GetWindowThreadProcessId(GetForegroundWindow(), out p); return p; }
}
"@
$idle = [W]::IdleSec()
$fg   = [W]::FgPid()
$fgn  = ""
try { if ($fg -gt 0) { $fgn = (Get-Process -Id $fg -ErrorAction Stop).ProcessName } } catch { $fgn = "?" }
$procs = @(Get-Process -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName)
[pscustomobject]@{ idle_s = $idle; fg_pid = $fg; fg_name = $fgn; procs = $procs } | ConvertTo-Json -Compress -Depth 3
'''


def probe():
    """Ask Windows for idle time, foreground process, and the process list. Raises on any doubt."""
    p = subprocess.run([PS, "-NoProfile", "-Command", PROBE],
                       capture_output=True, text=True, timeout=90)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError(f"probe failed rc={p.returncode} err={(p.stderr or '')[:200]}")
    d = json.loads(p.stdout)
    if d.get("idle_s") is None or float(d["idle_s"]) < 0:
        raise RuntimeError("GetLastInputInfo unavailable")
    return d


def games_running(procs):
    lp = [str(x).lower() for x in (procs or [])]
    return sorted({g for g in GAMES if any(g in n for n in lp)})


def queue_pending():
    with open(QUEUE) as f:
        q = json.load(f)
    return [s["id"] for s in q["steps"] if s["status"] == "pending"], q.get("restore_obligations", [])


def decide(force_idle=None):
    """Return (start: bool, reasons: dict). ANY exception upstream means hold."""
    r = {}
    d = probe()
    idle = float(force_idle) if force_idle is not None else float(d["idle_s"])
    r["idle_s"] = round(idle, 1)
    r["idle_ok"] = idle >= IDLE_MIN * 60
    g = games_running(d.get("procs"))
    r["games_running"] = g
    r["no_games"] = (len(g) == 0)
    fg = str(d.get("fg_name") or "?").lower()
    r["fg_name"] = d.get("fg_name")
    r["fg_not_game"] = (fg != "?") and not any(x in fg for x in GAMES)
    pend, obl = queue_pending()
    r["pending"] = pend
    r["has_pending"] = len(pend) > 0
    r["outstanding_obligations"] = len(obl)
    r["start"] = all([r["idle_ok"], r["no_games"], r["fg_not_game"], r["has_pending"]])
    return r["start"], r


def log(entry):
    entry["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def save_state(**kw):
    st = {}
    if os.path.exists(STATE):
        try:
            st = json.load(open(STATE))
        except Exception:
            st = {}
    st.update(kw)
    st["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, STATE)


def take_lock():
    """Refuse to run if another watcher stamped the lock recently. Fail closed on doubt."""
    now = time.time()
    if os.path.exists(LOCK):
        try:
            age = now - float(open(LOCK).read().strip())
        except Exception:
            return False
        if age < LOCK_STALE_S:
            return False
    open(LOCK, "w").write(str(now))
    return True


def liveness():
    """Prove the farm is alive with numbers, not an assertion."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import ab_arm
    out = ["=== LIVENESS ===", time.strftime("%Y-%m-%d %H:%M:%S")]
    p = os.path.join(REC, "follow_log.csv")
    s0 = os.path.getsize(p) if os.path.exists(p) else 0
    time.sleep(30)
    s1 = os.path.getsize(p) if os.path.exists(p) else 0
    out.append(f"  log growth: {s1-s0} bytes in 30 s")
    try:
        import csv as _c
        with open(p, newline="") as fh:
            hdr = next(_c.reader(fh))
        row_b = max((s1 - s0) / 30.0, 1e-9)
        out.append(f"  approx telemetry rows/sec: {row_b/ max(len(hdr)*7,1):.1f} (cols={len(hdr)})")
    except Exception as e:
        out.append(f"  row-rate probe failed: {e}")
    m = ab_arm.scan()
    if m and m["n_laps"]:
        out.append(f"  laps={m['n_laps']} median={m['med']:.2f} best={m['best']:.2f} "
                   f"stalls={m['stalls']} offtrack={m.get('offtrack_pct')}")
    else:
        out.append("  no clean laps yet")
    w = ab_arm.map_wmin()
    out.append(f"  map window-min: {w:.4f}" if w else "  map window-min: unavailable")
    try:
        q = json.load(open(QUEUE))
        for s in q["steps"]:
            g = s.get("baseline_gate")
            out.append(f"  [{s['status']:>11}] {s['id']}" + (f"  baseline_gate={g}" if g else ""))
    except Exception as e:
        out.append(f"  queue read failed: {e}")
    txt = "\n".join(out)
    with open(REPORT, "a") as f:
        f.write(txt + "\n\n")
    print(txt, flush=True)
    return txt


def fire():
    save_state(fired_at=time.strftime("%Y-%m-%d %H:%M:%S"), phase="starting")
    print("[fire] starting the watchdog", flush=True)
    subprocess.run([PS, "-NoProfile", "-Command",
                    f"Start-Process pwsh -ArgumentList '-NoProfile','-File','{os.path.join(ROOT,'watchdog.ps1')}' "
                    f"-WindowStyle Hidden"], timeout=120)
    time.sleep(240)                                    # let the follower come up and start racing
    for phase, args in (("recover", ["--recover"]), ("run", ["--run"])):
        save_state(phase=phase)
        print(f"[fire] run_queue {args}", flush=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "run_queue.py")] + args, cwd=ROOT)
    save_state(phase="queue-started")
    liveness()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--simulate-free", action="store_true")
    a = ap.parse_args()

    if a.once or a.simulate_free:
        try:
            start, r = decide(force_idle=(IDLE_MIN * 60 + 60) if a.simulate_free else None)
        except Exception as e:
            start, r = False, {"error": str(e), "start": False}
        r["mode"] = "simulate-free" if a.simulate_free else "once"
        log(r)
        print(json.dumps(r, indent=2))
        print("DECISION:", "START" if start else "HOLD")
        return 0

    if not a.watch:
        ap.print_help(); sys.exit(0)

    if not take_lock():
        print("another watcher holds the lock; exiting (fail closed)"); sys.exit(0)

    # HONOUR OBLIGATIONS BEFORE POLLING, unconditionally.
    #
    # There is a window inside run_queue between pinning the watchdog dead-man and the arm
    # completing. If everything dies in that window the dead-man stays pinned, and the NEXT
    # follower restart would silently arm the key with nobody watching. The obligation is
    # already on disk, but only --recover applies it and nothing else runs --recover after a
    # reboot. So the watcher does it first, every time it starts, before it can start anything.
    try:
        _r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "run_queue.py"), "--recover"],
                            cwd=ROOT, capture_output=True, text=True, timeout=300)
        log({"event": "STARTUP_RECOVER", "rc": _r.returncode, "out": (_r.stdout or "")[-400:]})
        print("[watch] startup --recover done", flush=True)
    except Exception as _e:
        log({"event": "STARTUP_RECOVER_FAILED", "error": str(_e)})
        print(f"[watch] startup --recover FAILED: {_e} -- holding, starting nothing", flush=True)
        return 0
    print(f"[watch] polling every {POLL_S}s; need no games AND idle >= {IDLE_MIN} min", flush=True)
    save_state(phase="watching", started=time.strftime("%Y-%m-%d %H:%M:%S"))
    while True:
        try:
            open(LOCK, "w").write(str(time.time()))
            start, r = decide()
        except Exception as e:                     # ANY failure -> hold
            start, r = False, {"error": str(e), "start": False, "held_because": "probe/queue error"}
        log(r)
        print(f"[watch] {'START' if start else 'hold'}  idle={r.get('idle_s')}s "
              f"games={r.get('games_running')} fg={r.get('fg_name')} pending={r.get('pending')}"
              f"{' err=' + r['error'] if r.get('error') else ''}", flush=True)
        if start:
            log({"event": "FIRING"})
            try:
                fire()
            except Exception as e:
                log({"event": "FIRE_FAILED", "error": str(e)})
                print(f"[fire] FAILED: {e}", flush=True)
            break                                   # one shot; the queue owns it from here
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main() or 0)
