# Night log, 2026-07-31/08-01

**Headline:** the farm was fundamentally broken when the night started, in ways nobody had
diagnosed, and it is now stable and self-healing. That cost most of the night, so only one arm
produced a scored result. Seven infrastructure defects were found and fixed, three of them
things that had been silently degrading the farm for days.

---

## The chain that was killing the farm

Each of these masked the next, which is why it took the whole night to unpick.

### 1. `TextInputHost.exe` was stealing the foreground (the root cause)

FH6 only accepts the virtual gamepad while it is the **foreground** window; lose focus and the
game pauses, the log stops growing, and the watchdog reads it as a hang. On this machine
**"Windows Input Experience" (`TextInputHost.exe`) repeatedly grabs the foreground**, and while
it holds it, `SetForegroundWindow` is *refused* - so every refocus attempt fails.

Measured: with **nobody touching the machine for 20 minutes the farm produced 0 laps** and sat
stale for 708 s. Refocus began succeeding on attempt 1 the instant that process was ended.

**Fixed:** the watchdog now ends it whenever the log stalls, and `tools/refocus_forza.ps1` uses
ALT priming + `AttachThreadInput` + verification with retries (plain `SetForegroundWindow`
cannot win the foreground lock from a background process).

### 2. Restarting the follower made things worse, not better

A restart destroys the vpad, so FH6 raises **"Controller Disconnected"**, which stops the Data
Out stream, which means the packet loop never runs and every unstick inside it is unreachable.
The follower would sit at its startup banner indefinitely.

And **a button press cannot fix a disconnect**: the dialog asks for a controller *connection
event*, not a keypress. The follower logged the same A+Enter dozens of times with no effect,
while a freshly created pad cleared it on the first A.

**Fixed:** `replug_pad()` destroys and recreates the pad to raise a fresh arrival. It is wired
into recovery (after 4 failed taps) *and* into the pre-telemetry path, the latter deliberately
**not** gated on foreground, since an arrival event is delivered regardless of focus. Verified
live: `dialog persists -> RE-PLUGGING` followed immediately by `racing confirmed`.

### 3. The learner had been carved down, and one pocket poisons ~18 m of track

This was the entire lap-time regression, and the mechanism is worth remembering.

`map_w` is a **window-MIN over the next 18 m**, so a handful of stations driven to the 0.80
floor pull the target down for *everything that can see them*. At station 294 the map still read
**1.550**, but stations 300-305 sat at the floor, so the target there was dragged from **217 to
119 km/h**. Predicted 118.9, observed 118.9.

37% of the lap ended up >10 km/h down, worth **+3.24 s** - which is exactly the regression.

The carving happened because every disconnect loop, wedge and stuck episode registered as a
corner incident. **Fixed:** `vtrim_quar` (20 s) suppresses incident learning after any recovery
or reset - an incident only teaches about a corner if the car was actually racing it.

**Also learned:** `vtrim_map.npz` is an **output**. The follower recomputes it from
`net.forward(features) + delta` at startup and overwrites the file, so restoring it does
nothing. The real inputs are `vtrim_net.npz` and `vtrim_delta.npz`, and the net absorbs damage
too. Restoring the pre-night delta recovered 0.64 s and cut the damaged stations from 37.6% to
19%.

---

## The one scored result

With the farm finally stable, the baseline calibrated cleanly:

    50 laps   med 32.32   p25 31.91   p75 32.79   best 31.44   stalls 0

**`slip_target` 1.05 -> 1.35: REJECTED.** It took the car from **0 stalls in 50 laps to 4 stalls
in 15 minutes** and self-aborted. Note the median never degraded (32.90, inside the baseline
band) - the failure mode is *instability*, not slowness, which matches the documented 07-03
power-oversteer precedent exactly. The "tyres peak at slip 1.18-1.80" analysis is probably right
about the tyres and wrong about the consequence: the extra slip goes into rotation, not drive.

---

## Two mistakes of mine worth recording

- **I set abort thresholds against a baseline that no longer existed.** The first ladder used
  `abort_med` 30.9-31.0 from the 07-29 config while the live baseline was 32.3, so all three
  arms aborted within 3 minutes for being *at* baseline. That is the exact METHODOLOGY rule I
  had written down ("calibrate thresholds on the current config"), violated the same week.
- **The abort monitor judged the median during equilibration**, which is the one window where a
  worse median is expected by design. Both fixed: the median abort now only applies after
  scoring starts, while the stall abort stays armed throughout.

I also nearly reported a **26.66 s best lap** as a record. It was an artifact of the scanner
taking `max(lap_t)` per lap number, which catches a partial lap across a reset. The real
distribution was min 31.44 / med 32.32. Checked before it reached you.

---

## Where the remaining gap is

After the learner restore the gap to the 07-29 reference (29.72) is **+2.51 s**, and it is no
longer a target problem - most zones now command *identical* targets and the car simply arrives
slower. The loss cascades from about s748 into s858, where the car arrives at **79.6 km/h against
a 136 km/h target**, part-throttle and not braking. That is an execution/cascade problem and
needs a fresh session rather than the end of this one.

## State

Farm running, Tacoma, learning **frozen** (correct A/B condition), all experimental keys at
legacy defaults, learner snapshotted to `recordings/snapshots/*_arm0801.npz`.
