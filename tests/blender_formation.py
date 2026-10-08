"""Run inside Blender (background): Form force and Shape bursts with real objects.
blender -b --factory-startup --python tests/blender_formation.py"""
import math, os, sys, tempfile

import addon_utils
import bpy
import numpy as np

mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = sys.modules[mod + ".sim"]
shapes = sys.modules[mod + ".shapes"]
core = sys.modules[mod + ".core"]
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 200
ok = True
work = tempfile.mkdtemp(prefix="nova_form_")


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


def nearest(P, pts):
    out = np.empty(len(P))
    for i in range(0, len(P), 2000):
        out[i:i + 2000] = np.sqrt(((P[i:i + 2000, None] - pts[None]) ** 2).sum(-1)).min(1)
    return out


dg = bpy.context.evaluated_depsgraph_get()

# ---- sampling: text outline vs surface, curves without fill
bpy.ops.object.text_add(location=(0, 0, 0))
txt = bpy.context.object
txt.data.body = "HI"
dg = bpy.context.evaluated_depsgraph_get()
surf = shapes.sample(txt, dg, "SURFACE", 4000)
line = shapes.sample(txt, dg, "OUTLINE", 4000)
check(len(surf) == len(line) == 4000 and np.abs(surf[:, 2]).max() < 1e-4, "text samples lie in its plane")
# the H's crossbar interior is inside the surface but far from the outline
lo, hi = surf.min(0), surf.max(0)
inner = nearest(surf, line)
check(inner.max() > 0.02 and nearest(line, surf).max() < 0.05, f"outline is the border (surface reaches {inner.max():.3f} inside)")
bpy.ops.curve.primitive_bezier_circle_add(radius=2.0)
circ = bpy.context.object
dg = bpy.context.evaluated_depsgraph_get()
pts = shapes.sample(circ, dg, "OUTLINE", 2000)
r = np.linalg.norm(pts[:, :2], axis=1)
check(np.abs(r - 2.0).max() < 0.02, f"an unfilled curve samples along its line (radius {r.min():.3f}-{r.max():.3f})")
for o in (txt, circ):
    bpy.data.objects.remove(o)

# ---- the preset: dust assembles into the word, then scatters
bpy.ops.nova.add_preset(preset="FORMATION")
so = bpy.context.object
so.nova.cache_dir = os.path.join(work, "cache") + "/"
so.nova.live = False
logo = bpy.data.objects["Logo Text"]
form = bpy.data.objects["Logo Form"]
dg = bpy.context.evaluated_depsgraph_get()
target = shapes.world(logo, shapes.sample(logo, dg, logo.nova_shape.mode, logo.nova_shape.points, logo.nova_shape.seed))
dist = {}
for f in range(1, 181):
    sc.frame_set(f)
    rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=False)
    if f in (10, 120, 180):
        P = rt.sys.export()[0]
        dist[f] = float(np.median(nearest(P[:6000], target)))
check(rt.sys.count() == 30000, f"{rt.sys.count()} motes")
check(dist[10] > 1.0, f"frame 10: scattered (median {dist[10]:.2f} m from the word)")
check(dist[120] < 0.003, f"frame 120: formed (median {dist[120] * 1000:.2f} mm from the word)")
check(dist[180] > 0.05, f"frame 180: released ({dist[180]:.2f} m)")

# moving the word moves the formed particles with it
sc.frame_set(1)
logo.location.x += 3.0
target2 = target + np.array([3.0, 0, 0], np.float32)
for f in range(1, 121):
    sc.frame_set(f)
    rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=False)
d2 = float(np.median(nearest(rt.sys.export()[0][:6000], target2)))
check(d2 < 0.003, f"the shape follows its object ({d2 * 1000:.2f} mm)")
logo.location.x -= 3.0

# ---- a firework shell that bursts into the word
bpy.ops.nova.add_preset(preset="FIREWORKS")
fw = bpy.context.object
fw.nova.live = False
for ob in sc.objects:
    if ob.nova_emitter.enabled and ob.nova_emitter.system == fw:
        ob.nova_emitter.rate = 0
k = fw.nova.kinds["Shell Peony"]
k.death_pattern, k.death_shape, k.death_count, k.death_speed, k.death_speed_var, k.death_inherit = \
    "SHAPE", logo, 600, 30.0, 0.0, 0.0
star = fw.nova.kinds["Peony Star"]
star.drag_lin, star.drag_quad, star.gravity, star.life_min, star.life_max = 2.0, 0.0, 0.0, 4.0, 4.0
star.trail_kind = ""
em = bpy.data.objects["Launcher Peony"]
em.nova_emitter.burst, em.nova_emitter.burst_frame = 1, 2
names = [x.name for x in fw.nova.kinds]
for f in range(1, 150):
    sc.frame_set(f)
    rt = sim.step(sc, fw, f, bpy.context.evaluated_depsgraph_get(), write=True)
d = core.read_cache(sim.particle_path(fw, 149))
P = d["P"].reshape(-1, 3)[d["kind"] == names.index("Peony Star")].astype(np.float64)
check(len(P) == 600, f"{len(P)} stars")
c = (P.max(0) + P.min(0)) / 2
L = np.array(logo.matrix_world.to_3x3())
unit = target - (target.max(0) + target.min(0)) / 2
unit /= np.linalg.norm(unit, axis=1).max()
Q = (P - c) / np.linalg.norm(P - c, axis=1).max()
err = nearest(Q, unit)
check(np.median(err) < 0.01 and abs(np.ptp(P[:, 1])) < 0.05 * np.ptp(P[:, 0]),
      f"stars spell the word, facing the camera like the text (median error {np.median(err):.4f} of its size)")
size = np.linalg.norm(P - c, axis=1).max()
check(abs(size - 15.0) / 15.0 < 0.05, f"word radius {size:.1f} m for speed/drag = 15 m")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
