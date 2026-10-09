"""Run inside Blender (background): thick liquids from the presets.
blender -b --factory-startup --python tests/blender_viscous.py"""
import os, sys, tempfile

import addon_utils
import bpy
import numpy as np

mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = sys.modules[mod + ".sim"]
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 200
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


def preset(key):
    bpy.ops.nova.add_preset(preset=key)
    so = bpy.context.object
    so.nova.live = False
    so.nova.cache_dir = tempfile.mkdtemp(prefix="nova_visc_") + "/"
    return so


def run(so, frames):
    for f in range(1, frames + 1):
        sc.frame_set(f)
        rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=False)
    return rt


# honey: the nozzle holds its stream, the surface is sized to the grid and looks like honey
so = preset("HONEY")
fl = so.nova.fluid
mod_ = fl.surface.modifiers["Nova Surface"]
rt = run(so, 24)
recs = sim.inflow_records(rt, sc, so, 24)
check(len(recs) == 1 and abs(recs[0][6] + 0.25) < 1e-6, f"one nozzle pouring down at 0.25 m/s")
P, V, *_ = rt.sys.export()
noz = np.array(recs[0][:3]); rad = recs[0][3]
top = np.linalg.norm(P - noz, axis=1) < rad * 0.9
check(top.any() and np.allclose(V[top, 2], -0.25, atol=1e-3), "honey inside the nozzle moves at the nozzle speed")
r = np.hypot(P[(P[:, 2] > 0.12) & (P[:, 2] < 0.18), 0], P[(P[:, 2] > 0.12) & (P[:, 2] < 0.18), 1])
check(len(r) and np.percentile(r, 95) < 0.008, f"a thin stream: radius {np.percentile(r, 95) * 1000:.1f} mm")
ins = {i.name: getattr(mod_.properties.inputs, i.identifier).value for i in mod_.node_group.interface.items_tree
       if getattr(i, "in_out", "") == "INPUT" and i.name in ("Radius", "Voxel Size")}
check(abs(ins["Radius"] - 1.2 * rt.fluid.dx) < 1e-6, f"surface sized to the grid: radius {ins['Radius'] * 1000:.1f} mm")
check(fl.surface.data.materials[0].name == "Nova Honey", "honey material")
fl.look = "LAVA"
check(fl.surface.data.materials[0].name == "Nova Lava", "changing the look swaps the material")

# melting: the letters hold until the lamp reaches them
so = preset("MELT")
rt = run(so, 2)
P0 = rt.sys.export()[0].copy()
rt = run(so, 30)
P1 = rt.sys.export()[0]
n = min(len(P0), len(P1))
moved = np.linalg.norm(P1[:n] - P0[:n], axis=1) > 0.01
lamp_x = bpy.data.objects["Heat Lamp"].location.x
near_lamp = np.abs(P0[:n, 0] - lamp_x) < 0.25
far = P0[:n, 0] > 0.5
check(moved[near_lamp].mean() > 0.3 and moved[far].mean() < 0.05,
      f"near the lamp {moved[near_lamp].mean() * 100:.0f}% have run, far away {moved[far].mean() * 100:.0f}%")

# heat force record
lamp = bpy.data.objects["Heat Lamp"]
recs = sim.force_records(rt, sc, None, so)
heat = [r for r in recs if r[0] == 6]
check(len(heat) == 1 and heat[0][7] == lamp.nova_force.temperature, "heat lamp sends its temperature")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
