"""Magic dust: a twinkling colour-shifting trail behind a moving wand, curl-noise swirls."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import bmesh
from _common import add, look_at, loop, material, render_settings, start

sc = start(frame_end=150)
dust = add("MAGIC", "magic_wand")
for k in dust.nova.kinds:                      # brighter, longer-lived trail for a hero shot
    if k.name == "Dust":
        k.emit = 3.0
        k.life_max = 2.6
tip = bpy.data.objects["Wand Tip"]

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
wand.location = (0.12, -0.17, -0.12)
wand.rotation_euler = (math.radians(-55), math.radians(30), 0)

# a soft violet backdrop far behind so the colours read
sky = sc.world.node_tree.nodes.get("Background")
if sky:
    sky.inputs["Color"].default_value = (0.004, 0.003, 0.012, 1)

cam = sc.camera
cam.location = (0.0, -4.6, 1.35)
look_at(cam, (0, 0, 1.2))
cam.data.lens = 38
render_settings(res=(1280, 720), samples=96)
loop("magic_wand", [dust], 60, 119, step=1, width=640, still_at=100)
