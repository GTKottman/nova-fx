"""Explosion: a fuel burst that expands (volume source in the pressure solve), rolls into a fireball
and leaves a smoke cloud; debris trail sparks and smoke of their own (particles feed the fluid)."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, look_at, loop, material, render_settings, start

sc = start(frame_end=110)
boom = add("EXPLOSION", "explosion_sequence")
boom.nova.fluid.resolution = 128
boom.nova.fluid.device = "GPU"          # CPU fallback without Vulkan
sc.frame_set(boom.nova.frame_start)

ground = bpy.data.objects["Nova Ground"]
ground.data.materials.clear()
ground.data.materials.append(material("Dry Ground", (0.09, 0.075, 0.06), rough=0.95))

cam = sc.camera
cam.location = (0, -40, 3.0)
look_at(cam, (0, 0, 6.5))
cam.data.lens = 32
render_settings(res=(1280, 720), samples=96)
loop("explosion_sequence", [boom], 1, 96, step=2, width=640, still_at=22)
