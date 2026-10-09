"""Run inside Blender (background): fire upres end to end, from the preset to the VDB files.
blender -b --factory-startup --python tests/blender_upres.py [-- --render DIR]"""
import os, sys, tempfile, time

import addon_utils
import bpy
import numpy as np

mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = sys.modules[mod + ".sim"]
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 48
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


bpy.ops.nova.add_preset(preset="CAMPFIRE", setup_scene=bool(argv))
so = bpy.context.object
so.nova.live = False
fl = so.nova.fluid
fl.resolution = 48
work = tempfile.mkdtemp(prefix="nova_upres_")


def bake(factor, frames=40):
    fl.upres = factor
    so.nova.cache_dir = os.path.join(work, f"x{factor}") + "/"
    sim._RT.pop(so.name, None)
    t = time.perf_counter()
    for f in range(1, frames + 1):
        sc.frame_set(f)
        rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=True)
    sim.wait_vdb(so)
    return rt, time.perf_counter() - t


def read(path):
    import openvdb as vdb
    grids = {g.name: g for g in vdb.readAll(path)[0]}
    d = grids["density"]
    lo, hi = d.evalActiveVoxelBoundingBox()
    shape = tuple(int(h - l + 1) for l, h in zip(lo, hi))
    arr = np.zeros(shape, np.float32)
    d.copyToArray(arr, ijk=lo)
    return d.transform.voxelSize()[0], arr, lo


rt1, t1 = bake(1)
st1 = dict(rt1.stats)
rt2, t2 = bake(2)
st2 = dict(rt2.stats)
check("Upres 2x" in st2.get("upres", ""), f"stats: {st2.get('upres')}")
v1, a1, lo1 = read(sim.volume_path(so, 40).replace("x2", "x1"))
v2, a2, lo2 = read(sim.volume_path(so, 40))
check(abs(v2 - v1 / 2) < 1e-6, f"voxels {v1 * 100:.2f} cm -> {v2 * 100:.2f} cm")
m1, m2 = a1.sum() * v1 ** 3, a2.sum() * v2 ** 3
check(abs(m2 - m1) / m1 < 0.05, f"same smoke in total: {m1:.4f} vs {m2:.4f} m³·density")
g1 = np.abs(np.diff(a1, axis=0)).sum() * v1 ** 2  # total variation per area: grows with fine structure
g2 = np.abs(np.diff(a2, axis=0)).sum() * v2 ** 2
check(g2 > 1.3 * g1, f"more detail: total variation {g2 / g1:.2f}x")
print(f"bake 40 frames: {t1:.1f} s without upres, {t2:.1f} s with 2x")

if argv and argv[0] == "--render":
    out = argv[1]
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 32
    sc.render.resolution_x, sc.render.resolution_y = 480, 640
    for factor in (1, 2):
        so.nova.cache_dir = os.path.join(work, f"x{factor}") + "/"
        sc.frame_set(40)
        sim.ensure_volume_object(sc, so)
        sim.refresh_volume(so)
        sc.render.filepath = os.path.join(out, f"campfire_x{factor}.png")
        bpy.ops.render.render(write_still=True)
        print("rendered", sc.render.filepath)

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
