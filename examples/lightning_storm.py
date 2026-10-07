"""A thunderstorm: three cloud-to-ground strikes over a wet plain. Each bolt is grown by the
dielectric breakdown model: a faint stepped leader branches down, the return stroke floods the channel and
lights the cloud deck from inside, re-strikes run down the main channel only, and the channel cools to
orange as it fades. The second bolt is drawn to the lightning rod on a mast."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from _common import add, look_at, loop, material, nova, render_settings, start

sc = start(frame_end=140)
sparks = add("LIGHTNING", "lightning_storm")   # bolt, impact sparks, camera, cloud deck, night sky, glow
lightning = nova("lightning")
coll = sparks.users_collection[0]
bolt = next(o for o in coll.objects if o.nova_lightning.enabled)
bolt.nova_lightning.seed = 4
bolt.nova_lightning.strike_frame = 66

# wet ground: dark and fairly glossy, so every flash shows up in it
bpy.data.objects["Nova Ground"].data.materials[0] = material("Wet Plain", (0.025, 0.027, 0.03), rough=0.25)

# a mast with a lightning rod; the second bolt is drawn to its tip
mast_mat = material("Mast Steel", (0.3, 0.31, 0.33), rough=0.4, metal=1.0)
bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=22, location=(-26, 22, 11), vertices=12)
bpy.context.object.data.materials.append(mast_mat)
bpy.ops.mesh.primitive_cone_add(radius1=0.12, radius2=0.0, depth=1.5, location=(-26, 22, 22.75), vertices=8)
bpy.context.object.data.materials.append(mast_mat)
rod = bpy.data.objects.new("Rod Tip", None)
rod.location = (-26, 22, 23.5)
coll.objects.link(rod)
bpy.context.view_layer.update()
lightning.add(bpy.context, coll, (-29, 25, 50), name="Bolt To Rod", strike_frame=94, seed=11, target=rod,
              field=0.55, brightness=35, strokes=2)
lightning.add(bpy.context, coll, (40, 70, 50), name="Distant Bolt", strike_frame=118, seed=5, brightness=22,
              strokes=4, stroke_gap=2.5, radius=0.07, light_power=2e5)

render_settings(res=(1280, 720), samples=64)
sc.cycles.volume_step_rate = 4.0
loop("lightning_storm", [sparks], 52, 134, step=1, width=640, still_at=67)
