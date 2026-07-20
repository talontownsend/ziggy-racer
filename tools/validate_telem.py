"""Quick live validation of the upgraded telemetry fields. Listens on UDP 7777,
parses with the new parse_packet, and prints the grip/slip signals so we can confirm
they respond correctly (≈0 at rest, spike under throttle/cornering) before recording
50 laps. Runs ~35 s then prints a min/max summary."""
import socket, sys, time
sys.path.insert(0, r"C:\Users\talon\FH6-AFK-Farm")
from fh6_telemetry import parse_packet

DUR = 35
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.bind(("0.0.0.0", 7777))
except OSError as e:
    print(f"BIND FAILED on 7777 ({e}) -- is the follower still running and holding the port?", flush=True)
    sys.exit(1)
sock.settimeout(1.0)
print("listening on 7777 ... drive: sit still, then blip throttle, then crank the wheel", flush=True)

stats, npkt, drivetrain, last = {}, 0, None, 0.0
def upd(n, v):
    s = stats.setdefault(n, [v, v]); s[0] = min(s[0], v); s[1] = max(s[1], v)

t0 = time.time()
while time.time() - t0 < DUR:
    try:
        data = sock.recvfrom(2048)[0]
    except socket.timeout:
        print("  ...no packets (is FH6 Data Out ON, 127.0.0.1, port 7777, and in the race?)", flush=True)
        continue
    f = parse_packet(data)
    if f is None:
        continue
    npkt += 1; drivetrain = f.drivetrain
    spd = f.speed_mps * 3.6
    latg, longg = f.ax / 9.81, f.az / 9.81
    cs = max(abs(f.combined_slip_fl), abs(f.combined_slip_fr), abs(f.combined_slip_rl), abs(f.combined_slip_rr))
    sr = max(abs(f.slip_ratio_fl), abs(f.slip_ratio_fr), abs(f.slip_ratio_rl), abs(f.slip_ratio_rr))
    sa = max(abs(f.slip_angle_fl), abs(f.slip_angle_fr), abs(f.slip_angle_rl), abs(f.slip_angle_rr)) * 57.3
    for n, v in (("speed_kmh", spd), ("lat_g", latg), ("long_g", longg),
                 ("combined_slip", cs), ("slip_ratio", sr), ("slip_angle_deg", sa)):
        upd(n, v)
    now = time.time()
    if now - last > 0.5:
        last = now
        print(f"spd{spd:5.0f}  latG{latg:+5.2f}  longG{longg:+5.2f}  combSlip{cs:5.2f}  "
              f"slipRatio{sr:5.2f}  slipAng{sa:5.1f}", flush=True)

print(f"\n--- {npkt} packets parsed | drivetrain={drivetrain} (0=FWD 1=RWD 2=AWD) ---", flush=True)
for n, (lo, hi) in stats.items():
    print(f"  {n:16s} min {lo:+8.2f}   max {hi:+8.2f}", flush=True)
ok = ("lat_g" in stats and stats["lat_g"][1] - stats["lat_g"][0] > 0.3 and
      "combined_slip" in stats and stats["combined_slip"][1] > 0.1)
print(f"\nVERDICT: {'fields RESPOND -> offsets look correct' if ok else 'fields look flat -- offsets may be wrong or you did not load the car'}", flush=True)
