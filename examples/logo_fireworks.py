"""Shaped fireworks: shells that burst into a word and a star. A Shape burst sends every star along a point of
the object, and linear drag stops it there: the shape's size is burst speed / linear drag."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh
import bpy
from _common import add, look_at, loop, nova, render_settings, start

sc = start(frame_end=260)
show = add("FIREWORKS", "logo_fireworks")
presets = nova("presets")
coll = show.users_collection[0]
for ob in sc.objects:
    if ob.nova_emitter.enabled:
        ob.nova_emitter.rate = 0

# the shapes, standing up and facing the camera; never rendered themselves
word = presets.text_object(coll, "Shape Word", "NOVA", size=1.0, loc=(0, 0, -50))
word.data.extrude = 0.0
word.nova_shape.mode, word.nova_shape.points = "OUTLINE", 4000
me = bpy.data.meshes.new("Shape Star")
bm = bmesh.new()
pts = [(math.cos(math.pi / 2 + i * math.pi / 5) * (1.0 if i % 2 == 0 else 0.42),
        math.sin(math.pi / 2 + i * math.pi / 5) * (1.0 if i % 2 == 0 else 0.42), 0) for i in range(10)]
bm.faces.new([bm.verts.new(p) for p in pts])
bm.to_mesh(me)
bm.free()
star = bpy.data.objects.new("Shape Star", me)
star.location, star.rotation_euler, star.hide_render = (0, 0, -50), (math.radians(90), 0, 0), True
coll.objects.link(star)
star.nova_shape.mode, star.nova_shape.points = "OUTLINE", 4000

n = show.nova
# word: gold glitter stars that hang in place; size = 46 / 2.2 = ~21 m
for shell, shape, starkind, count, speed in (("Shell Peony", word, "Chrysanthemum Star", 900, 46.0),
                                             ("Shell Ring", star, "Ring Star", 500, 34.0)):
    k = n.kinds[shell]
    k.death_kind, k.death_pattern, k.death_shape = starkind, "SHAPE", shape
    k.death_count, k.death_speed, k.death_speed_var, k.death_inherit = count, speed, 0.0, 0.0
    s = n.kinds[starkind]
    s.drag_lin, s.drag_quad, s.gravity = 2.2, 0.0, 0.08
    s.life_min, s.life_max = 2.6, 3.0
    s.trail_rate = min(s.trail_rate, 20)  # a little glitter, not enough to blur the letters
launch = {"Launcher Peony": (0, 30), "Launcher Ring": (-30, 110), "Launcher Chrysanthemum": (36, 118)}
for name, (x, frame) in launch.items():
    ob = bpy.data.objects[name]
    ob.location, ob.rotation_euler = (x, 0, 0), (0, 0, 0)
    e = ob.nova_emitter
    e.burst, e.burst_frame, e.spread = 1, frame, 0.0
n.kinds["Shell Chrysanthemum"].death_count = 220

cam = sc.camera
cam.location = (0, -170, 10)
look_at(cam, (0, 0, 66))
cam.data.lens = 26
render_settings(res=(1280, 720), samples=64)
loop("logo_fireworks", [show], 90, 250, step=2, width=640, still_at=135)
