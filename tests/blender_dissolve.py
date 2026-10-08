"""Run inside Blender (background): Disintegrate. The mask, the material and the particles agree.
blender -b --factory-startup --python tests/blender_dissolve.py [-- --render OUT.png]"""
import os, sys, tempfile

import addon_utils
import bpy
import numpy as np

mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sim = sys.modules[mod + ".sim"]
dissolve = sys.modules[mod + ".dissolve"]
core = sys.modules[mod + ".core"]
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 160
ok = True
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


bpy.ops.nova.add_preset(preset="DISINTEGRATE", setup_scene=bool(argv))
so = bpy.context.object
so.nova.live = False
so.nova.cache_dir = tempfile.mkdtemp(prefix="nova_dis_") + "/"
ob = bpy.data.objects["Burning Monkey"]
d = ob.nova_dissolve
check(d.enabled and d.front is not None and ob.modifiers.get(dissolve.MOD), "preset sets up the front and the mask")
mats = list(ob.data.materials)
check(all(m.get(dissolve.COPY) for m in mats) and bpy.data.materials.get("Nova Monkey Paint").users == 0,
      "materials are dissolve copies; the original is untouched")


def mask(frame):
    sc.frame_set(frame)
    dg = bpy.context.evaluated_depsgraph_get()
    co, tri, v, nrm, area = dissolve.evaluated(ob, dg)
    w = np.array(ob.matrix_world)
    zw = co @ w[:3, :3].T + w[:3, 3]
    return zw, v, area, tri


zw, v, area, tri = mask(70)
fz = d.front.matrix_world.translation.z
gone = v < 0
check(0.2 < gone.mean() < 0.8, f"frame 70: {gone.mean() * 100:.0f}% of the points gone")
# without noise the mask is exactly the height above the front
d.noise = 0.0
zw, v, area, tri = mask(70)
check(np.abs(v - (zw[:, 2] - d.front.matrix_world.translation.z)).max() < 1e-4,
      "the mask is the distance past the front plane (metres)")
d.noise = 0.25
zw, v, area, tri = mask(70)
dev = v - (zw[:, 2] - d.front.matrix_world.translation.z)
check(0.05 < np.abs(dev).max() <= 0.2501, f"ragged: noise moves the front up to {np.abs(dev).max():.3f} m")
mask_before = mask(5)[1]
mask_after = mask(150)[1]
check((mask_before > 0).all() and (mask_after < 0).all(), "solid before the sweep, gone after it")

# particles: every one is born where the surface crossed zero during its frame
sc.frame_set(1)
names = [k.name for k in so.nova.kinds]
born_ok, total, area_gone, counts = [], 0, 0.0, []
prev_v = None
for f in range(1, 101):
    sc.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    rt = sim.step(sc, so, f, dg, write=True)
    co, tri_, vv, nrm, ar = dissolve.evaluated(ob, dg)
    if prev_v is not None:
        a_prev = (prev_v[tri_] > 0).mean(1) * ar
        a_now = (vv[tri_] > 0).mean(1) * ar
        area_gone += float((a_prev - a_now).clip(0).sum())
    prev_v = vv
    c = core.read_cache(sim.particle_path(so, f))
    counts.append(c["n"])
total = counts[-1]
ember = so.nova.kinds["Ember"]
check(counts[5] == 0 and max(counts) > 1000, f"nothing before the front arrives, {max(counts)} particles at the peak")
# rough count check: (ember + ash density) x area that went
expect = (1200 + 2500) * area_gone
emitted = sum(rt.em_state.get(n, {}).get("dummy", 0) for n in ())  # not tracked: use born ids
c = core.read_cache(sim.particle_path(so, 100))
born = int(c["id"].max()) + 1 if c["n"] else 0
check(0.6 < born / max(expect, 1) < 1.5, f"{born} born for {area_gone:.3f} m² gone ({expect:.0f} expected)")
# fresh particles sit on the burning edge
sc.frame_set(60)
dg = bpy.context.evaluated_depsgraph_get()
c = core.read_cache(sim.particle_path(so, 60))
young = c["age"].astype(np.float32) < 0.02  # age is a fraction of life: just born
P = c["P"].reshape(-1, 3)[young]
zf = d.front.matrix_world.translation.z
check(len(P) > 50 and np.abs(P[:, 2] - zf).max() < d.noise + 0.08,
      f"{len(P)} fresh particles within the ragged band around the front (|dz| <= {np.abs(P[:, 2] - zf).max():.2f} m)")

# flames along the edge: the ember emitter also feeds the fluid on the glowing band
presets = sys.modules[mod + ".presets"]
coll = so.users_collection[0]
presets.domain(coll, so, (3.4, 2.4, 3.4), (0, 0, 1.4), 48, device="CPU")
emo = bpy.data.objects["Burning Monkey Ember"].nova_emitter
emo.fl_enabled, emo.fl_fuel, emo.fl_heat = True, 1.0, 1.0
sc.frame_set(1)
for f in range(1, 61):
    sc.frame_set(f)
    rt = sim.step(sc, so, f, bpy.context.evaluated_depsgraph_get(), write=False)
fl = rt.fluid
fuel = fl.field(2)  # fuel burns off within a second: it marks where the edge feeds the fire now
zs = fl.origin[2] + (np.arange(fuel.shape[0]) + 0.5) * fl.dx
prof = fuel.sum(axis=(1, 2))
zc = float((prof * zs).sum() / max(prof.sum(), 1e-9))
zf = d.front.matrix_world.translation.z
check(prof.sum() > 0 and abs(zc - zf) < d.noise + 0.3,
      f"the fluid is fed along the burning edge (fuel centred at z {zc:.2f}, front at {zf:.2f})")
so.nova.fluid.enabled = False

# turning it off restores the object
d.enabled = False
check(ob.modifiers.get(dissolve.MOD) is None and ob.data.materials[0].name == "Nova Monkey Paint",
      "off: modifier gone, original material back")
d.enabled = True
check(ob.modifiers.get(dissolve.MOD) is not None, "on again")

if argv and argv[0] == "--render":
    out = argv[1]
    sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE_NEXT"
    sc.render.resolution_x, sc.render.resolution_y = 640, 480
    sc.render.filepath = out
    sc.frame_set(60)
    sim.load_frame(so, 60)
    bpy.ops.render.render(write_still=True)
    print("rendered", out)

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
