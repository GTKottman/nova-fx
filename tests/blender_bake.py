"""Windowed test of the modal Bake operator (needs a window for its timer)."""
import os, sys, traceback, importlib
import bpy, addon_utils
OUT = os.environ["NOVA_UI_OUT"]
log = open(os.path.join(OUT, "bake_log.txt"), "w")
mod = "bl_ext.user_default.nova_fx"
state = {}
def area():
    w = bpy.context.window_manager.windows[0]
    return w, next(a for a in w.screen.areas if a.type == "VIEW_3D")
def start():
    addon_utils.enable(mod, default_set=True)
    w, a = area()
    with bpy.context.temp_override(window=w, area=a):
        bpy.ops.nova.add_preset(preset="TORCH")
        so = bpy.context.object
        so.nova.frame_end = 30
        so.nova.cache_dir = OUT + "/cache/"
        state["so"] = so
        print("invoke", bpy.ops.nova.bake("INVOKE_DEFAULT"), file=log, flush=True)
def check():
    sim = sys.modules[mod + ".sim"]
    so = state["so"]
    if sim.STATE["baking"]:
        return 0.5
    frames = sim.cached_frames(so)
    vdbs = [f for f in os.listdir(sim.cache_dir(so)) if f.endswith(".vdb")]
    vol = so.nova.fluid.volume
    print(f"cached {len(frames)} particle frames {frames[:2]}..{frames[-2:]}, {len(vdbs)} vdb, volume={vol and vol.data.filepath}, "
          f"seq={vol and vol.data.is_sequence}", file=log, flush=True)
    bpy.context.scene.frame_set(20)
    print("points at 20:", len(so.data.points), file=log, flush=True)
    log.close()
    bpy.ops.wm.quit_blender()
    return None
def tick():
    try:
        if "so" not in state:
            start(); return 1.0
        return check()
    except Exception:
        print(traceback.format_exc(), file=log, flush=True); log.close(); bpy.ops.wm.quit_blender()
bpy.app.timers.register(tick, first_interval=2.0)
