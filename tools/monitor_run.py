"""Watchdog for a live follower run. Polls the log and prints an event ONLY on a
state change (stuck in dirt / data stalled / recovered) so it doesn't spam."""
import csv
import time

LOG = r"C:\Users\talon\FH6-AFK-Farm\recordings\follow_log.csv"
state = "ok"
last_t = None

while True:
    time.sleep(20)
    try:
        rows = list(csv.DictReader(open(LOG)))
    except Exception:
        continue
    if len(rows) < 80:
        continue
    cur_t = rows[-1]["t"]
    recent = rows[-250:]
    on = sum(int(float(r["on_track"])) for r in recent) / len(recent)
    gears = sorted({int(float(r["gear"])) for r in recent})
    spd = max(float(r["spd_kmh"]) for r in recent)

    if cur_t == last_t:
        new = "stalled"                      # no new telemetry in ~20s
    elif on < 0.45:
        new = "stuck"                        # mostly off-track
    else:
        new = "ok"
    last_t = cur_t

    if new != state:
        if new == "stuck":
            print(f"[watchdog] STUCK: {on:.0%} on-track over last {len(recent)} frames, "
                  f"idx {recent[-1]['i0']}, {spd:.0f} km/h", flush=True)
        elif new == "stalled":
            print(f"[watchdog] STALLED: no new telemetry (follower stopped / race ended / paused) "
                  f"at t={cur_t}s", flush=True)
        else:
            print(f"[watchdog] RECOVERED: {on:.0%} on-track, gears {gears}, {spd:.0f} km/h", flush=True)
        state = new
