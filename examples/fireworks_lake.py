"""Fireworks show over a lake: eleven shell types, reflections in rippled water, a city skyline."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import bmesh
from _common import add, look_at, loop, material, render_settings, start, still

sc = start(frame_end=330)
show = add("FIREWORKS", "fireworks_lake")
for ob in bpy.data.objects:          # a busier show: launch shells a little more often
    if ob.nova_emitter.enabled:
        ob.nova_emitter.rate = 0.28

# the lake: a dark mirror with fine ripples so reflections streak vertically like on real water
me = bpy.data.meshes.new("Lake")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=900)
bm.to_mesh(me)
bm.free()
lake = bpy.data.objects.new("Lake", me)
sc.collection.objects.link(lake)
water = material("Water", (0.01, 0.012, 0.016), rough=0.04)
nt = water.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
bsdf.inputs["IOR"].default_value = 1.33
tc = nt.nodes.new("ShaderNodeTexCoord")
mp = nt.nodes.new("ShaderNodeMapping")
mp.inputs["Scale"].default_value = (0.05, 1.4, 1.0)   # ripples stretched across the view
noise = nt.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 4.0
noise.inputs["Detail"].default_value = 6.0
bump = nt.nodes.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.7
nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
nt.links.new(mp.outputs["Vector"], noise.inputs["Vector"])
nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
me.materials.append(water)

# skyline far across the lake: dark blocks, a few warm windows
rng = random.Random(7)
dark = material("Building", (0.006, 0.006, 0.008), rough=0.8)
glow = material("Windows", (0.0, 0.0, 0.0), emit=(1.0, 0.62, 0.3), strength=2.5)
x = -760.0
while x < 760:
    w, h = rng.uniform(14, 34), rng.uniform(8, 38) * (1.7 if abs(x) < 140 else 1.0)
    me = bpy.data.meshes.new("b")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    b = bpy.data.objects.new("Building", me)
    b.location = (x + w / 2, 520 + rng.uniform(0, 80), h / 2)
    b.scale = (w, rng.uniform(10, 25), h)
    me.materials.append(dark)
    sc.collection.objects.link(b)
    for _ in range(int(h / 6)):          # lit windows on the facade facing the lake
        if rng.random() < 0.18:
            me2 = bpy.data.meshes.new("win")
            bm = bmesh.new()
            bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
            bm.to_mesh(me2)
            bm.free()
            win = bpy.data.objects.new("Window", me2)
            win.location = (x + rng.uniform(2, w - 2), b.location.y - b.scale.y / 2 - 0.05, rng.uniform(3, h - 2))
            win.rotation_euler = (1.5708, 0, 0)
            win.scale = (rng.uniform(1.0, 2.0), rng.uniform(0.8, 1.4), 1)
            me2.materials.append(glow)
            sc.collection.objects.link(win)
    x += w + rng.uniform(1, 8)

# night sky: black overhead, a faint city glow on the horizon so the skyline reads as a silhouette
w = sc.world
nt = w.node_tree
bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.0
ramp.color_ramp.elements[0].color = (0.022, 0.019, 0.03, 1)
ramp.color_ramp.elements[1].position = 0.08
ramp.color_ramp.elements[1].color = (0.002, 0.0025, 0.005, 1)
nt.links.new(tc.outputs["Generated"], sep.inputs[0])
nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])

# level, wide camera just above the water: bursts above the skyline, their reflections below it
cam = sc.camera
cam.location = (0, -200, 3.5)
look_at(cam, (0, 0, 14))
cam.data.lens = 20
render_settings(res=(1280, 720), samples=96)
loop("fireworks_lake", [show], 180, 300, step=2, width=640, still_at=270)
