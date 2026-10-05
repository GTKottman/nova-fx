"""Seconds-long checks of the C core: correctness + throughput. Run: python3 tests/test_core.py"""
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from _core import core

def test_tables():
    t = core.tables()
    assert "death_pattern" in t["kind"].index and "vorticity" in t["fluid"].index
    rgb = core.blackbody(1500); assert rgb[0] == max(rgb) and rgb[2] < 0.2, rgb
    rgb = core.blackbody(6500); assert min(rgb) > 0.8, rgb
    print("tables ok; 1500K", np.round(core.blackbody(1500), 3), "6500K", np.round(core.blackbody(6500), 3))

def test_particles_throughput():
    s = core.System(); s.set_params(dict(turb_amp=3.0, max_particles=3_000_000))
    s.set_kinds([dict(life_min=5, life_max=6, drag_quad=0.1, turb=1.0)])
    n = 1_000_000
    rng = np.random.default_rng(0)
    s.emit(0, rng.normal(size=(n, 3)), rng.normal(size=(n, 3)) * 5)
    s.frame(1/24, 1)  # warm
    t = time.perf_counter(); s.frame(1/24, 4); dt = time.perf_counter() - t
    print(f"1M particles, 4 substeps w/ curl noise: {dt*1000:.1f} ms/frame ({n*4/dt/1e6:.0f} M particle-steps/s)")
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "nv_test.bin")
    t = time.perf_counter(); w = s.write(path); dtw = time.perf_counter() - t
    d = core.read_cache(path); os.remove(path)
    assert d["n"] == n == w
    print(f"cache write {dtw*1000:.1f} ms, {n*35/1e6:.0f} MB")

def test_events_deterministic():
    def run(threads):
        core.lib().nv_set_threads(threads)
        s = core.System(); s.set_params(dict(seed=3))
        s.set_kinds([
            dict(life_min=1, life_max=1, death_kind=1, death_count=200, death_pattern=0, death_speed=20, trail_kind=2, trail_rate=50),
            dict(life_min=0.5, life_max=1.0, split_kind=1, split_rate=2, split_count=3, split_max_gen=3),
            dict(life_min=0.2, life_max=0.3),
        ])
        s.emit(0, np.zeros((5, 3)), np.tile([0, 0, 30], (5, 1)))
        counts = []
        for f in range(48):
            s.frame(1/24, 2); counts.append(s.count())
        P, *_ = s.export()
        return counts, P
    c1, p1 = run(1); c16, p16 = run(os.cpu_count())
    assert c1 == c16 and np.array_equal(p1, p16), "thread count changed the result"
    print("events deterministic across thread counts; counts", c1[20:26], "peak", max(c1))

def test_collision_ground():
    s = core.System()
    s.set_kinds([dict(life_min=10, life_max=10, bounce=0.5, friction=0.1)])
    m = np.eye(4, dtype=np.float32)[:3].ravel()
    s.set_colliders([[0, *m, *m, 0, 0, 0, 0, 0, 0]])
    s.emit(0, [[0, 0, 5]], [[1, 0, 0]])
    zs = []
    for f in range(96):
        s.frame(1/24, 4); zs.append(s.export()[0][0, 2])
    assert min(zs) >= -1e-3, min(zs)
    print("ground collision ok, min z", round(min(zs), 4))

def test_fluid():
    res = (64, 64, 96)
    f = core.Fluid(res, 0.05, (-1.6, -1.6, 0))
    f.set_params(dict(vorticity=0.4))
    times = []
    for i in range(30):
        f.splat([[0, 0, 0.3]], 0.25, dens=1, heat=1.5, fuel=1.0, mode=1)
        t = time.perf_counter(); f.step(1/24); times.append(time.perf_counter() - t)
    s = core.System(); st = s.stats(f)
    div = f.max_divergence()
    d = f.field(0); T = f.field(1)
    print(f"fluid {res}: {np.median(times)*1000:.0f} ms/frame, cg iters {st['cg_iters']}, rel res {st['cg_res']:.1e}, "
          f"max|div| {div:.3f}/s, maxvel {st['max_vel']:.2f}, smoke top z-cell {np.nonzero(d.max(axis=(1,2))>0.05)[0].max()}")
    assert st["cg_iters"] < 60 and np.isfinite(d).all() and T.max() > 0

def test_fluid_big():
    res = (128, 128, 192)
    f = core.Fluid(res, 0.025, (-1.6, -1.6, 0))
    for i in range(6):
        f.splat([[0, 0, 0.3]], 0.25, dens=1, heat=1.5, fuel=1.0, mode=1)
        t = time.perf_counter(); f.step(1/24); dt = time.perf_counter() - t
    st = core.System().stats(f)
    print(f"fluid {res} ({np.prod(res)/1e6:.1f}M cells): {dt*1000:.0f} ms/frame, cg iters {st['cg_iters']}")


def test_sdf_collider_voxelizes_like_sphere():
    import ctypes as C
    L = core.lib()
    L.nv_fluid_solid_ptr.restype = C.POINTER(C.c_uint8); L.nv_fluid_solid_ptr.argtypes = [C.c_void_p]
    I = np.eye(4, dtype=np.float32)[:3].ravel()
    counts = []
    for kind in ("sphere", "sdf"):
        f = core.Fluid((40, 40, 40), 0.05, (-1, -1, -1)); s = core.System(); s.set_fluid(f)
        if kind == "sdf":
            n = 33; dx = 1.2 * 2 / (n - 1); g = np.linspace(-1.2, 1.2, n)
            Z, Y, X = np.meshgrid(g, g, g, indexing="ij")
            s.set_sdf(0, (-1.2, -1.2, -1.2), dx, np.sqrt(X**2 + Y**2 + Z**2) - 0.6)
            s.set_colliders([[3, *I, *I, 0, 0, 0, 0, 0, 0]])
        else:
            s.set_colliders([[1, *I, *I, 0.6, 0, 0, 0, 0, 0]])
        s.frame(1/24, 1, f)
        counts.append(int(np.ctypeslib.as_array(L.nv_fluid_solid_ptr(f.h), shape=(40**3,)).sum()))
    exact = 4 / 3 * np.pi * 0.6**3 / 0.05**3
    print(f"solid cells: analytic sphere {counts[0]}, SDF sphere {counts[1]} (volume says {exact:.0f})")
    assert abs(counts[0] - counts[1]) < 0.03 * counts[0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and (len(sys.argv) < 2 or name in sys.argv[1:]):
            fn()
