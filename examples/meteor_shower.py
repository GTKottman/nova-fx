"""A custom effect built from scratch with the Python API (no preset): burning meteors streak
down, leave incandescent trails, and burst into sparks when they hit the ground.

    One system, three particle types, one emitter, one collider - about 30 lines."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, look_at, loop, material, render_settings, start

sc = start(frame_end=150)
sky = add("EMPTY", "meteor_shower")           # an empty system to fill in
n = sky.nova
n.kinds.clear()

def kind(**kw):
    k = n.kinds.add()
    for key, val in kw.items():
        setattr(k, key, val)
    k["_prev_name"] = k.name
    return k

# a meteor: hot (Planck colour), drags a trail, bursts on impact
kind(name="Meteor", color_mode="BLACKBODY", temp0=3200, temp_var=400, cool=0.2, life_min=3, life_max=4,
     size_start=0.06, size_end=0.04, emit=60, drag_quad=0.002, collide="DIE",
     trail_kind="Trail", trail_rate=180, trail_inherit=0.05, trail_jitter=0.4,
     hit_kind="Spark", hit_count=60, hit_speed=9)
kind(name="Trail", color_mode="BLACKBODY", temp0=2400, temp_var=300, cool=1.8, cool_rad=1.0,
     life_min=0.5, life_max=1.2, size_start=0.035, size_end=0.0, emit=25, drag_lin=1.5, gravity=0.2,
     collide="NONE", fade_out=0.5)
kind(name="Spark", color_mode="BLACKBODY", temp0=2600, temp_var=300, cool=1.5, life_min=0.6, life_max=1.6,
     size_start=0.02, size_end=0.006, emit=40, drag_quad=0.5, collide="BOUNCE", bounce=0.35, friction=0.3,
     split_kind="Spark", split_rate=1.5, split_count=2, split_speed=2.0, split_max_gen=1)
n.display = "STREAKS"
n.streak_length = 0.03
n.substeps = 2

# meteors enter high up, travelling down and across
em = bpy.data.objects["Nova Emitter"]
em.location = (-14, 30, 26)
em.rotation_euler = (math.radians(130), 0, math.radians(-35))
e = em.nova_emitter
e.kind, e.shape, e.radius = "Meteor", "SPHERE", 6.0
e.rate, e.random_timing, e.speed, e.speed_var, e.spread = 2.2, True, 26, 0.15, math.radians(6)

bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
ground = bpy.context.object
ground.data.materials.append(material("Basalt", (0.02, 0.018, 0.017), rough=0.6))
ground.nova_collider.enabled = True
ground.nova_collider.shape = "PLANE"

cam = sc.camera
cam.location = (0, -22, 3.2)
look_at(cam, (0, 6, 6))
cam.data.lens = 24
render_settings(res=(1280, 720), samples=96)
loop("meteor_shower", [sky], 60, 131, step=2, width=640, still_at=118)
