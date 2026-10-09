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


def test_turbulence_grid():
    """Baked turbulence must match direct curl noise closely, and auto mode must only kick in when it pays."""
    L = core.lib()
    def field(mode, n, spread=5.0):
        s = core.System(); s.set_params(dict(turb_amp=1.0, turb_freq=0.5, turb_octaves=2, gz=0, turb_speed=0))
        s.set_kinds([dict(life_min=100, life_max=100, gravity=0)]); L.nv_sys_set_turb_grid(s.h, mode)
        rng = np.random.default_rng(1); s.emit(0, rng.uniform(-spread, spread, (n, 3)), np.zeros((n, 3)))
        s.frame(1e-3, 1); used = L.nv_sys_turb_grid_used(s.h); a = s.export()[1] / 1e-3; s.free()
        return a, used
    a, _ = field(-1, 200_000); b, used = field(1, 200_000)
    err = np.sqrt(((a - b) ** 2).sum(1).mean() / (a ** 2).sum(1).mean())
    _, small = field(0, 20_000)          # grid would be bigger than the particle count: stay direct
    _, big = field(0, 1_000_000)         # grid is tiny next to 1M particles: bake
    print(f"turbulence grid: {err*100:.2f}% RMS vs direct; auto off at 20k particles: {not small}, on at 1M: {bool(big)}")
    assert used and err < 0.06 and not small and big


def test_gpu_solver_matches_cpu():
    """Whole fluid solver on the GPU (Vulkan) vs the CPU solver: combustion, vorticity, turbulence,
    a collider, velocity sources, MGPCG. Skipped on machines without a Vulkan GPU."""
    probe = core.Fluid((8, 8, 8), 0.1, (0, 0, 0))
    if not probe.use_gpu(True):
        print("gpu: skipped,", core.gpu_name()); probe.free(); return
    probe.free()
    def run(gpu, frames):
        n = 40
        f = core.Fluid((n, n, 60), 0.06, (-1.2, -1.2, 0))
        f.set_params(dict(sparse=0, vorticity=0.5, turb_amp=4.0, turb_freq=3.0, max_sub=2))
        s = core.System(); s.set_fluid(f)
        if gpu: f.use_gpu(True)
        m = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -2.2]], np.float32).ravel()
        mi = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 2.2]], np.float32).ravel()
        s.set_colliders([[1, *m, *mi, 0.35, 0, 0, 0, 0, 0]])
        for fr in range(frames):
            f.splat([[0, 0, 0.3]], 0.2, dens=1, heat=1.5, fuel=1, vel=[[0, 0, 1]], vel_amt=0.5, mode=1)
            s.frame(1 / 24, 1, f)
        f.sync(True)
        out = np.stack([f.field(i).copy() for i in range(4)]); s.free(); f.free(); return out
    a, b = run(False, 1), run(True, 1)
    err = np.abs(a - b).max() / np.abs(a).max()
    print(f"gpu ({core.gpu_name()}): 1 frame, max difference {err*100:.4f}% of peak")
    assert err < 1e-4  # the kernels compute the same thing
    # later frames: rounding differences are amplified wherever a cell sits right at the ignition
    # threshold (fuel burns on one device, not yet on the other), so count outlier cells, not the max
    a, b = run(False, 8), run(True, 8)
    off = np.abs(a - b) > 0.005 * np.abs(a).max()
    print(f"gpu: 8 frames, {off.mean()*100:.4f}% of cells differ by more than 0.5% of peak "
          f"(median difference {np.median(np.abs(a - b)):.1e})")
    assert off.mean() < 1e-4


