# A_BRAKE is optimistic, and it explains the excursion

`follow.py` back-propagates the braking target at a fixed `A_BRAKE = 25.0 m/s^2 (2.55 g)`,
independent of steering. Measured against achieved longitudinal deceleration on 159,903 ticks
with brake > 0.30:

| \|steer\| band | ticks | achieved g | m/s² | vs assumed |
|---|---|---|---|---|
| straight <0.15 | 7,136 | 2.25 | 22.0 | −12% |
| partial 0.15-0.5 | 39,316 | 2.03 | 19.9 | −20% |
| heavy 0.5-0.9 | 42,009 | 1.38 | 13.5 | **−46%** |
| **full lock >0.9** | 71,442 | 1.44 | **14.1** | **−44%** |

**The assumption is optimistic everywhere and 44% optimistic at full lock**, which is where 45%
of braking ticks happen.

## The consequence, quantified

To shed 157 -> 121 km/h (the measured corner-1 approach):

| condition | braking distance needed |
|---|---|
| planner's budget (assumed 25.0) | **15.4 m** |
| achievable straight (22.0) | 17.5 m |
| achievable at full lock (14.1) | **27.4 m** |

**The follower starts braking 12.0 m too late for any corner that needs lock while braking.** It
then arrives hot, holds 100% brake at full lock (where combined slip further destroys lateral
grip), and washes wide. Same corner, same station, every lap.

## The human does the opposite

| | bot | human |
|---|---|---|
| brake onset | station 729 (s=780 m) | **station 712 (s=761 m)** |
| peak decel | 2.66 g @ stn 739 | 2.03 g @ stn 733 |
| brake at stn 754 | **100%** | 46% |
| minimum speed | 119.3 @ stn 790 | **144.2 @ stn 775** |

The human brakes **18 m earlier**, peaks **lower**, and **tapers** — trail-brake release. The bot
brakes late, peaks harder, and holds full brake at full lock 25 m deeper into the corner. That is
exactly the behaviour an optimistic `A_BRAKE` produces.

## The candidate change

`A_BRAKE` is a hardcoded constant (`follow.py` ~L1699). Lowering it, or making it steering-aware
(`A_BRAKE * (1 - k*|steer|)`), extends `look = 20 + v^2/(2*A_BRAKE)` and starts braking earlier.
At v = 182 km/h the lookahead goes 71 m -> 111 m if `A_BRAKE` drops 25 -> 14.1.

**Note the source comment records only that 28 was tried (brake later) and caused off-tracks.
Lowering it has not been tested.** The measurement says it should be.

Not implemented and not queued — reported for the decision. It is offline-reproducible: the
braking pass is pure arithmetic over `vplan`, already replicated exactly in `tools/tv_trace.py`
(median error +0.00 km/h).
