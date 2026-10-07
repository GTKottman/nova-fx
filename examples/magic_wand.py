"""Magic dust: a twinkling colour-shifting trail behind a moving wand, curl-noise swirls."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import bmesh
from mathutils import Vector
from _common import add, look_at, loop, material, render_settings, start

sc = start(frame_end=260)
dust = add("MAGIC", "magic_wand")
for k in dust.nova.kinds:                      # a longer trail, cyan to magenta; moderate glow keeps colour saturated
    if k.name == "Dust":
        k.emit = 1.1
        k.life_max = 2.6
        k.color, k.color2, k.color_curve = (0.1, 0.55, 1.0), (1.0, 0.15, 0.85), 0.6
    elif k.name == "Glint":
        k.emit = 40
tip = bpy.data.objects["Wand Tip"]
tip.animation_data_clear()                     # fly the preset's figure-eight twice (120 frames per lap)
for f in range(1, 242, 10):
    a = (f - 1) / 120 * 2 * math.pi
    tip.location = (1.2 * math.sin(a), 0.6 * math.sin(2 * a), 1.2 + 0.25 * math.sin(3 * a))
    tip.keyframe_insert("location", frame=f)

# a dark wooden wand that follows the tip, pointing back toward the camera side
me = bpy.data.meshes.new("Wand")
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.012, radius2=0.006, depth=0.42)
bm.to_mesh(me)
bm.free()
wand = bpy.data.objects.new("Wand", me)
me.materials.append(material("Wand Wood", (0.05, 0.025, 0.012), rough=0.45))
sc.collection.objects.link(wand)
wand.parent = tip
d = Vector((-0.12, 0.17, 0.12)).normalized()   # handle low, right and nearer the camera; +Z points at the tip
wand.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
wand.location = -d * 0.215

glow = bpy.data.objects.new("Tip Glow", bpy.data.lights.new("Tip Glow", "POINT"))
glow.data.energy = 3.0
glow.data.color = (0.55, 0.8, 1.0)
glow.data.shadow_soft_size = 0.02
glow.parent = tip
sc.collection.objects.link(glow)

# a soft violet backdrop far behind so the colours read
sky = sc.world.node_tree.nodes.get("Background")
if sky:
    sky.inputs["Color"].default_value = (0.004, 0.003, 0.012, 1)

cam = sc.camera
cam.location = (0.0, -4.6, 1.35)
look_at(cam, (0, 0, 1.2))
cam.data.lens = 38
render_settings(res=(1280, 720), samples=96)
loop("magic_wand", [dust], 121, 239, step=2, width=640, still_at=211)  # the second lap: warmed up, seamless