def test_gpu_sparse_matches_cpu():
    """Sparse GPU solver (every kernel runs over the active tiles only) vs the sparse CPU solver. The source
    slides across the domain and everything fades fast behind it, so tiles join the region at the front and
    leave it at the back: the GPU content scan, incremental stencil uploads and the clearing of tiles that
    left all run. The pressure solve is converged tightly: at the default tolerance (1e-3) the two devices
    stop it at slightly different points and velocities differ by ~1e-4 of peak, dense or sparse.
    Skipped without a Vulkan GPU."""
    probe = core.Fluid((8, 8, 8), 0.1, (0, 0, 0))
    if not probe.use_gpu(True):
        print("gpu sparse: skipped,", core.gpu_name()); probe.free(); return
    probe.free()
    def run(gpu, frames):
        f = core.Fluid((48, 48, 64), 0.05, (-1.2, -1.2, 0))
        k = 60.0  # fades below the tile threshold within ~4 frames
        f.set_params(dict(sparse=1, vorticity=0.5, turb_amp=4.0, turb_freq=3.0, max_sub=2, smoke_decay=k, cool=k,
                          fuel_decay=k, flame_decay=k, cg_tol=1e-6, cg_iter=200))
        s = core.System(); s.set_fluid(f)
        if gpu: f.use_gpu(True)
        m = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, -1.6]], np.float32).ravel()
        mi = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 1.6]], np.float32).ravel()
        s.set_colliders([[1, *m, *mi, 0.3, 0, 0, 0, 0, 0]])
        region = []
        for fr in range(frames):
            f.splat([[-0.9 + 0.12 * fr, 0, 0.3]], 0.2, dens=1, heat=1.5, fuel=1, vel=[[0, 0, 1]], vel_amt=0.5, mode=1)
            s.frame(1 / 24, 1, f)
            region.append((s.stats(f)["active"], f.active_bbox()))
        f.sync(True)
        out = np.stack([f.field(i).copy() for i in range(4)]), f.cell_velocity()
        s.free(); f.free()
        return out, region
    (a, av), _ = run(False, 1)
    (b, bv), _ = run(True, 1)
    err = max(np.abs(a - b).max() / np.abs(a).max(), np.abs(av - bv).max() / np.abs(av).max())
    print(f"gpu sparse: 1 frame, max difference {err*100:.5f}% of peak")
    assert err < 1e-5  # the kernels compute the same thing
    (a, av), reg = run(False, 16)
    (b, bv), reg_gpu = run(True, 16)
    assert reg == reg_gpu, (reg, reg_gpu)  # the same tiles every frame
    act, i0 = [r[0] for r in reg], [r[1][0] for r in reg]
    assert max(act) <= 0.5 and i0[-1] > i0[0], reg  # sparse, and tiles left the region behind the source
    off = np.abs(a - b) > 0.005 * np.abs(a).max()
    offv = np.abs(av - bv) > 0.005 * np.abs(av).max()
    print(f"gpu sparse: 16 frames, active tiles {min(act)*100:.0f}-{max(act)*100:.0f}%, region start x {i0[0]} -> {i0[-1]}, "
          f"{off.mean()*100:.4f}% of scalar and {offv.mean()*100:.4f}% of velocity cells differ by more than 0.5% of peak")
    assert off.mean() < 1e-4 and offv.mean() < 1e-4
    (c, cv), _ = run(True, 16)
    assert np.array_equal(b, c) and np.array_equal(bv, cv)  # run to run: bit-identical


def test_lightning():
    """Dielectric-breakdown bolt: deterministic per seed, reaches the ground (or the target) in every seed,
    branches, and grows in milliseconds."""
    import ctypes as C
    L = core.lib()
    def grow(seed, target=None, h=45 / 130, eta=12.0, field=0.3):
        t = target or (0, 0, 0)
        p = np.array([0, 0, 45, 0, h, eta, field, seed, 1 if target else 0, *t], np.float32)
        pos = np.zeros(3 * 20000, np.float32); par = np.zeros(20000, np.int32)
        t0 = time.perf_counter()
        n = L.nv_lightning(core.fptr(p), 20000, core.fptr(pos), par.ctypes.data_as(C.POINTER(C.c_int)))
        return pos[:3 * abs(n)].reshape(-1, 3), par[:abs(n)], n > 0, time.perf_counter() - t0
    grow(0)  # warm up the thread pool
    a, pa, ok, _ = grow(7); b, pb, _, _ = grow(7); c, _, _, _ = grow(8)
    assert ok and np.array_equal(a, b) and np.array_equal(pa, pb) and not np.array_equal(a[:len(c)], c[:len(a)])
    hits, ms, kids = 0, [], []
    for seed in range(1, 11):
        P, par, ok, dt = grow(seed)
        hits += ok; ms.append(dt * 1000)
        assert P[-1, 2] == 0 and (par[1:] < np.arange(1, len(par))).all()  # ends on the ground; parents first
        kids.append(np.bincount(par[1:], minlength=len(par)).max())
    assert hits == 10 and min(kids) >= 2, (hits, kids)  # every seed strikes, every bolt forks
    P, par, ok, _ = grow(3, target=(12, -5, 8))
    assert ok and np.allclose(P[-1], (12, -5, 8))  # a strike target is hit exactly
    print(f"lightning: 10/10 seeds strike, {int(np.median([len(grow(s)[0]) for s in range(1, 11)]))} steps, "
          f"median {np.median(ms):.0f} ms, max {max(ms):.0f} ms; target hit")
    assert np.median(ms) < 200


