# Program Constraints

The invariants every shipped change must satisfy. If a change violates one of these, it doesn't
ship — regardless of lap time. Exceptions live in the register at the bottom, each with a
rationale and an exit path.

1. **Track-agnostic control path.** No arc-length or track-position literals in shipped control
   logic. Zones and limits must derive from survey geometry (crest/turn/bank detection), from
   physics conditions (curvature, speed, load, brake state), or from the car's own experience
   (self-learned maps). Porting to a new track must require only: survey the track, rebuild the
   artifacts, run.

2. **Device-honest I/O.** Input is the game's public telemetry stream (UDP "Data Out") only;
   output is a virtual Xbox controller only. No memory reading, no game-internal state, no
   scripting the game's own AI. The bot competes under the same I/O a human has.

3. **Independence from human data.** Human laps are *evaluation targets*, never *operating
   bounds*. No speed floor, steering profile, margin, or cap may be derived from human driving.
   (Single standing exception: the reference line — see register.)

4. **Self-calibrated limits.** Every planning limit — grip envelope, steering feasibility,
   braking capability, per-corner speed — comes from the bot's own measured telemetry and is
   rebuildable per car/track by script. No hand-entered physics numbers.

5. **Interpretable driving path.** The shipped control loop contains no black-box policy.
   Learned components must be inspectable artifacts (per-station tables, (κ,v) lookup maps,
   scalar gains). Neural components may exist offline or behind default-off keys.

6. **Unattended-safe.** The system must recover from every reachable state without a human:
   crashes, menus, dialogs, race restarts, process hangs. Experimental features must be
   dead-man-disarmed by any restart (watchdog re-writes their keys to off).

7. **Hot-revertible experimentation.** Anything armable must be revertible through the config
   file within seconds, without a process restart, and every live experiment must run under a
   monitor that executes its own rollback.

---

## Exceptions register

| Exception | Violates | Rationale | Exit path |
|---|---|---|---|
| Reference line = human's recorded best lap | #3 | Six computed-line solvers failed (inside-hugging); the measured-constraint optimizer later confirmed the human line is near-optimal under the bot's own limits. Deliberate, user-approved. | A recorded faster human session, or a future solver win, replaces the artifact — the mechanism (line-in-a-file) is already agnostic. |
| `mbc` cap spans (s470-608, s638-702) | #1 | The survey-derived zones (`mbc_geo`) under-protect crest exits; measured +0.75s-and-worse twice. | `mbc_geo` ships as the new-track bootstrap; a zone rule that learns exit extents from incidents would retire the literals. |
| `hul` stable-aim span (s515-565) | #1 | The condition-based form fires during hairpin recoveries where line-aim is infeasible (measured: 9 stalls/45min). | Curvature-feasibility-gated trigger (aim at the line only where the line is reachable). |

Everything else in the shipped path is mechanism-level. When adding an exception, add the row —
an undocumented exception is a bug.
