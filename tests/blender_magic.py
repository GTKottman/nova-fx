"""Run inside Blender (background): ribbons, tangent emission, spirit smoke and the magic presets.
blender -b --factory-startup --python tests/blender_magic.py"""
import math, os, sys, tempfile

import addon_utils
import bpy
import numpy as np

mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = sys.modules[mod + ".sim"]
core = sys.modules[mod + ".core"]
import importlib
ribbons = importlib.import_module(mod + ".ribbons")
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 120
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


def system(key):
    bpy.ops.nova.add_preset(preset=key)
    so = bpy.context.object
    if not so.nova.is_system:
        so = next(o for c in so.users_collection for o in c.objects if o.nova.is_system)
    so.nova.live = False
    so.nova.cache_dir = tempfile.mkdtemp(prefix="nova_magic_") + "/"
    return so


# ribbons trace each particle's real path
so = system("WISPS")
for f in range(1, 41):
    sc.frame_set(f)
    sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=True)
sim.load_frame(so, 40)
rob = ribbons.ribbon_object(so, create=False)
check(rob is not None and len(rob.data.curves) > 0, f"{len(rob.data.curves)} ribbons")
sizes, P, heads, T, cur = ribbons.trails(so, 40, lambda f: sim.particle_path(so, f))
# the first ribbon's points are the particle's positions in the last frames, oldest first
k = int(np.argmax(sizes))  # the longest ribbon
start = int(sizes[:k].sum())
pid = cur["id"][heads[k]]
path = []
for b in range(sizes[k] - 1, -1, -1):
    d = core.read_cache(sim.particle_path(so, 40 - b))
    path.append(d["P"].reshape(-1, 3)[d["id"] == pid][0])
check(np.allclose(np.array(path), P[start:start + sizes[k]], atol=1e-6),
      f"a ribbon is the path its particle took ({sizes[k]} frames)")
check(sizes.max() == so.nova.ribbon_frames, f"ribbons reach {so.nova.ribbon_frames} frames back")
check(not so.hide_render, "Show Heads keeps the points in the render")

# tangent emission: sparks leave a ring sideways, around its axis
so = system("PORTAL")
for f in range(1, 3):
    sc.frame_set(f)
    rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=False)
P, V, *_ = rt.sys.export()
ring = bpy.data.objects["Portal Ring"]
c = np.array(ring.matrix_world.translation)
z = np.array(ring.matrix_world.to_3x3() @ __import__("mathutils").Vector((0, 0, 1)))
young = np.linalg.norm(P - c, axis=1)
near = np.abs(young - 1.1) < 0.15
rad = (P - c)[near]
rad -= np.outer(rad @ z, z)
rad /= np.linalg.norm(rad, axis=1)[:, None]
v = V[near].astype(np.float64)
v /= np.linalg.norm(v, axis=1)[:, None]
check(np.median(np.abs((v * rad).sum(1))) < 0.35, f"sparks leave the rim sideways (median |cos| to radius "
      f"{np.median(np.abs((v * rad).sum(1))):.2f})")

# spirit smoke: the volume uses the spirit material
so = system("SPIRIT")
for f in range(1, 13):
    sc.frame_set(f)
    sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=True)
sim.wait_vdb(so)
vob = sim.ensure_volume_object(sc, so)
mat = vob.data.materials[0]
check(mat.get("look") == "SPIRIT" and mat.node_tree.nodes.get("nova_spirit") is not None, "spirit volume material")
so.nova.fluid.gas_look = "FIRE"
check(vob.data.materials[0].node_tree.nodes.get("nova_spirit") is None, "switching back to fire rebuilds it")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
