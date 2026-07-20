"""Synthetic-packet self-test for fh6_telemetry.parse_packet (no game needed)."""
import struct
from fh6_telemetry import parse_packet, HORIZON_DASH_BASE

# Build a 324-byte Forza Horizon packet with known values.
buf = bytearray(324)
struct.pack_into("<i", buf, 0, 1)            # is_race_on = 1
struct.pack_into("<I", buf, 4, 123456)       # timestamp_ms
struct.pack_into("<f", buf, 16, 6500.0)      # rpm
struct.pack_into("<fff", buf, 32, 40.0, 0.0, 30.0)    # vel x,y,z
struct.pack_into("<fff", buf, 44, 0.0, 1.2, 0.0)      # angvel x,y,z (yaw rate)
struct.pack_into("<fff", buf, 56, 1.5708, 0.1, -0.2)  # yaw, pitch, roll

b = HORIZON_DASH_BASE
struct.pack_into("<fff", buf, b + 0, -123.5, 12.25, 678.75)  # pos x,y,z
struct.pack_into("<f", buf, b + 12, 55.0)    # speed m/s
struct.pack_into("<f", buf, b + 48, 4321.0)  # dist_traveled
struct.pack_into("<ffff", buf, b + 52, 30.0, 31.0, 12.34, 99.0)  # best,last,cur,racetime
struct.pack_into("<H", buf, b + 68, 3)       # lap_no
struct.pack_into("<BBBBBB", buf, b + 70, 1, 200, 0, 0, 0, 4)  # racepos,accel,brake,clutch,hand,gear
struct.pack_into("<b", buf, b + 76, -42)     # steer

f = parse_packet(bytes(buf))
assert f is not None
checks = {
    "is_race_on": (f.is_race_on, 1),
    "timestamp_ms": (f.timestamp_ms, 123456),
    "rpm": (round(f.rpm), 6500),
    "yaw": (round(f.yaw, 4), 1.5708),
    "vel_x": (round(f.vel_x), 40),
    "vel_z": (round(f.vel_z), 30),
    "angvel_y": (round(f.angvel_y, 1), 1.2),
    "pos_x": (round(f.pos_x, 2), -123.5),
    "pos_y": (round(f.pos_y, 2), 12.25),
    "pos_z": (round(f.pos_z, 2), 678.75),
    "speed_mps": (round(f.speed_mps), 55),
    "speed_kmh": (round(f.speed_kmh), 198),
    "dist_traveled": (round(f.dist_traveled), 4321),
    "cur_lap_time": (round(f.cur_lap_time, 2), 12.34),
    "cur_race_time": (round(f.cur_race_time), 99),
    "lap_no": (f.lap_no, 3),
    "accel": (f.accel, 200),
    "gear": (f.gear, 4),
    "steer": (f.steer, -42),
}
bad = {k: v for k, (v, want) in checks.items() if v != want}
for k, (got, want) in checks.items():
    print(f"  {'OK ' if got == want else 'XX '} {k:14} got={got!r:>10}  want={want!r}")
if bad:
    raise SystemExit(f"\nFAILED: {list(bad)}")
print("\nAll offsets correct. Parser is byte-exact for the 324B Horizon packet.")
