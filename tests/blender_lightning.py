"""Run inside Blender (background): the Lightning preset's controls.
blender -b --factory-startup --python tests/blender_lightning.py"""
import sys

import addon_utils
import bpy

mod = "bl_ext.user_default.nova_fx"
addon_utils.enable(mod, default_set=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable(mod, default_set=True)
sc = bpy.context.scene
sc.frame_start, sc.frame_end = 1, 80
ok = True


def check(cond, what):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


bpy.ops.nova.add_preset(preset="LIGHTNING")
ob = bpy.context.object
lt = ob.nova_lightning
check(ob.type == "CURVES" and lt.enabled, "the preset focuses the bolt")
check(len(ob.data.points) > 100 and len(ob.data.curves) > 3, f"{len(ob.data.points)} points in {len(ob.data.curves)} curves")
strike = tuple(ob["nova_strike"])
check(abs(strike[2] - lt.ground) < 1e-4, f"strikes the ground at {strike[0]:.1f}, {strike[1]:.1f}")
check((lt.impact.location - ob.matrix_world.translation).length > 1 and abs(lt.impact.location.z - 0.05) < 1e-3
      and abs(lt.impact.location.x - strike[0]) < 1e-3, "impact emitter sits on the strike point")

first = [tuple(p.position) for p in ob.data.points[:50]]
lt.seed += 1
check([tuple(p.position) for p in ob.data.points[:50]] != first, "a new seed regrows the bolt")
check(abs(lt.impact.location.x - ob["nova_strike"][0]) < 1e-3, "the impact emitter follows the new strike")

tgt = bpy.data.objects.new("Rod", None)
sc.collection.objects.link(tgt)
tgt.location = (10, 4, 6)
bpy.context.view_layer.update()
lt.target = tgt
check(all(abs(a - b) < 1e-3 for a, b in zip(ob["nova_strike"], (10, 4, 6))), "a strike target is hit")
lt.target = None

nt = ob.data.materials[0].node_tree
lt.strike_frame = 30
check(lt.impact.nova_emitter.burst_frame == 30, "the impact burst follows the strike frame")


def value(name, frame):
    sc.frame_set(frame)
    return nt.nodes[name].outputs[0].default_value


check(value("nova_flash", 20) == 0 and value("nova_lglow", 20) == 0, "dark before the leader")
check(0 < value("nova_leader", 26) < 1 and value("nova_lglow", 26) == 1, "the leader is coming down at frame 26")
check(value("nova_flash", 30) >= 0.99 and value("nova_bflash", 30) >= 0.99, "the return stroke at frame 30")
light = bpy.data.objects[ob.name + " Flash"].data
sc.frame_set(30)
check(light.energy > 0.5 * lt.light_power, f"the flash light fires ({light.energy:.0f} W)")
end = 30 + (lt.strokes - 1) * lt.stroke_gap * 1.4 + lt.afterglow + 2
check(value("nova_flash", int(end) + 1) == 0, "dark again after the afterglow")
check(value("nova_temp", 31) > value("nova_temp", int(end) - 2) > 2900, "the channel cools as it fades")
bpy.ops.nova.lightning_regrow(new_seed=True)
check(len(ob.data.points) > 100, "Regrow / New Seed operator")
print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
