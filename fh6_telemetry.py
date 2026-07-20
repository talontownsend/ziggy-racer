#!/usr/bin/env python3
"""
FH6 telemetry recorder (Stage 0) -- READ ONLY.

Listens to Forza Horizon 6's "Data Out" UDP stream, parses each packet, prints a
live readout, and records every in-race packet to a per-race CSV. This injects
nothing into the game; it only reads the broadcast FH6 sends by design, so it is
safe to run and is the foundation for the path-following controller later.

Setup in FH6:
    Settings > HUD and Gameplay > Data Out          -> ON
              Data Out IP Address                    -> 127.0.0.1
              Data Out IP Port                       -> 20440   (must match --port)

Then:
    python fh6_telemetry.py                 # live readout + record laps to ./recordings
    python fh6_telemetry.py --port 20440 --out ./recordings

Packet format (Forza Horizon "Dash", 324 bytes, little-endian):
    - Sled block, offsets 0..231 (stable across all Forza titles):
        0   IsRaceOn            s32
        4   TimestampMS         u32
        16  CurrentEngineRpm    f32
        20  Acceleration X/Y/Z  3x f32
        32  Velocity X/Y/Z      3x f32
        56  Yaw / Pitch / Roll  3x f32   (radians)
    - Dash block, Horizon base offset 244 (FH4/FH5/FH6):
        +0   PositionX/Y/Z      3x f32   (meters, world space)
        +12  Speed              f32      (m/s)
        +48  DistanceTraveled   f32      (meters this race)
        +52  Best/Last/Cur lap + CurrentRaceTime  4x f32 (seconds)
        +68  LapNumber          u16
        +70  RacePos, Accel, Brake, Clutch, HandBrake, Gear  6x u8
        +76  Steer              s8       (-127..127)
        +77  NormalizedDrivingLine, NormalizedAIBrakeDifference  2x s8

The Horizon packet has a 12-byte gap between the sled and the dash block, so the
dash base is 244 (not 232 as in Forza Motorsport 7). If your build streams a
different size, pass --dash-offset to nudge it; the script prints the packet
length on the first packet so you can confirm.
"""
from __future__ import annotations

import argparse
import csv
import socket
import struct
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

DASH_TAIL_SIZE = 79          # PositionX .. NormalizedAIBrakeDifference
HORIZON_DASH_BASE = 244      # FH4 / FH5 / FH6
MOTORSPORT_DASH_BASE = 232   # FM7 (no Horizon gap) -- fallback


@dataclass
class Frame:
    timestamp_ms: int
    is_race_on: int
    lap_no: int
    cur_lap_time: float
    cur_race_time: float
    dist_traveled: float
    pos_x: float
    pos_y: float
    pos_z: float
    speed_mps: float
    yaw: float
    pitch: float
    roll: float
    vel_x: float
    vel_y: float
    vel_z: float
    angvel_x: float
    angvel_y: float
    angvel_z: float
    rpm: float
    max_rpm: float
    gear: int
    accel: int   # game's own input value 0..255
    brake: int
    steer: int   # -127..127
    # --- grip / slip telemetry (Forza Dash sled block) -- added for grip-aware control ---
    ax: float = 0.0      # lateral acceleration, CAR-LOCAL right+ (m/s^2) = measured lateral grip
    ay: float = 0.0      # vertical acceleration (m/s^2)
    az: float = 0.0      # longitudinal acceleration, forward+ (m/s^2)
    slip_ratio_fl: float = 0.0   # longitudinal tire slip (wheelspin >0 / lockup <0)
    slip_ratio_fr: float = 0.0
    slip_ratio_rl: float = 0.0
    slip_ratio_rr: float = 0.0
    slip_angle_fl: float = 0.0   # lateral tire slip angle (rad)
    slip_angle_fr: float = 0.0
    slip_angle_rl: float = 0.0
    slip_angle_rr: float = 0.0
    combined_slip_fl: float = 0.0  # combined (lat+long) normalized slip, ~1.0 = grip limit
    combined_slip_fr: float = 0.0
    combined_slip_rl: float = 0.0
    combined_slip_rr: float = 0.0
    drivetrain: int = 0          # 0=FWD, 1=RWD, 2=AWD
    race_position: int = 0       # player's position in the race (1..N); 0 in FREE ROAM (no race).
                                 # The clean race-vs-freeroam signal: is_race_on/clock are 1 in BOTH.

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6


