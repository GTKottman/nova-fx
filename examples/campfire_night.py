"""Campfire at night: combustion simulated on the GPU, embers riding the flow, firelit stones."""
import math, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import bmesh
from _common import add, look_at, loop, material, render_settings, start

sc = start(frame_end=140)
fire = add("CAMPFIRE", "campfire_night")
fire.nova.fluid.resolution = 128           # finer flame licks
fire.nova.fluid.device = "GPU"             # falls back to the CPU solver without a Vulkan GPU
sc.frame_set(fire.nova.frame_start)        # restart with the new grid

# a ring of rough stones around the logs
rng = random.Random(11)
stone = material("Stone", (0.32, 0.30, 0.28), rough=0.8)
for i in range(11):
    a = i / 11 * 2 * math.pi + rng.uniform(-0.1, 0.1)
    me = bpy.data.meshes.new("stone")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
    for v in bm.verts:                      # lumpy, not perfect spheres
        v.co *= 1.0 + 0.18 * math.sin(v.co.x * 5.1 + i) * math.cos(v.co.y * 4.3 - i)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    s = bpy.data.objects.new("Stone", me)
    r = rng.uniform(0.09, 0.13)
    s.location = (0.55 * math.cos(a), 0.55 * math.sin(a), r * 0.45)
    s.scale = (r * rng.uniform(1.1, 1.5), r, r * 0.75)
    s.rotation_euler = (0, 0, a + rng.uniform(-0.4, 0.4))
    me.materials.append(stone)
    sc.collection.objects.link(s)

# dirt ground with a little colour variation
g = bpy.data.objects["Nova Ground"]
dirt = material("Dirt", (0.06, 0.045, 0.035), rough=0.95)
nt = dirt.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
noise = nt.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 18.0
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.07, 0.055, 0.045, 1)
ramp.color_ramp.elements[1].color = (0.17, 0.13, 0.10, 1)
nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
g.data.materials.clear()
g.data.materials.append(dirt)

# faint blue moonlight from behind
moon = bpy.data.objects.new("Moon", bpy.data.lights.new("Moon", "SUN"))
moon.data.energy = 0.08
moon.data.color = (0.55, 0.65, 1.0)
moon.rotation_euler = (math.radians(55), 0, math.radians(160))
sc.collection.objects.link(moon)

cam = sc.camera
cam.location = (0.0, -2.35, 0.42)
look_at(cam, (0, 0, 0.62))
cam.data.lens = 32
render_settings(res=(1280, 720), samples=96)
sc.view_settings.exposure = -0.8            # keep the flame core from clipping to white
loop("campfire_night", [fire], 72, 119, step=1, width=640, still_at=104)
