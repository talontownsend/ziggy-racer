import numpy as np, csv, sys
sys.path.insert(0,r"C:/Users/talon/FH6-AFK-Farm")
from racing_line import menger_curvature
plan=np.load(r"C:/Users/talon/FH6-AFK-Farm/recordings/session_20260621_093038_plan.npz")
line=plan["line"];N=len(line);kappa=menger_curvature(line);radius=np.where(kappa>1e-9,1/kappa,1e9)
rows=list(csv.DictReader(open(r"C:/Users/talon/FH6-AFK-Farm/recordings/follow_log.csv")))
g=lambda n,tp=float:np.array([tp(d[n]) for d in rows])
t=g("t");i0=g("i0",int);spd=g("spd_kmh");alpha=g("alpha_deg");cte=g("cte_m");steer=g("steer")
spd_mps=spd/3.6
mask=(t-t[0])>=15.0
sr=radius[np.clip(i0,0,N-1)];pk=kappa[np.clip(i0,0,N-1)]
CO=mask&(sr<80)
Ld=np.clip(4+0.2*spd_mps,4,40)

# Pure-pursuit geometry: aiming Ld ahead at a point ON the line, the achievable path
# curvature is kappa_pp = 2*sin(alpha)/Ld. The chord Ld spans the gap to the target.
# When Ld (6.3m) << corner radius (36m), the lookahead point sits only ~6m ahead, the
# subtended angle alpha is small, so kappa_pp is modest UNLESS cte is large.
# Decompose commanded steer into the two analytic terms (pre-clip) at corner samples:
STEER_SIGN=-1;sg=1.2;kc=2.8
ar=np.deg2rad(alpha)
pursuit=STEER_SIGN*sg*ar
xtrack=STEER_SIGN*np.arctan2(kc*cte,spd_mps+3)
cmd=pursuit+xtrack
print("=== corner steer decomposition (signed, controller frame) ===")
print(f"pursuit term  mean={pursuit[CO].mean():+.3f}  |.|={np.abs(pursuit[CO]).mean():.3f}")
print(f"xtrack  term  mean={xtrack[CO].mean():+.3f}  |.|={np.abs(xtrack[CO]).mean():.3f}")
print(f"reconstructed cmd mean={cmd[CO].mean():+.3f}; logged steer mean={steer[CO].mean():+.3f}")
print(f"corr(reconstructed,logged) corner={np.corrcoef(cmd[CO],steer[CO])[0,1]:+.3f}")
print(f"pursuit share of |steer|: {np.abs(pursuit[CO]).mean()/(np.abs(pursuit[CO]).mean()+np.abs(xtrack[CO]).mean()):.2f}")

# How big is xtrack saturated by atan? max possible xtrack term = atan2 -> bounded by pi/2 (~1.57 rad)
# at corner speed v~11.4, +3 =>14.4. For cte=1m: atan2(2.8,14.4)=0.19rad. So xtrack term tiny per meter.
v=spd_mps[CO].mean()
for ctev in [0.5,1,2,3]:
    print(f"  xtrack term at cte={ctev}m, v={v:.1f}: {np.arctan2(kc*ctev,v+3):.3f} rad ({np.degrees(np.arctan2(kc*ctev,v+3)):.1f} deg-equiv)")
print(f"  => cross-track authority is weak at speed: even 3m wide only adds {np.degrees(np.arctan2(kc*3,v+3)):.0f}deg of correction demand")

# steer units: is steer in [-1,1] a normalized angle? estimate effective max steer angle by matching
# achieved kappa to steer via bicycle model kappa=tan(delta)/L. We don't know L, but ratio test:
# achieved kappa vs steer linear fit
import numpy as np
# rough achieved kappa from earlier ~0.017 at steer~0.23 in corners
print("\n=== mechanism summary numbers ===")
print(f"corner: plan R={1/pk[CO].mean():.0f}m, Ld={Ld[CO].mean():.1f}m, Ld/R={Ld[CO].mean()*pk[CO].mean():.2f}")
print(f"corner mean speed={spd[CO].mean():.0f}km/h, alpha mean={alpha[CO].mean():+.1f}deg, signed cte mean={cte[CO].mean():+.2f}m")
print(f"frac corner wide(cte<0)={np.mean(cte[CO]<0):.2f}, |steer| max={np.abs(steer[CO]).max():.2f} (no saturation)")