def _dash_base(packet_len: int, override: int | None) -> int | None:
    if override is not None:
        return override
    if packet_len >= 324:
        return HORIZON_DASH_BASE
    if packet_len >= 311:
        return MOTORSPORT_DASH_BASE
    return None  # sled-only packet: no position data


def parse_packet(data: bytes, dash_override: int | None = None) -> Frame | None:
    """Parse one Data Out packet into a Frame, or None if it carries no dash block."""
    base = _dash_base(len(data), dash_override)
    if base is None or len(data) < base + DASH_TAIL_SIZE:
        return None

    is_race_on = struct.unpack_from("<i", data, 0)[0]
    timestamp_ms = struct.unpack_from("<I", data, 4)[0]
    max_rpm = struct.unpack_from("<f", data, 8)[0]
    rpm = struct.unpack_from("<f", data, 16)[0]
    ax, ay, az = struct.unpack_from("<fff", data, 20)                # accel, car-local (m/s^2)
    vel_x, vel_y, vel_z = struct.unpack_from("<fff", data, 32)        # m/s, car-local
    angvel_x, angvel_y, angvel_z = struct.unpack_from("<fff", data, 44)  # rad/s
    yaw, pitch, roll = struct.unpack_from("<fff", data, 56)
    # tire slip arrays (FL,FR,RL,RR); offsets are stable in the Forza Dash sled block
    srfl, srfr, srrl, srrr = struct.unpack_from("<ffff", data, 84)    # slip RATIO (longitudinal)
    safl, safr, sarl, sarr = struct.unpack_from("<ffff", data, 164)   # slip ANGLE (lateral, rad)
    csfl, csfr, csrl, csrr = struct.unpack_from("<ffff", data, 180)   # COMBINED slip (~1=limit)
    drivetrain = struct.unpack_from("<i", data, 224)[0]              # 0=FWD 1=RWD 2=AWD

    pos_x, pos_y, pos_z = struct.unpack_from("<fff", data, base + 0)
    speed = struct.unpack_from("<f", data, base + 12)[0]
    dist = struct.unpack_from("<f", data, base + 48)[0]
    _best, _last, cur_lap, cur_race_time = struct.unpack_from("<ffff", data, base + 52)
    lap_no = struct.unpack_from("<H", data, base + 68)[0]
    racepos, accel, brake, _clutch, _hand, gear = struct.unpack_from("<BBBBBB", data, base + 70)
    steer = struct.unpack_from("<b", data, base + 76)[0]

    return Frame(
        timestamp_ms=timestamp_ms, is_race_on=is_race_on, lap_no=lap_no,
        cur_lap_time=cur_lap, cur_race_time=cur_race_time, dist_traveled=dist,
        pos_x=pos_x, pos_y=pos_y, pos_z=pos_z, speed_mps=speed,
        yaw=yaw, pitch=pitch, roll=roll,
        vel_x=vel_x, vel_y=vel_y, vel_z=vel_z,
        angvel_x=angvel_x, angvel_y=angvel_y, angvel_z=angvel_z,
        rpm=rpm, max_rpm=max_rpm, gear=gear, accel=accel, brake=brake, steer=steer,
        ax=ax, ay=ay, az=az,
        slip_ratio_fl=srfl, slip_ratio_fr=srfr, slip_ratio_rl=srrl, slip_ratio_rr=srrr,
        slip_angle_fl=safl, slip_angle_fr=safr, slip_angle_rl=sarl, slip_angle_rr=sarr,
        combined_slip_fl=csfl, combined_slip_fr=csfr, combined_slip_rl=csrl, combined_slip_rr=csrr,
        drivetrain=drivetrain, race_position=racepos,
    )


CSV_FIELDS = list(Frame.__annotations__.keys())


