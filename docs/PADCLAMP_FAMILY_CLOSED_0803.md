# The restored pedal cannot be used: six arms, closed

## The defect is real and confirmed from the device byte

`vgamepad` writes `round(v*255)` into a ctypes `c_ubyte` that wraps mod 256. Read back from
`gp.report.bRightTrigger`: commanded 1.00-1.06 is sent as **0.0235**, 1.06-1.30 as **0.1098**.
Mean pedal **0.3922 commanded, 0.3120 delivered: 20.4% destroyed**. Lag-aligned by the measured
111 ms, the acceleration cost is **-5.87 m/s²**.

And it attacks the right thing. Splitting the 3.25 s gap by what would have to change:

| regime | stations | loss | share |
|---|---|---|---|
| **delivery-limited** (car >10 km/h below its OWN target) | 534 | **+2.180 s** | **67.1%** |
| target-limited (within 5 km/h) | 401 | +0.864 s | 26.6% |
| in between | 65 | +0.205 s | 6.3% |

## Six arms say the car cannot use it

| arm | median | delta | stalls | off% | sideslip p99 | spd-tgt |
|---|---|---|---|---|---|---|
| baseline (08-03) | 30.29 | | 2 | 0.75 | 7.60 | -9.14 |
| `pad_clamp` alone (08-02) | 30.62 | +0.74 | 8 | 4.25 | 21.90 | |
| `pad_clamp` alone (re-test) | 31.10 | +1.26 | 11 | 3.54 | 22.00 | -9.26 |
| + `spin_thr` 2.5 | 30.14 | +0.30 | 5 | 2.58 | 15.50 | **-7.78** |
| + `spin_thr` 1.5 | 31.02 | +0.74 | 7 | 2.60 | 15.40 | -8.80 |
| + `spin_thr` 1.0 | 30.69 | +0.40 | 6 | 2.50 | 14.90 | -8.44 |
| + `spin_thr` 1.5 + `slip_target` 0.95 | 31.69 | +1.41 | **2** | 1.21 | 15.20 | **-10.19** |

Two things are now established.

**The guard plateaus.** Taking `spin_thr` from 2.5 to 1.5 to 1.0 quadruples then sextuples its
coverage and sideslip p99 stays pinned near 15 against a 7.6 baseline, with stalls stuck at 5-7.
A longitudinal wheelspin guard cannot absorb what the restored pedal does to this car.

**Where stability IS recovered, the delivery goes with it.** The only arm that returned to
baseline stability (2 stalls, off-track 1.21%) did so by tightening the combined ceiling, and its
speed-vs-target collapsed to **-10.19**, worse than the baseline it was trying to beat.

The delivery gain is real and measurable: `spin_thr` 2.5 produced **-7.78 km/h** speed-vs-target,
the best figure ever recorded on this bot. It simply costs more in instability than it returns.

## What this closes, and what it leaves

The `pad_clamp` family is closed. `pad_clamp`, `spin_thr` and `ff_thr` all stay OFF and remain in
the watchdog dead-man. The instruments they produced stay and are worth more than the arms were:
`pad_thr`/`pad_brk` (device ground truth), `meas_long` (raw longitudinal channel), the 111 ms
pedal lag, and the delivery/target decomposition above.

**Seventeen arms, no lap-time gain.** Five single-axis relaxations, three joint-axis, three
feedforward, six pad_clamp. The bot sits at 29.84-30.29 throughout, against a human 26.82 on the
same car, track and morning.

The honest position: two-thirds of the gap is the car failing to reach targets it has already
computed correctly, the one measured cause of that is a 20.4% pedal loss, and restoring that
pedal makes the car unstable in a way no available guard contains. That is not a tuning problem
and it is not a planning problem. It is that this controller, at this operating point, cannot
convert additional longitudinal authority into lap time.
