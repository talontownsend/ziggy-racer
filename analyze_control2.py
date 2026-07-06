import numpy as np, csv, sys
sys.path.insert(0, r"C:/Users/talon/FH6-AFK-Farm")
from racing_line import menger_curvature

plan = np.load(r"C:/Users/talon/FH6-AFK-Farm/recordings/session_20260621_093038_plan.npz")
line = plan["line"]; N=len(line)
kappa = menger_curvature(line)
radius = np.where(kappa>1e-9,1.0/kappa,1e9)

rows=list(csv.DictReader(open(r"C:/Users/talon/FH6-AFK-Farm/recordings/follow_log.csv")))
g=lambda n,tp=float: np.array([tp(d[n]) for d in rows])
t=g("t");i0=g("i0",int);spd=g("spd_kmh");alpha=g("alpha_deg");cte=g("cte_m");steer=g("steer")
mask=(t-t[0])>=15.0
sr=radius[np.clip(i0,0,N-1)]
ST=mask&(sr>200);CO=mask&(sr<80)
spd_mps=spd/3.6

# Straight: is |cte| a steady one-sided offset or a slow wander crossing 0?
# Break straights into contiguous runs, look at per-run mean cte and how often cte stays one sign within a run.
print("=== STRAIGHT structure ===")
c=cte[ST]
print(f"cte percentiles 5/25/50/75/95: {np.percentile(c,[5,25,50,75,95]).round(2)}")
print(f"frac time |cte|>1m on straights: {np.mean(np.abs(c)>1.0):.2f}")
print(f"frac cte>0: {np.mean(c>0):.2f}  frac cte<0: {np.mean(c<0):.2f}")
# how many zero-crossings overall in the straight cte series (time-ordered subset)
ci=cte[ST]; zc=np.sum(np.sign(ci[1:])!=np.sign(ci[:-1]))
print(f"cte zero-crossings in straight series={zc} over {ST.sum()} samples ({100*zc/ST.sum():.2f}/100)")

# dominant period: count steer sign changes => weave half-cycles; dt
dt=np.median(np.diff(t))
print(f"median dt={dt*1000:.1f} ms => ~{1/dt:.0f} Hz")

# CORNER: does the car under-rotate? compare achieved path curvature to plan curvature.
# achieved curvature ~ yawrate/speed. Use head_deg change.
head=g("head_deg")
# unwrap heading
hu=np.deg2rad(head); hu=np.unwrap(hu)
dpsi=np.gradient(hu,t)            # rad/s yaw rate
achieved_kappa=np.abs(dpsi)/np.maximum(spd_mps,1.0)
ak=achieved_kappa; pk=kappa[np.clip(i0,0,N-1)]
print("\n=== CORNER curvature (achieved vs plan) ===")
print(f"plan kappa mean (corner)={pk[CO].mean():.4f} 1/m  -> R={1/pk[CO].mean():.1f} m")
print(f"achieved kappa mean(corner)={ak[CO].mean():.4f} 1/m -> R={1/max(ak[CO].mean(),1e-6):.1f} m")
print(f"achieved/plan curvature ratio (median)={np.median(ak[CO]/np.maximum(pk[CO],1e-6)):.2f}")
print(f"frac corner samples achieved<plan (under-turn)={np.mean(ak[CO]<pk[CO]):.2f}")

# steer headroom in corners: how far from full lock
print(f"\ncorner steer: mean={steer[CO].mean():+.3f} max|={np.abs(steer[CO]).max():.3f} p95|steer|={np.percentile(np.abs(steer[CO]),95):.3f}")
print(f"frac |steer|>0.7={np.mean(np.abs(steer[CO])>0.7):.3f}  >0.5={np.mean(np.abs(steer[CO])>0.5):.3f}")

# At the cte<0 (wide) corner samples, what is steer doing? is it commanding more inside?
wide=CO&(cte<0)
print(f"\nwide corner samples (cte<0): n={wide.sum()} mean cte={cte[wide].mean():.2f} mean steer={steer[wide].mean():+.3f} mean |steer|={np.abs(steer[wide]).mean():.3f}")
print(f"   their alpha mean={alpha[wide].mean():+.2f} deg (heading error to lookahead)")

# Compare: required steady-state steer angle to hold radius R at lookahead vs commanded.
# pure-pursuit ideal curvature = 2*sin(alpha)/Ld. Check if pursuit law even asks for plan curvature.
Ld=np.clip(4+0.2*spd_mps,4,40)
pp_kappa=2*np.sin(np.deg2rad(alpha))/Ld
print(f"\npursuit-implied curvature 2sin(a)/Ld mean(corner)={np.abs(pp_kappa[CO]).mean():.4f} 1/m -> R={1/max(np.abs(pp_kappa[CO]).mean(),1e-6):.1f} m")
print(f"  vs plan R={1/pk[CO].mean():.1f} m. Ld mean={Ld[CO].mean():.1f}m, plan R mean={1/pk[CO].mean():.1f}m")
