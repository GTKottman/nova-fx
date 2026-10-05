"""Render a preset at a given frame (background Blender).
blender -b --factory-startup --python tests/blender_render.py -- PRESET FRAME OUT.png [engine] [samples]"""
import sys, time, tempfile
import bpy, addon_utils
argv = sys.argv[sys.argv.index("--") + 1:]
key, frames, out = argv[0], [int(x) for x in argv[1].split(",")], argv[2]
frame = max(frames)
engine = argv[3] if len(argv) > 3 else "CYCLES"
samples = int(argv[4]) if len(argv) > 4 else 64
mod = "bl_ext.user_default.nova_fx"
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
from importlib import import_module
sim = import_module(mod + ".sim")
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, max(frame, 250)
bpy.ops.nova.add_preset(preset=key, setup_scene=True)
so = bpy.context.object
so.nova.cache_dir = tempfile.mkdtemp(prefix="nova_r_", dir="/tmp/claude-1000") + "/"
import os
if os.environ.get("NOVA_DEVICE"):
    so.nova.fluid.device = os.environ["NOVA_DEVICE"]
r = sc.render
r.resolution_x, r.resolution_y, r.resolution_percentage = 960, 540, 100
r.filepath = out
if engine == "CYCLES":
    r.engine = "CYCLES"
    p = bpy.context.preferences.addons["cycles"].preferences
    p.compute_device_type = "OPTIX"
    p.get_devices()
    for d in p.devices:
        d.use = d.type == "OPTIX"
    sc.cycles.device = "GPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
else:
    try:
        r.engine = "BLENDER_EEVEE"
    except TypeError as e:
        r.engine = "BLENDER_EEVEE_NEXT"
sc.view_settings.view_transform = "AgX"
t0 = time.perf_counter()
for f in range(so.nova.frame_start, frame + 1):
    sc.frame_set(f)
    if f in frames:
        sim.wait_vdb(so)
        if so.nova.fluid.volume:
            sim.refresh_volume(so)
        r.filepath = out.replace("#", str(f)) if "#" in out else out
        print(f"sim to {f}: {time.perf_counter()-t0:.1f}s, {sim.stats(so)}")
        bpy.ops.render.render(write_still=True)
        print(f"rendered {r.filepath}")
