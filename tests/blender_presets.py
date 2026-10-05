"""Run inside Blender (background): builds every preset and simulates a few frames.
blender -b --factory-startup --python tests/blender_presets.py -- [PRESET ...] [--frames N]"""
import sys, time, os, tempfile
import bpy, addon_utils
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
frames = 12
if "--frames" in argv:
    i = argv.index("--frames"); frames = int(argv[i + 1]); del argv[i:i + 2]
mod = "bl_ext.user_default.nova_fx"
addon_utils.enable(mod, default_set=True)
nova = sys.modules[mod]
from importlib import import_module
presets = import_module(mod + ".presets"); sim = import_module(mod + ".sim")
tmp = tempfile.mkdtemp(prefix="nova_test_", dir="/tmp/claude-1000")
keys = argv or [p[0] for p in presets.PRESETS]
ok = True
for key in keys:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable(mod, default_set=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, 250
    try:
        bpy.ops.nova.add_preset(preset=key, setup_scene=True)
        so = bpy.context.object
        so.nova.cache_dir = tmp + "/"
        t0 = time.perf_counter()
        for f in range(so.nova.frame_start, so.nova.frame_start + frames):
            sc.frame_set(f)  # live preview path (frame_change handler)
        dt = time.perf_counter() - t0
        st = sim.stats(so)
        npts = len(so.data.points)
        vdb = os.path.exists(sim.volume_path(so, so.nova.frame_start + frames - 1)) if so.nova.fluid.enabled else None
        sim.wait_vdb(so)
        print(f"[{key:10s}] {frames} frames {dt:6.2f}s  particles={st.get('count')} shown={npts} "
              f"pms={st.get('particle_ms', 0):.1f} fms={st.get('fluid_ms', 0):.0f} cg={st.get('cg_iters')} "
              f"active={st.get('active', 0):.2f} vdb={vdb} vol={so.nova.fluid.volume.name if so.nova.fluid.volume else None}")
    except Exception as e:
        import traceback; traceback.print_exc(); ok = False
        print(f"[{key}] FAILED: {e}")
print("ALL OK" if ok else "FAILURES")
