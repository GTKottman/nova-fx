"""Sparkler close-up: forking iron sparks, shallow depth of field, string lights melting into bokeh."""
import math, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import bmesh
from mathutils import Vector
from _common import add, look_at, loop, material, render_settings, start

sc = start(frame_end=120)
spark = add("SPARKLER", "sparkler_bokeh")
tip = bpy.data.objects["Sparkler Tip"].location.copy()

# warm string lights a few metres behind: small glowing bulbs that the lens turns into bokeh discs
rng = random.Random(3)
bulb = material("Bulb", (0, 0, 0), emit=(1.0, 0.55, 0.22), strength=10.0)
for strand in range(3):
    y = 5.0 + strand * 2.2
    for i in range(34):
        x = -5.0 + i * 0.32 + rng.uniform(-0.05, 0.05)
        z = tip.z - 1.3 + 0.25 * math.cosh((x - strand * 0.3) / 2.2) + strand * 0.55
        me = bpy.data.meshes.new("bulb")
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.025)
        bm.to_mesh(me)
        bm.free()
        b = bpy.data.objects.new("Bulb", me)
        b.location = (x, y, z)
        me.materials.append(bulb)
        sc.collection.objects.link(b)

cam = sc.camera
cam.location = tip + Vector((0.75, -1.45, 0.12))
look_at(cam, tip + Vector((0.02, 0.0, -0.07)))
cam.data.lens = 85
render_settings(res=(1280, 720), samples=128, dof=((cam.location - tip).length, 2.8))
loop("sparkler_bokeh", [spark], 40, 87, step=1, width=640, still_at=72)
