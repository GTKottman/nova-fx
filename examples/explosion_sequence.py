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
boom.nova.display = "STREAKS"             # debris and its trail sparks as motion streaks, not dots
boom.nova.streak_length = 0.03

ground = bpy.data.objects["Nova Ground"]
ground.data.materials.clear()
ground.data.materials.append(material("Dry Ground", (0.09, 0.075, 0.06), rough=0.95))

# dusk: a warm band on the horizon fading to deep blue overhead
nt = sc.world.node_tree
bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.0
ramp.color_ramp.elements[0].color = (0.30, 0.12, 0.05, 1)
ramp.color_ramp.elements[1].position = 0.35
ramp.color_ramp.elements[1].color = (0.012, 0.018, 0.045, 1)
mid = ramp.color_ramp.elements.new(0.07)
mid.color = (0.07, 0.05, 0.08, 1)
nt.links.new(tc.outputs["Generated"], sep.inputs[0])
nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])

# low, warm sun from the front left, so the smoke cloud has a lit side and a shadow side
sun = bpy.data.objects["Nova Sun"]
sun.rotation_euler = (math.radians(78), 0, math.radians(-60))
sun.data.color = (1.0, 0.62, 0.38)
sun.data.energy = 3.0

cam = sc.camera
cam.location = (0, -27, 2.2)
look_at(cam, (0, 0, 4.6))
cam.data.lens = 30
render_settings(res=(1280, 720), samples=96)
loop("explosion_sequence", [boom], 1, 96, step=2, width=640, still_at=34)  # still: the rolling fireball
