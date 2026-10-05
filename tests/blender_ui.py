"""Windowed UI smoke test: draws every Nova panel and screenshots the sidebar."""
import os, sys, traceback
import bpy, addon_utils
OUT = os.environ.get("NOVA_UI_OUT", "/tmp")
mod = "bl_ext.user_default.nova_fx"
log = open(os.path.join(OUT, "ui_log.txt"), "w")
def L(*a):
    print(*a, file=log, flush=True)

steps = []
def area3d():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                return w, a
def shot(name):
    w, a = area3d()
    with bpy.context.temp_override(window=w, area=a):
        bpy.ops.screen.screenshot_area(filepath=os.path.join(OUT, name + ".png"))
    L("shot", name)

def select(ob):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob

def setup():
    addon_utils.enable(mod, default_set=True)
    # scripts cannot switch sidebar tabs, so show the Nova panels in the active one for the screenshot
    ui = sys.modules[mod + ".ui"]
    for c in ui.CLASSES:
        if getattr(c, "bl_category", None) == "Nova FX":
            bpy.utils.unregister_class(c)
            c.bl_category = "Item"
            bpy.utils.register_class(c)
    for n in ("VIEW3D_PT_transform", "OBJECT_PT_transform"):
        c = getattr(bpy.types, n, None)
        if c:
            bpy.utils.unregister_class(c)
    w, a = area3d()
    a.spaces[0].show_region_ui = True
    for r in a.regions:
        if r.type == "UI":
            r.width  # noqa
            try:
                r.active_panel_category = "Nova FX"
            except Exception as e:
                L("category", e)
    with bpy.context.temp_override(window=w, area=a):
        bpy.ops.nova.add_preset(preset="CAMPFIRE")
    L("campfire added", bpy.context.object.name)
    for f in range(1, 25):
        bpy.context.scene.frame_set(f)

def s_system():
    shot("1_system")
def s_emitter():
    select(bpy.data.objects["Fire Source"]); 
def s_emitter_shot():
    shot("2_emitter")
def s_fireworks():
    w, a = area3d()
    with bpy.context.temp_override(window=w, area=a):
        bpy.ops.nova.add_preset(preset="FIREWORKS")
    for f in range(1, 120):
        bpy.context.scene.frame_set(f)
    a.spaces[0].shading.type = "SOLID"
    reg = next(r for r in a.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=w, area=a, region=reg):
        bpy.ops.view3d.view_selected()
def s_fw_shot():
    shot("3_fireworks")
def s_quit():
    L("done")
    log.close()
    bpy.ops.wm.quit_blender()

seq = [setup, s_system, s_emitter, s_emitter_shot, s_fireworks, s_fw_shot, s_quit]
def tick():
    if not seq:
        return None
    fn = seq.pop(0)
    try:
        fn()
    except Exception:
        L("ERROR in", fn.__name__, traceback.format_exc())
    return 1.5
bpy.app.timers.register(tick, first_interval=2.0)
