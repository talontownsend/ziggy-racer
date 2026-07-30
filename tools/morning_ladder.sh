#!/bin/bash
# Morning ladder: start the farm, verify the RIGHT CAR, then run the 07-29 arm ladder.
#
# Run this AFTER putting the Tacoma back and starting the 50-lap Shimanoyama event.
#   bash tools/morning_ladder.sh
#
# It refuses to score anything unless the car fingerprint matches (max_rpm 8000). On
# 2026-07-29 an EventLab auto-restart swapped in a Skyline (11000 rpm) and the learned map
# took 645 stations of damage before a human noticed; never again.
cd /c/Users/talon/FH6-AFK-Farm
PY=C:/Users/Talon/myenv/Scripts/python.exe
SNAP="recordings/snapshots"

echo "== starting watchdog =="
powershell.exe -NoProfile -Command "Start-Process pwsh -ArgumentList '-NoProfile','-File','C:\Users\talon\FH6-AFK-Farm\watchdog.ps1' -WindowStyle Hidden" >/dev/null 2>&1
sleep 90

echo "== verifying car identity and that we are actually racing =="
for i in $(seq 1 30); do
  ok=$($PY - <<'PYEOF'
import csv, collections
rpm = collections.Counter(); racing = 0
try:
    for r in csv.DictReader(open("recordings/follow_log.csv")):
        try:
            rpm[round(float(r["max_rpm"]))] += 1
            if float(r["race_pos"]) >= 1: racing += 1
        except Exception: pass
except Exception:
    print("nolog"); raise SystemExit
if not rpm: print("nolog"); raise SystemExit
top = rpm.most_common(1)[0][0]
print(f"{'CAROK' if abs(top-8000) <= 160 else 'CARBAD'}:{top}:{racing}")
PYEOF
)
  case "$ok" in
    CAROK:*:0)   echo "  car OK but not racing yet ($ok)";;
    CAROK:*)     echo "  car OK and racing ($ok)"; break;;
    CARBAD:*)    echo "  WRONG CAR ($ok) -- expected max_rpm 8000 (Tacoma). Put the Tacoma back and rerun."; exit 1;;
    *)           echo "  waiting for telemetry...";;
  esac
  sleep 30
done

racing_now() {
  $PY -c "
import sys; sys.path.insert(0,'tools'); import ab_arm as A
t=A.now_t(); m=A.scan(t_from=(t-600) if t else None,t_to=t) if t else None
print(1 if (m and m['n_laps']>=6) else 0)" 2>/dev/null | tail -1
}
if [ "$(racing_now)" != "1" ]; then echo "not producing race laps; aborting"; exit 1; fi

cp recordings/vtrim_map.npz   "$SNAP/vtrim_map_premorning.npz"
cp recordings/vtrim_delta.npz "$SNAP/vtrim_delta_premorning.npz"
restore() { cp "$SNAP/vtrim_map_premorning.npz" recordings/vtrim_map.npz
            cp "$SNAP/vtrim_delta_premorning.npz" recordings/vtrim_delta.npz; echo "  (map restored)"; }

$PY -c "
import json,os
t=json.load(open('recordings/tune.json'))
t.update({'vtrim_up':0.0,'vtrim_dn':0.0,'vtrim_netscale':0.0,'vtrim_on':1.0,'vtrim_cut':0.03})
json.dump(t,open('recordings/tune.json.tmp','w'),indent=1); os.replace('recordings/tune.json.tmp','recordings/tune.json')
print('vtrim learning frozen for the ladder (cut left armed)')"

echo "== settling 15 min, then reference window =="
sleep 900
$PY -c "
import sys; sys.path.insert(0,'tools'); import ab_arm as A
t=A.now_t(); m=A.scan(t_from=t-900,t_to=t)
print('REFERENCE', {k:m[k] for k in ['n_laps','med','best','stalls']})"

echo "== ARM 1: slip_target 1.05 -> 1.35 (throttle mute; tyres peak at slip 1.18-1.80) =="
$PY tools/ab_arm.py --label slip135 \
  --arm '{"slip_target":1.35}' --revert '{"slip_target":1.05}' \
  --equil 20 --score 40 --abort-stalls 3 --abort-med 30.6 --check 120
restore; sleep 420

echo "== ARM 2: brk_lock_slip 2.0 -> 3.0 (brake mute; own decel curve flat to 3.0) =="
$PY tools/ab_arm.py --label brk_lock30 \
  --arm '{"brk_lock_slip":3.0}' --revert '{"brk_lock_slip":2.0}' \
  --equil 20 --score 40 --abort-stalls 4 --abort-med 30.8
restore; sleep 420

echo "== ARM 3: corrected v_own raise-only (model says -0.235 s) =="
$PY tools/ab_arm.py --label vown_fixed \
  --arm '{"vown_w":1.0,"vown_raise":1.0}' --revert '{"vown_w":0.0}' \
  --equil 25 --score 40 --abort-stalls 4 --abort-med 30.8
restore

$PY -c "
import json,os
t=json.load(open('recordings/tune.json'))
t.update({'vtrim_up':0.0002,'vtrim_dn':0.002,'vtrim_netscale':0.1})
json.dump(t,open('recordings/tune.json.tmp','w'),indent=1); os.replace('recordings/tune.json.tmp','recordings/tune.json')
print('vtrim learning restored')"
echo "== LADDER COMPLETE =="
