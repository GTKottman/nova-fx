"""Run inside Blender (background): the FLIP liquid from preset to meshed surface.
blender -b --factory-startup --python tests/blender_liquid.py [-- --render OUT.png]"""
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
sc.frame_start, sc.frame_end = 1, 160
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


bpy.ops.nova.add_preset(preset="LIQUID", setup_scene=bool(argv))
so = bpy.context.object
so.nova.live = False
so.nova.cache_dir = tempfile.mkdtemp(prefix="nova_liq_") + "/"
fl = so.nova.fluid
check(fl.mode == "LIQUID" and fl.surface is not None and so.hide_render, "liquid preset: surface object, points out of the render")
frames = int(argv[argv.index("--frames") + 1]) if "--frames" in argv else 60
times, counts = [], []
for f in range(1, frames + 1):
    sc.frame_set(f)
    t = time.perf_counter()
    rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=True)
    times.append(time.perf_counter() - t)
    sim.load_frame(so, f)
    counts.append(rt.sys.count())
check(counts[0] > 50000 and len(set(counts)) == 1, f"{counts[0]} particles, none lost in the tank")
check(rt.gpu_note == "CPU (liquid)", rt.gpu_note)
P = rt.sys.export()[0]
lo, hi = sim.domain_box(fl.domain)
check((P >= lo - 1e-3).all() and (P[:, :2] <= hi[:2] + 1e-3).all(), "everything stays inside the tank")
ball = bpy.data.objects["Obstacle"]
d = np.linalg.norm(P - np.array(ball.location), axis=1)
check((d > 0.22 - 0.02).all(), f"nothing inside the ball (closest {d.min():.3f} m, radius 0.22)")
check(P[:, 0].max() > 0.9, f"the wave reaches the far wall (x max {P[:, 0].max():.2f})")
# the surface: a closed mesh from the points
dg = bpy.context.evaluated_depsgraph_get()
me = fl.surface.evaluated_get(dg).to_mesh()
nv = len(me.vertices)
co = np.empty(nv * 3, np.float32)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
fl.surface.evaluated_get(dg).to_mesh_clear()
check(nv > 2000 and co[:, 2].min() >= lo[2] - 1e-4 and co[:, 2].max() < 1.4, f"surface mesh: {nv} vertices, z {co[:, 2].min():.3f}..{co[:, 2].max():.3f}")
slow = [(i + 1, round(t, 2)) for i, t in enumerate(times) if t > 0.5]
print("slow frames", slow)
print(f"liquid: median {np.median(times) * 1000:.0f} ms/frame, max {max(times) * 1000:.0f} ms")

if "--render" in argv:
    out = argv[argv.index("--render") + 1]
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 48
    sc.render.resolution_x, sc.render.resolution_y = 800, 450
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print("rendered", out)

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