class RaceRecorder:
    """Opens a fresh CSV each time a race starts (IsRaceOn 0->1), closes on stop."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._writer = None
        self._fh = None
        self._rows = 0
        self._path: Path | None = None

    def _open(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = self.out_dir / f"run_{stamp}.csv"
        self._fh = self._path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=CSV_FIELDS)
        self._writer.writeheader()
        self._rows = 0

    def _close(self):
        if self._fh:
            self._fh.close()
            print(f"\n  saved {self._rows} frames -> {self._path}")
        self._fh = self._writer = self._path = None

    def feed(self, frame: Frame):
        if frame.is_race_on:
            if self._writer is None:
                self._open()
                print(f"\n  >> race started, recording to {self._path.name}")
            self._writer.writerow(asdict(frame))
            self._rows += 1
        else:
            if self._writer is not None:
                self._close()

    def close(self):
        self._close()


class ContinuousRecorder:
    """Records EVERY packet (in-race and free-roam) to one CSV. Used for boundary
    traces and calibration runs, where we split the laps afterward by lap_no."""

    def __init__(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = out_dir / f"session_{stamp}.csv"
        self._fh = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=CSV_FIELDS)
        self._writer.writeheader()
        self.rows = 0
        print(f"  recording ALL frames -> {self.path}")

    def feed(self, frame: Frame):
        self._writer.writerow(asdict(frame))
        self.rows += 1
        if self.rows % 60 == 0:          # flush ~1x/sec so the file is readable live
            self._fh.flush()

    def close(self):
        if self._fh:
            self._fh.flush()
            self._fh.close()
            print(f"\n  saved {self.rows} frames -> {self.path}")
            self._fh = None


def main() -> int:
    ap = argparse.ArgumentParser(description="FH6 Data Out telemetry recorder (read-only)")
    ap.add_argument("--ip", default="0.0.0.0", help="bind address (default: all interfaces)")
    ap.add_argument("--port", type=int, default=20440, help="UDP port (match FH6 Data Out, default 20440)")
    ap.add_argument("--out", default="./recordings", help="directory for per-race CSVs")
    ap.add_argument("--dash-offset", type=int, default=None,
                    help="override dash block base offset (default: auto, 244 for FH6)")
    ap.add_argument("--all", action="store_true",
                    help="record EVERY packet (in-race AND free-roam) to one CSV; "
                         "for boundary traces / calibration runs")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((args.ip, args.port))
    except OSError as exc:
        print(f"ERROR: could not bind {args.ip}:{args.port} -- {exc}", file=sys.stderr)
        print("Another telemetry app may be holding the port, or the port is wrong.", file=sys.stderr)
        return 1

    print(f"Listening for FH6 Data Out on {args.ip}:{args.port}  (Ctrl+C to stop)")
    print("Enable: FH6 > Settings > HUD and Gameplay > Data Out = On, IP 127.0.0.1, "
          f"Port {args.port}\n")

    recorder = ContinuousRecorder(Path(args.out)) if args.all else RaceRecorder(Path(args.out))
    announced_len = False
    frames = 0

    sock.settimeout(1.0)   # so Ctrl+C is honored even when the game stops sending
    quiet = 0.0
    try:
        while True:
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                quiet += 1.0
                if quiet in (10.0, 30.0, 60.0):
                    print(f"\n  no packets for {quiet:.0f}s -- check: game in gameplay? Data Out On,"
                          f" 127.0.0.1:{args.port}? another listener holding the port?")
                continue
            quiet = 0.0
            if not announced_len:
                base = _dash_base(len(data), args.dash_offset)
                print(f"First packet: {len(data)} bytes  ->  dash base offset {base}")
                if len(data) < 324:
                    print("  WARNING: packet smaller than expected 324B; position may be absent.")
                announced_len = True

            frame = parse_packet(data, args.dash_offset)
            if frame is None:
                continue
            frames += 1
            recorder.feed(frame)

            if frames % 6 == 0:  # ~throttle console to keep it readable
                tag = "RACE" if frame.is_race_on else "menu"
                sys.stdout.write(
                    f"\r[{tag}] lap {frame.lap_no:>2} t={frame.cur_lap_time:6.2f}s  "
                    f"pos=({frame.pos_x:8.1f},{frame.pos_y:7.1f},{frame.pos_z:8.1f})  "
                    f"{frame.speed_kmh:6.1f} km/h  yaw={frame.yaw:+.3f}  "
                    f"gear {frame.gear}  thr {frame.accel:3d} brk {frame.brake:3d}   "
                )
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        recorder.close()
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
