"""Run inside Blender (background): blood stains lie flat on what they hit, whitewater, ink.
blender -b --factory-startup --python tests/blender_fx.py"""
import sys, tempfile

import addon_utils
import bpy
import numpy as np

mod = "bl_ext.user_default.nova_fx"
sim = core = None
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


def system(key, frames):
    global sim, core
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable(mod, default_set=True)
    sim, core = sys.modules[mod + ".sim"], sys.modules[mod + ".core"]
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 200
    bpy.ops.nova.add_preset(preset=key)
    so = bpy.context.object
    so.nova.live = False
    so.nova.cache_dir = tempfile.mkdtemp(prefix="nova_fx_") + "/"
    for f in range(1, frames + 1):
        sc.frame_set(f)
        rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=True)
    sim.load_frame(so, frames)
    return so, rt, sc


# blood: stains stuck on the wall face the room, on the floor face up
so, rt, sc = system("SPLATTER", 30)
d = core.read_cache(sim.particle_path(so, 30))
names = [k.name for k in so.nova.kinds]
st = d["kind"] == names.index("Stain")
P, V = d["P"].reshape(-1, 3)[st], d["V"].reshape(-1, 3)[st].astype(np.float64)
wall_y = bpy.data.objects["Wall"].location.y
on_floor = P[:, 2] < 0.01
on_wall = (np.abs(P[:, 1] - wall_y) < 0.01) & ~on_floor
check(len(P) == (on_wall | on_floor).sum(), f"every stain is on a surface ({len(P)} stains)")
nv = V / np.maximum(np.linalg.norm(V, axis=1), 1e-12)[:, None]
check(on_wall.sum() > 50 and on_floor.sum() > 5, f"{on_wall.sum()} stains on the wall, {on_floor.sum()} on the floor")
corner = on_floor & (np.abs(P[:, 1] - wall_y) < 0.01)  # in the corner either surface is right
check(np.all(nv[on_wall, 1] < -0.99) and np.all(nv[on_floor & ~corner, 2] > 0.99),
      "each stain carries its surface's normal (wall: toward the room, floor: up)")
sob = bpy.data.objects[so.name + " Shapes"]
dg = bpy.context.evaluated_depsgraph_get()
zs = [np.array(i.matrix_world)[:3, 2] for i in dg.object_instances
      if i.is_instance and i.parent and i.parent.name == sob.name and i.object.data.name.startswith("Nova Splat")]
zs = np.array([z / np.linalg.norm(z) for z in zs])
check(len(zs) == st.sum() and (np.abs(zs[:, 1]) > 0.99).sum() >= on_wall.sum(),
      f"{len(zs)} stain shapes lie flat on their surface")

# whitewater: the crash throws spray, leaves foam on the water, traps bubbles; no bubble survives in the air
so, rt, sc = system("WHITEWATER", 50)
d = core.read_cache(sim.particle_path(so, 50))
names = [k.name for k in so.nova.kinds]
counts = {n: int((d["kind"] == names.index(n)).sum()) for n in names}
# spray is fleeting (it lands and turns to foam): count what it became too
check(counts["Spray"] + counts["Foam"] > 1000 and counts["Foam"] > 50 and counts["Bubble"] > 20, f"whitewater: {counts}")
f = rt.fluid
bub = d["P"].reshape(-1, 3)[d["kind"] == names.index("Bubble")]
cell = np.floor((bub - np.array(f.origin)) / f.dx).astype(int)
check(len(bub) > 0, "bubbles exist")
ww = bpy.data.objects.get(so.name + " Whitewater")
check(ww is not None and not ww.hide_render and so.hide_render, "whitewater renders from its own object")

# ink: the ink look
so, rt, sc = system("INK", 20)
sim.wait_vdb(so)
vob = sim.ensure_volume_object(sc, so)
check(vob.data.materials[0].get("ink"), "ink volume material")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
