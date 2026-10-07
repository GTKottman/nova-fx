"""Grinder sparks splashing off a steel Suzanne: an exact mesh collider (signed distance field),
continuous collision (no tunnelling through the thin ears), sparks that split and spatter."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, look_at, loop, material, render_settings, start

sc = start(frame_end=120)
sparks = add("GRINDER", "grinder_monkey")

bpy.ops.mesh.primitive_monkey_add(size=0.7, location=(0, -0.75, 0.32), rotation=(0.3, 0, 0))
monkey = bpy.context.object
for p in monkey.data.polygons:
    p.use_smooth = True
monkey.modifiers.new("Smooth", "SUBSURF").levels = 2
monkey.data.materials.append(material("Brushed Steel", (0.55, 0.55, 0.57), rough=0.32, metal=1.0))
monkey.nova_collider.enabled = True
monkey.nova_collider.shape = "MESH"      # the exact shape, baked to a distance field once
monkey.nova_collider.sdf_res = 96

floor = bpy.data.objects["Nova Ground"]  # dark polished concrete: sparks reflect in it
floor.data.materials.clear()
floor.data.materials.append(material("Concrete", (0.03, 0.03, 0.032), rough=0.22))

cam = sc.camera
cam.location = (1.55, -2.35, 0.75)
look_at(cam, (0, -0.65, 0.32))
cam.data.lens = 40
render_settings(res=(1280, 720), samples=128, dof=(2.3, 4.0))
loop("grinder_monkey", [sparks], 30, 77, step=1, width=640, still_at=60)
