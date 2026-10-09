"""Run inside Blender (background): Shapes display, snow globe, rain chain.
blender -b --factory-startup --python tests/blender_weather.py"""
import sys, tempfile

import addon_utils
import bpy
import numpy as np

mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = sys.modules[mod + ".sim"]
core = sys.modules[mod + ".core"]
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 200
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


def system(key, frames):
    # a fresh scene each time: colliders and forces are scene-wide (the globe's floor would catch the rain)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable(mod, default_set=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 200
    bpy.ops.nova.add_preset(preset=key)
    so = bpy.context.object
    so.nova.live = False
    so.nova.cache_dir = tempfile.mkdtemp(prefix="nova_weather_") + "/"
    for f in range(1, frames + 1):
        sc.frame_set(f)
        rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=True)
    sim.load_frame(so, frames)
    return so, rt, sc


# Shapes: one instance per particle, of the type's own mesh
so, rt, sc = system("AUTUMN", 60)
sob = bpy.data.objects[so.name + " Shapes"]
dg = bpy.context.evaluated_depsgraph_get()
insts = [(i.object.data.name, np.array(i.matrix_world)) for i in dg.object_instances
         if i.is_instance and i.parent and i.parent.name == sob.name]  # copied: instance handles are transient
check(len(insts) == rt.sys.count() and all(nm.startswith("Nova Leaf") for nm, _m in insts[:20]),
      f"{len(insts)} leaf instances for {rt.sys.count()} leaves")
check(so.hide_render and not sob.hide_render, "the points leave the render to the shapes")

# tumbling stops when a leaf lands: its orientation depends on where it is, not on time
rot0 = {}
for f in range(61, 152):
    sc.frame_set(f)
    sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=True)
    if f >= 150:
        sim.load_frame(so, f)
        dg = bpy.context.evaluated_depsgraph_get()
        d = core.read_cache(sim.particle_path(so, f))
        landed = d["P"].reshape(-1, 3)[:, 2] < 0.02
        mats = [np.array(i.matrix_world) for i in dg.object_instances
                if i.is_instance and i.parent and i.parent.name == sob.name]
        rot0[f] = (np.array(mats), landed, d["id"].copy(), d["P"].reshape(-1, 3).copy())
(m0, l0, id0, p0), (m1, l1, id1, p1) = rot0[150], rot0[151]
common = np.intersect1d(id0[l0], id1[l1])
# only leaves that have come to rest (the wind slides some along the ground: those still turn, as they should)
common = np.array([i for i in common
                   if np.linalg.norm(p0[np.nonzero(id0 == i)[0][0]] - p1[np.nonzero(id1 == i)[0][0]]) < 1e-5])
a = np.array([m0[np.nonzero(id0 == i)[0][0]][:3, :3] for i in common])
b = np.array([m1[np.nonzero(id1 == i)[0][0]][:3, :3] for i in common])
check(len(common) > 5 and np.abs(a - b).max() < 1e-5, f"{len(common)} landed leaves stay still")

# snow globe: flakes stay inside the glass
so, rt, sc = system("GLOBE", 48)
glass = bpy.data.objects["Globe Glass"]
c = np.array(glass.matrix_world.translation)
r = np.linalg.norm(rt.sys.export()[0] - c, axis=1)
check(r.max() <= 0.5 + 1e-3, f"flakes inside the globe (furthest {r.max():.3f} m of 0.5)")

# rain: drops splash, splashes ring the surface with ripples
so, rt, sc = system("RAIN", 40)
d = core.read_cache(sim.particle_path(so, 40))
names = [k.name for k in so.nova.kinds]
counts = {n: int((d["kind"] == names.index(n)).sum()) for n in names}
check(counts["Splash"] > 0 and counts["Ripple"] > 0, f"rain chain: {counts}")
rip = d["P"].reshape(-1, 3)[d["kind"] == names.index("Ripple")]
check(np.abs(rip[:, 2]).max() < 0.02, "ripples lie on the surface")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
