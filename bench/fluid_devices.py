"""CPU sparse vs CPU dense vs GPU, wall time per frame (best of 3 runs). Run on an idle machine.
python3 bench/fluid_devices.py"""
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
from _core import core

def run(mode, shape, dx, sources, frames=16, warm=8):
    f = core.Fluid(shape, dx, (-shape[0] * dx / 2, -shape[1] * dx / 2, 0))
    f.set_params(dict(max_sub=2, vorticity=0.5, sparse=1 if mode == "cpu-sparse" else 0, expansion=1.0))
    s = core.System(); s.set_fluid(f)
    if mode == "gpu" and not f.use_gpu(True):
        s.free(); f.free(); return None, None
    ts = []
    for fr in range(frames):
        f.splat(sources, 0.25, dens=1, heat=1.5, fuel=1.2, mode=1)
        t = time.perf_counter(); s.frame(1 / 24, 1, f); ts.append(time.perf_counter() - t)
    act = s.stats(f)["active"]
    s.free(); f.free()
    return float(np.median(ts[warm:])) * 1000, act

def best(*a, **k):
    out = [run(*a, **k) for _ in range(3)]
    ms = [o[0] for o in out if o[0] is not None]
    return (min(ms) if ms else None), out[0][1]

print(f"machine load: {os.getloadavg()[0]:.1f}", flush=True)
print("\n## Small plume, growing empty domain (dx = 3 cm)")
for n in (64, 96, 128, 160, 192):
    shape = (n, n, int(n * 1.5))
    r = {m: best(m, shape, 0.03, [[0, 0, 0.3]]) for m in ("cpu-sparse", "cpu-dense", "gpu")}
    print(f"{shape} {np.prod(shape)/1e6:5.1f}M cells ({r['cpu-sparse'][1]*100:3.0f}% active): "
          + "  ".join(f"{m} {v[0]:7.1f} ms" if v[0] else f"{m} n/a" for m, v in r.items()), flush=True)
print("\n## Busy domain: a wide fire fills most of it")
for n in (64, 96, 128, 160):
    shape = (n, n, int(n * 1.5)); dx = 2.4 / n
    src = [[x, y, 0.3] for x in np.linspace(-0.8, 0.8, 5) for y in np.linspace(-0.8, 0.8, 5)]
    r = {m: best(m, shape, dx, src) for m in ("cpu-sparse", "cpu-dense", "gpu")}
    print(f"{shape} {np.prod(shape)/1e6:5.1f}M cells ({r['cpu-sparse'][1]*100:3.0f}% active): "
          + "  ".join(f"{m} {v[0]:7.1f} ms" if v[0] else f"{m} n/a" for m, v in r.items()), flush=True)
print(f"\nmachine load at end: {os.getloadavg()[0]:.1f}")
