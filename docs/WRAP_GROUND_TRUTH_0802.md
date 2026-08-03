# The throttle wrap, settled from the device byte

I changed position on this three times in one session. This file records the sequence and the
final measurement, because the reasoning errors are more reusable than the answer.

## Final answer: the wrap is real

`follow.py` now reads back `gp.report.bRightTrigger` after the pad write, i.e. the literal byte
handed to ViGEm. No inference:

| commanded `thr` | byte actually sent |
|---|---|
| 0.90-1.00 | 0.9529 |
| **1.00-1.06** | **0.0235** |
| **1.06-1.30** | **0.1098** |
| 1.30-2.00 | 0.6471 |

Over-range ticks: mean commanded **1.181**, mean actually sent **0.194**. The
`round(v*255) % 256` reconstruction matches the truth on **99.6%** of ticks.

**Overall mean pedal: 0.3922 commanded, 0.3120 delivered. 20.4% destroyed.**

## The lag that made me retract a correct finding

Acceleration does not follow the pedal within a tick. Correlating `pad_thr(t)` against
`meas_long(t+k)`:

| lag | 0 ms | 56 ms | 83 ms | **111 ms** | 139 ms | 194 ms | 278 ms |
|---|---|---|---|---|---|---|---|
| corr | +0.492 | +0.642 | +0.704 | **+0.718** | +0.687 | +0.559 | +0.329 |

**Pedal to acceleration is 111 ms.** Over-range episodes have a median length of 111 ms, i.e.
exactly the lag, so a per-tick comparison at the over-range ticks measures the acceleration the
car is still carrying from *before* the episode. Unaligned, the deficit vanishes. Aligned by
8 ticks it is obvious:

| gear / rpm | cmd 0.90-1.00 | cmd >1.0 | delta |
|---|---|---|---|
| g3 4500-6000 | 7.62 | 3.33 | -4.29 |
| g3 6000-7300 | 14.62 | 9.81 | -4.81 |
| g4 4500-6000 | 12.15 | 1.34 | **-10.81** |
| g4 6000-7300 | 11.13 | 7.54 | -3.59 |

Mean **-5.87 m/s²**. Real, and smaller than the -10 to -13.6 m/s² I first reported.

## The three errors, in order

1. **Right answer, bad instrument.** The original -10 to -13.6 m/s² came from single-tick
   `dv/dt`. `spd_kmh` is logged rounded to 0.1 km/h, so at 72 Hz that estimator moves in ~2 m/s²
   steps and correlates only **+0.291** with true acceleration (the 200 ms smoothed version
   correlates +0.945). Its *median* snaps between quantisation levels, manufacturing large
   clean-looking deltas. The conclusion was right by luck, and the magnitude was inflated.
2. **Better instrument, missing correction.** Re-testing with `meas_long` but *without* lag
   alignment showed no deficit, and I retracted a correct finding on that basis.
3. **Hypotheses instead of measurement.** Between those two I proposed and discarded several
   explanations (wrong interpreter, vgamepad version, brief episodes smoothed by lag) when the
   decisive step was to log the byte. That took ten minutes and ended the argument.

## What does not change

`pad_clamp` stays **OFF**. Restoring ~20% more pedal was measured worse (30.62 s and 8 stalls
against 29.88 s and 0), and this result explains why rather than undermining it: the extra drive
is real, and the car cannot currently use it. Everything in `JOINT_SEARCH_1_RESULT.md` stands.

## Instruments that should have existed from the start

- `meas_long` — car-local longitudinal acceleration, straight from telemetry. Never log a
  derived quantity when the raw channel is in the packet.
- `pad_thr` / `pad_brk` — the actual bytes sent to the device, read back rather than assumed.
- **Lag-align by 8 ticks (111 ms) before relating any pedal input to any longitudinal response.**