def _nearest(P, pts):
    return np.sqrt(((P[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).min(1)


def test_form_force():
    rng = np.random.default_rng(4)
    pts = rng.normal(size=(200, 3)).astype(np.float32) * [3, 0.1, 1]  # a flat "logo" floating at z = 6
    pts[:, 2] += 6
    s = core.System()
    s.set_params(dict(turb_amp=4.0))                                   # gravity and turbulence on
    s.set_kinds([dict(life_min=100, life_max=100, drag_lin=0.5, collide=0)])
    assert s.set_shape(0, pts) == 1
    s.set_forces([[5, 0, 0, 0, 0, 0, 1, 1.0, 0, 4.0, 1.0, 0]])         # pull 1, snap 4, damping 1
    s.emit(0, rng.normal(size=(3000, 3)) * 8, np.zeros((3000, 3)))
    for _ in range(96):
        s.frame(1 / 24, 2)
    d = _nearest(s.export()[0], pts)
    assert d.max() < 1e-3, d.max()
    s.set_forces([[5, 0, 0, 0, 0, 0, 1, 0.5, 0, 4.0, 1.0, 0]])         # half pull: gravity sags them
    for _ in range(48):
        s.frame(1 / 24, 2)
    sag = np.median(_nearest(s.export()[0], pts))
    s.set_forces([[5, 0, 0, 0, 0, 0, 1, 0.0, 0, 4.0, 1.0, 0]])         # released: they fall
    for _ in range(24):
        s.frame(1 / 24, 2)
    z = s.export()[0][:, 2].mean()
    assert sag > 0.05 and z < 5.0, (sag, z)
    print(f"form: 3000 particles on 200 points within {d.max() * 1e3:.2f} mm under gravity + turbulence; "
          f"half pull sags {sag:.2f} m; released they fall (mean z {z:.1f})")


def test_shape_burst():
    rng = np.random.default_rng(5)
    unit = rng.normal(size=(500, 3)).astype(np.float32)
    unit /= np.linalg.norm(unit, axis=1).max()
    s = core.System()
    s.set_params(dict(gz=0.0))
    # shell -> 400 stars in the shape; size = speed / linear drag = 12 / 3 = 4 m
    s.set_kinds([dict(life_min=0.5, life_max=0.5, death_kind=1, death_count=400, death_pattern=8,
                      death_shape=0, death_speed=12, death_speed_var=0, death_inherit=0, collide=0),
                 dict(life_min=20, life_max=20, drag_lin=3.0, collide=0)])
    s.set_shape(0, unit)
    s.emit(0, [[0, 0, 10]], [[0, 0, 0]])
    for _ in range(96):
        s.frame(1 / 24, 4)
    P = s.export()[0] - [0, 0, 10]
    # stepping linear drag shrinks every path by the same factor (~1.6% at 4 substeps): the shape is exact,
    # its size within a few percent of speed / drag
    scale = np.linalg.norm(P, axis=1).max()
    d = _nearest(P / scale, unit)
    assert len(P) == 400 and d.max() < 1e-4 and abs(scale - 4) < 0.1, (len(P), d.max(), scale)
    print(f"shape burst: 400 stars stop exactly in the shape (error {d.max() * 1e3:.3f} per mille), "
          f"{scale:.2f} m for speed/drag = 4 m")



def test_upres():
    """Fine detail that still averages to the fluid."""
    res = (48, 48, 72)
    f = core.Fluid(res, 0.05, (-1.2, -1.2, 0))
    f.set_params(dict(vorticity=0.4, turb_amp=2.0))
    up = core.Upres(f, 2)
    times = []
    for i in range(40):
        f.splat([[0, 0, 0.3]], 0.25, dens=1, heat=1.5, fuel=1.0, mode=1)
        f.step(1 / 24)
        up.step(1 / 24, strength=1.0, wavelength=2.0)
        times.append(up.ms())
    nx, ny, nz, i0, j0, k0 = up.box()
    assert i0 % 2 == 0 and nx % 2 == 0
    d = up.field(0)
    coarse = f.field(0)[k0 // 2:(k0 + nz) // 2, j0 // 2:(j0 + ny) // 2, i0 // 2:(i0 + nx) // 2]
    avg = d.reshape(nz // 2, 2, ny // 2, 2, nx // 2, 2).mean(axis=(1, 3, 5))
    err = np.abs(avg - coarse).max() / coarse.max()
    # detail: small-scale energy (fine minus its own 2x2x2 average) vs what plain upsampling would give (0)
    det = d - np.repeat(np.repeat(np.repeat(avg, 2, 0), 2, 1), 2, 2)
    grad_fine = np.abs(np.diff(d, axis=2)).mean()
    up_lin = np.repeat(np.repeat(np.repeat(coarse, 2, 0), 2, 1), 2, 2)
    grad_lin = np.abs(np.diff(up_lin, axis=2)).mean() / 2  # a trilinear upsample has about half the steps
    assert err < 0.08 and np.isfinite(d).all() and d.min() >= 0, err
    assert np.abs(det).mean() > 0.05 * coarse.mean() and grad_fine > 1.3 * grad_lin, (np.abs(det).mean(), grad_fine, grad_lin)
    print(f"upres 2x: box {nx}x{ny}x{nz} fine cells, coarse average within {err * 100:.1f}% of the fluid, "
          f"detail {grad_fine / grad_lin:.1f}x the gradients of plain upsampling, {np.median(times):.0f} ms/frame")



def _dam(threads=None, frames=96):
    if threads:
        core.lib().nv_set_threads(threads)
    f = core.Fluid((32, 12, 24), 0.05, (0, 0, 0))     # 1.6 x 0.6 x 1.2 m tank
    f.set_params(dict(liquid=1, flip=0.95, walls=1, closed_floor=1, cfl=1.0, max_sub=8))
    s = core.System()
    s.set_kinds([dict(liquid=1, life_min=1e6, life_max=1e6, collide=0)])
    s.set_fluid(f)
    # a 0.5 x 0.5 m column of water against the left wall, 8 particles per cell, jittered
    rng = np.random.default_rng(1)
    g = np.stack(np.meshgrid(np.arange(1, 11), np.arange(1, 11), np.arange(1, 11), indexing="ij"), -1).reshape(-1, 3)
    pts = (np.repeat(g, 8, 0) + rng.random((len(g) * 8, 3))) * 0.05
    s.emit(0, pts, np.zeros_like(pts))
    for _ in range(frames):
        s.frame(1 / 24, 1, f)
    return s, f, len(pts)


def test_liquid_dam_break():
    t = time.perf_counter()
    s, f, n0 = _dam(frames=120)
    ms = (time.perf_counter() - t) / 120 * 1000
    P, V, *_ = s.export()
    assert s.count() == n0 and np.isfinite(P).all()
    inside = (P[:, 0] > 0) & (P[:, 0] < 1.6) & (P[:, 1] > 0) & (P[:, 1] < 0.6) & (P[:, 2] > 0)
    assert inside.all()
    # settled: slow, and spread into a flat layer over the floor inside the walls (1.5 x 0.5 m)
    depth_expect = 0.5 * 0.5 * 0.5 / (1.5 * 0.5)
    top = np.percentile(P[:, 2], 99) - 0.05
    occ = len(np.unique((P / 0.05).astype(int), axis=0))
    speed = np.sqrt((V.astype(np.float64) ** 2).sum(1))
    print(f"liquid dam break: {n0} particles kept, settled depth {top:.3f} m (volume says {depth_expect:.3f}), "
          f"{occ} cells occupied vs {10 * 10 * 10} at the start, median speed {np.median(speed):.3f} m/s, "
          f"{ms:.0f} ms/frame")
    assert abs(top - depth_expect) < 0.06, top
    assert 0.75 < occ / 1000 < 1.35, occ
    assert np.median(speed) < 0.15
    # the pressure solve sums in parallel (like the gas solver), so runs repeat exactly per thread count
    a, _f, _n = _dam(os.cpu_count(), frames=24)
    b, _f2, _n2 = _dam(os.cpu_count(), frames=24)
    assert np.array_equal(a.export()[0], b.export()[0]), "the same run gave a different liquid"
    print("liquid repeats exactly run to run")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and (len(sys.argv) < 2 or name in sys.argv[1:]):
            fn()
