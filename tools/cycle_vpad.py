"""Destroy and recreate the virtual gamepad, raising a FRESH connection event.

Why this exists: when FH6 shows the controller-disconnected modal, the follower blocks on
telemetry and never reaches its own recovery, so it cannot press its way out. Worse, the pad
the game believes is gone cannot prove it is back by pressing buttons -- only a new device
arrival clears the modal. Measured 08-01: the farm sat dead 80 minutes across 7 follower
restarts because every restart recreated the pad while the game still held the stale handle.

The follower already has replug_pad() for this, but it is unreachable when the follower is
blocked pre-telemetry. So the watchdog needs to do it from outside the follower.

  python tools/cycle_vpad.py            cycle for real
  python tools/cycle_vpad.py --stub     print what it WOULD do, touch no hardware
  python tools/cycle_vpad.py --check    report whether vgamepad is importable, cycle nothing

NEVER run the real cycle while a human is using the machine -- it injects a device
arrival/removal into their session. The queue runs it once as a preflight smoke test, after
the watcher has confirmed the machine is free.
"""
import argparse
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--stub", action="store_true", help="dry run: no hardware touched")
ap.add_argument("--check", action="store_true", help="report importability only")
ap.add_argument("--hold", type=float, default=1.5, help="seconds between removal and arrival")
a = ap.parse_args()

if a.check or a.stub:
    try:
        import vgamepad  # noqa: F401
        ok = True
        detail = f"vgamepad importable ({getattr(vgamepad, '__file__', '?')})"
    except Exception as e:
        ok = False
        detail = f"vgamepad NOT importable: {type(e).__name__}: {e}"
    print(f"[cycle_vpad] {'STUB' if a.stub else 'CHECK'}: {detail}")
    if a.stub:
        print("[cycle_vpad] STUB: would del the pad, sleep "
              f"{a.hold}s, then construct a new VX360Gamepad (fresh arrival event)")
        print("[cycle_vpad] STUB: no hardware touched")
    sys.exit(0 if ok else 1)

try:
    import vgamepad as vg
except Exception as e:
    print(f"[cycle_vpad] FAILED to import vgamepad: {type(e).__name__}: {e}")
    sys.exit(2)

try:
    # Constructing a second pad then dropping both guarantees the old handle is released and a
    # genuinely new device arrives. Neutral report first so the game never sees a stuck input.
    pad = vg.VX360Gamepad()
    pad.reset()
    pad.update()
    time.sleep(0.2)
    del pad
    time.sleep(a.hold)                       # let Windows process the removal
    fresh = vg.VX360Gamepad()
    fresh.reset()
    fresh.update()
    time.sleep(0.3)
    del fresh
    print(f"[cycle_vpad] OK: pad removed and re-arrived (hold {a.hold}s)")
    sys.exit(0)
except Exception as e:
    print(f"[cycle_vpad] FAILED: {type(e).__name__}: {e}")
    sys.exit(3)
