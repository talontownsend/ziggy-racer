"""Arm the vtrim2 line-adherence DIAGNOSTIC into recordings/tune.json.
Run AFTER the follower has started (startup rewrites tune.json from args, wiping hot-only
keys). Freezes the grip map (map1) so vtrim2 learns against a fixed base, turns OFF the
hand-tuned s7m/acm margins so vtrim2 measures the RAW line-speed need, and enables vtrim2.
Idempotent: merges keys into the current tune.json without touching planner keys."""
import json
import os

TUNE = os.path.join(os.path.dirname(__file__), "recordings", "tune.json")

DIAG = {
    # --- freeze map1 (grip map): keep it ON (applies its learned boost outside the aperture)
    #     but ZERO all learning rates so it can't drift under the diagnostic ---
    "vtrim_on": 1.0, "vtrim_up": 0.0, "vtrim_dn": 0.0, "vtrim_cut": 0.0, "vtrim_netscale": 0.0,
    # --- margins OFF: vtrim2 must measure the raw line need, not the s7m/acm-patched behaviour ---
    "s7m_on": 0.0, "acm_on": 0.0,
    # --- vtrim2 line-adherence instrument ON (governs the S6->S10 aperture) ---
    "vt2_on": 1.0, "vt2_up": 0.004, "vt2_dn": 0.004, "vt2_band": 1.0,
    "vt2_steer_sat": 0.9, "vt2_clip_lo": 0.45, "vt2_clip_hi": 1.70, "vt2_reset": 0.0,
}


def main():
    with open(TUNE) as f:
        t = json.load(f)
    t.update(DIAG)
    tmp = TUNE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(t, f, indent=1)
    os.replace(tmp, TUNE)
    print("vtrim2 diagnostic ARMED in tune.json:")
    for k, v in DIAG.items():
        print(f"  {k} = {v}")
    print("\nmap1 FROZEN (learning rates 0), s7m/acm OFF, vtrim2 governing s430-783.")


if __name__ == "__main__":
    main()
