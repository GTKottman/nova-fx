"""Ready-made effects. Each builder creates a system, its particle types, emitters and helpers."""

import math

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from . import dissolve, lightning, render, shapes_display, sim
from .params import chem

# ------------------------------------------------------------------ building blocks


def _collection(context, name):
    coll = bpy.data.collections.new(name)
    context.scene.collection.children.link(coll)
    return coll


def new_system(context, coll, name, kinds, frame_end=None, **settings):
    pc = bpy.data.pointclouds.new(name)
    ob = bpy.data.objects.new(name, pc)
    coll.objects.link(ob)
    n = ob.nova
    n.is_system = True
    scene = context.scene
    n.frame_start = scene.frame_start
    n.frame_end = frame_end or scene.frame_end
    for kd in kinds:
        k = n.kinds.add()
        for key, val in kd.items():
            setattr(k, key, val)
        k["_prev_name"] = k.name
    for key, val in settings.items():
        if key == "fluid":
            for fk, fv in val.items():
                setattr(n.fluid, fk, fv)
        else:
            setattr(n, key, val)
    render.sync_display(ob)
    render.sync_materials(ob)
    scene.render.use_lock_interface = True  # handlers swap point data while rendering
    return ob


def _empty(coll, name, loc, rot=(0, 0, 0), kind="SPHERE", size=0.1, scale=(1, 1, 1)):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = kind
    ob.empty_display_size = size
    ob.location = loc
    ob.rotation_euler = rot
    ob.scale = scale
    coll.objects.link(ob)
    return ob


def emitter(coll, sysob, name, kind, loc, rot=(0, 0, 0), display="SPHERE", size=0.1, scale=(1, 1, 1), ob=None,
            **em):
    ob = ob or _empty(coll, name, loc, rot, display, size, scale)
    e = ob.nova_emitter
    e.enabled = True
    e.system = sysob
    e.kind = kind
    e.frame_start = sysob.nova.frame_start
    e.frame_end = sysob.nova.frame_end
    for key, val in em.items():
        setattr(e, key, val)
    return ob


def _mesh(coll, name, build, loc=(0, 0, 0), rot=(0, 0, 0), mat=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = rot
    coll.objects.link(ob)
    if mat:
        me.materials.append(mat)
    return ob


def _charred_wood(name="Nova Charred Wood"):
    """Black, cracked bark; the cracks glow like embers (emission masked by Voronoi cell edges)."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.9
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = 22.0
    vor.inputs["Randomness"].default_value = 0.9
    crack = nt.nodes.new("ShaderNodeMapRange")          # thin bright lines along the cell edges
    crack.inputs["From Min"].default_value = 0.0
    crack.inputs["From Max"].default_value = 0.06
    crack.inputs["To Min"].default_value = 1.0
    crack.inputs["To Max"].default_value = 0.0
    noise = nt.nodes.new("ShaderNodeTexNoise")          # not every crack is equally hot
    noise.inputs["Scale"].default_value = 4.0
    heat = nt.nodes.new("ShaderNodeMath")
    heat.operation = "MULTIPLY"
    hot = nt.nodes.new("ShaderNodeMapRange")
    hot.inputs["From Min"].default_value = 0.45
    hot.inputs["From Max"].default_value = 0.7
    strength = nt.nodes.new("ShaderNodeMath")
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = 6.0
    bark = nt.nodes.new("ShaderNodeValToRGB")          # ash-grey to black bark
    bark.color_ramp.elements[0].color = (0.006, 0.005, 0.004, 1)
    bark.color_ramp.elements[1].color = (0.05, 0.045, 0.04, 1)
    L = nt.links.new
    L(vor.outputs["Distance"], crack.inputs["Value"])
    L(noise.outputs["Fac"], hot.inputs["Value"])
    L(crack.outputs["Result"], heat.inputs[0])
    L(hot.outputs["Result"], heat.inputs[1])
    L(heat.outputs["Value"], strength.inputs[0])
    L(strength.outputs["Value"], bsdf.inputs["Emission Strength"])
    L(noise.outputs["Fac"], bark.inputs["Fac"])
    L(bark.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.22, 0.03, 1)
    mat.diffuse_color = (0.02, 0.015, 0.012, 1)
    return mat


def _plain_material(name, color, rough=0.8, emit=None, emit_strength=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if not mat.node_tree:
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1)
        bsdf.inputs["Roughness"].default_value = rough
        if emit:
            bsdf.inputs["Emission Color"].default_value = (*emit, 1)
            bsdf.inputs["Emission Strength"].default_value = emit_strength
    mat.diffuse_color = (*color, 1)
    return mat


def ground(coll, size=20.0, z=0.0, visible=True, name="Nova Ground"):
    ob = _mesh(coll, name, lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2),
               (0, 0, z), mat=_plain_material("Nova Ground", (0.05, 0.05, 0.05), 0.6))
    ob.nova_collider.enabled = True
    ob.nova_collider.shape = "PLANE"
    if not visible:
        ob.hide_render = True
        ob.display_type = "WIRE"
    return ob


def domain(coll, sysob, size, center, resolution, **fluid):
    ob = _mesh(coll, sysob.name + " Domain",
               lambda bm: bmesh.ops.create_cube(bm, size=1.0), center)
    ob.scale = size
    ob.display_type = "BOUNDS"
    ob.hide_render = True
    fl = sysob.nova.fluid
    fl.enabled = True
    fl.domain = ob
    fl.resolution = resolution
    for k, v in fluid.items():
        setattr(fl, k, v)
    return ob


def camera(context, coll, loc, target, lens=35.0):
    cam = bpy.data.cameras.new("Nova Camera")
    cam.lens = lens
    cam.clip_end = 2000
    ob = bpy.data.objects.new("Nova Camera", cam)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    coll.objects.link(ob)
    context.scene.camera = ob
    return ob


def night_world(context, color=(0.0015, 0.002, 0.005)):
    w = bpy.data.worlds.get("Nova Night") or bpy.data.worlds.new("Nova Night")
    if not w.node_tree:
        w.use_nodes = True
    bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs["Color"].default_value = (*color, 1)
        bg.inputs["Strength"].default_value = 1.0
    context.scene.world = w


def day_world(context):
    """A physical sky: clear water needs something bright to refract and reflect."""
    w = bpy.data.worlds.get("Nova Day") or bpy.data.worlds.new("Nova Day")
    if not w.node_tree:
        w.use_nodes = True
    nt = w.node_tree
    bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None)
    if bg is not None and not any(n.type == "TEX_SKY" for n in nt.nodes):
        sky = nt.nodes.new("ShaderNodeTexSky")
        try:
            sky.sun_elevation = math.radians(35)
            sky.sun_rotation = math.radians(-30)
            sky.sun_disc = False  # the scene's own sun lamp is the sun: the sky's disc would double it
        except AttributeError:
            pass
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.35
    context.scene.world = w


def _offset(coll, offset):
    for ob in coll.objects:
        if ob.parent is None and ob.type != "CAMERA":
            ob.location = Vector(ob.location) + offset


# ------------------------------------------------------------------ shared particle types

def bb(name, T, life, size, emit, **kw):
    """Incandescent (blackbody) type."""
    d = dict(name=name, color_mode="BLACKBODY", temp0=T, temp_var=kw.pop("temp_var", 0.1 * T),
             life_min=life[0], life_max=life[1], size_start=size[0], size_end=size[1], emit=emit,
             collide=kw.pop("collide", "NONE"), fade_in=0.0, fade_out=kw.pop("fade_out", 0.15))
    d.update(kw)
    return d


def col(name, color, life, size, emit, **kw):
    d = dict(name=name, color_mode="FIXED", color=color, life_min=life[0], life_max=life[1], size_start=size[0],
             size_end=size[1], emit=emit, collide=kw.pop("collide", "NONE"), fade_in=0.0,
             fade_out=kw.pop("fade_out", 0.35), color_var=kw.pop("color_var", 0.05))
    d.update(kw)
    return d


# ------------------------------------------------------------------ presets

def build_sparkler(context, coll):
    s = new_system(context, coll, "Sparkler", [
        bb("Spark", 2500, (0.15, 0.4), (0.0008, 0.0003), 40, size_var=0.35, drag_quad=25.0, drag_lin=0.5,
           cool=2.5, cool_rad=1.0, emit_var=0.3, gravity=0.6, split_kind="Spark", split_rate=4.0, split_count=3,
           split_speed=1.3, split_inherit=0.5, split_max_gen=3),
        bb("Core Glow", 2900, (0.04, 0.08), (0.004, 0.002), 80, size_var=0.3, emit_var=0.4, gravity=0.0),
    ], display="STREAKS", streak_length=0.015, substeps=3)
    stick_mat = _plain_material("Nova Sparkler Wire", (0.25, 0.25, 0.27), 0.4)
    _mesh(coll, "Sparkler Wire",
          lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.0015, radius2=0.0015,
                                           depth=0.35), (0, 0, 0.9), (0.6, 0, 0), stick_mat)
    tip = Vector((0, 0, 0.9)) + Euler((0.6, 0, 0)).to_matrix() @ Vector((0, 0, 0.12))
    burn_mat = _plain_material("Nova Sparkler Burn", (0.05, 0.04, 0.03), 0.7, (1.0, 0.45, 0.12), 25.0)
    _mesh(coll, "Sparkler Coating",
          lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.004, radius2=0.004,
                                           depth=0.11),
          Vector((0, 0, 0.9)) + Euler((0.6, 0, 0)).to_matrix() @ Vector((0, 0, 0.065)), (0.6, 0, 0), burn_mat)
    emitter(coll, s, "Sparkler Tip", "Spark", tip, size=0.02, shape="SPHERE", radius=0.008, direction="RANDOM",
            rate=700, speed=3.0, speed_var=0.45)
    emitter(coll, s, "Sparkler Core", "Core Glow", tip, size=0.015, shape="SPHERE", radius=0.006,
            direction="RANDOM", rate=400, speed=0.15, speed_var=0.5)
    return s


def build_grinder(context, coll):
    s = new_system(context, coll, "Grinder Sparks", [
        bb("Spark", 2300, (0.6, 1.4), (0.004, 0.0015), 30, drag_quad=0.25, cool=1.2, cool_rad=0.4,
           collide="BOUNCE", bounce=0.35, friction=0.35, hit_kind="Spatter", hit_count=0.7, hit_speed=2.5,
           split_kind="Spatter", split_rate=0.8, split_count=3, split_speed=1.5, split_max_gen=1),
        bb("Spatter", 2100, (0.15, 0.4), (0.0025, 0.001), 20, drag_quad=1.0, cool=3.0, collide="BOUNCE",
           bounce=0.2, friction=0.4),
    ], display="STREAKS", streak_length=0.02, substeps=2)
    ground(coll, 10)
    emitter(coll, s, "Grinder Contact", "Spark", (0, 0, 0.6), (math.radians(115), 0, 0), "SINGLE_ARROW", 0.25,
            shape="POINT", direction="OBJECT_Z", spread=0.18, rate=4000, speed=14, speed_var=0.35)
    return s


def build_fountain(context, coll):
    s = new_system(context, coll, "Fountain", [
        bb("Spark", 2000, (0.9, 1.6), (0.006, 0.002), 25, temp_var=150, drag_quad=0.35, cool=0.8, collide="BOUNCE",
           bounce=0.25, friction=0.3, split_kind="Glitter", split_rate=1.2, split_count=4, split_speed=1.8,
           split_max_gen=1),
        bb("Glitter", 2600, (0.1, 0.35), (0.004, 0.002), 60, drag_quad=1.0, cool=3.0, twinkle_freq=15,
           twinkle_amt=0.7),
    ], display="STREAKS", streak_length=0.03, substeps=2)
    ground(coll, 12)
    emitter(coll, s, "Fountain Nozzle", "Spark", (0, 0, 0.05), (0, 0, 0), "SINGLE_ARROW", 0.3, shape="POINT",
            direction="OBJECT_Z", spread=0.22, rate=3000, speed=8.5, speed_var=0.25)
    return s


# fireworks ----------------------------------------------------------------

def _shell(name, star, count, pattern, speed, trail_rate=90, life=(2.6, 3.1), **kw):
    d = bb("Shell " + name, 1900, life, (0.14, 0.1), 6, temp_var=100, drag_quad=0.006, cool=0.1,
           trail_kind="Lift Spark", trail_rate=trail_rate, trail_inherit=0.05, trail_jitter=1.5,
           death_kind=star, death_count=count, death_pattern=pattern, death_speed=speed, death_speed_var=0.08,
           death_inherit=0.25, fade_out=0.0)
    d.update(kw)
    return d


FIREWORK_KINDS = [
    bb("Lift Spark", 1900, (0.3, 0.7), (0.09, 0.03), 40, temp_var=150, drag_quad=0.3, cool=1.5),
    col("Ember", (1, 0.5, 0.2), (0.3, 0.7), (0.1, 0.0), 40, inherit_color=True, drag_lin=1.5, gravity=0.3,
        fade_out=0.8),
    bb("Gold Glitter", 2000, (0.5, 1.2), (0.1, 0.02), 60, temp_var=200, drag_lin=2.0, gravity=0.4, cool=0.9,
       twinkle_freq=9, twinkle_amt=0.5),
    bb("Willow Trail", 1800, (1.8, 3.0), (0.11, 0.03), 40, temp_var=120, drag_lin=2.5, gravity=0.25, cool=0.45,
       fade_out=0.6),
    col("Crackle", (1, 0.85, 0.6), (0.04, 0.12), (0.4, 0.08), 900, emit_var=0.5, drag_lin=3.0, gravity=0.0,
        fade_out=0.5),
    # stars
    col("Peony Star", chem("STRONTIUM"), (1.6, 2.2), (0.32, 0.2), 300, drag_quad=0.07, trail_kind="Ember",
        trail_rate=25),
    bb("Chrysanthemum Star", 2300, (1.8, 2.4), (0.26, 0.16), 160, drag_quad=0.07, trail_kind="Gold Glitter",
       trail_rate=60, cool=0.2),
    bb("Willow Star", 1900, (3.5, 4.5), (0.2, 0.12), 120, drag_quad=0.25, gravity=0.6, cool=0.12,
       trail_kind="Willow Trail", trail_rate=70),
    bb("Palm Arm", 2200, (2.2, 2.8), (0.4, 0.24), 220, drag_quad=0.04, cool=0.15, trail_kind="Gold Glitter",
       trail_rate=150),
    col("Ring Star", chem("COPPER"), (1.5, 2.0), (0.32, 0.2), 320, drag_quad=0.07, trail_kind="Ember",
        trail_rate=15),
    col("Crossette Star", chem("BARIUM"), (0.9, 1.1), (0.32, 0.28), 260, drag_quad=0.05, fade_out=0.0,
        death_kind="Crossette Piece", death_count=4, death_pattern="CROSS", death_speed=9, death_inherit=0.6),
    col("Crossette Piece", chem("BARIUM"), (0.9, 1.3), (0.26, 0.14), 240, inherit_color=True, drag_quad=0.07,
        trail_kind="Ember", trail_rate=25),
    col("Crackle Star", chem("PURPLE"), (1.4, 1.8), (0.3, 0.2), 280, drag_quad=0.07, death_kind="Crackle",
        death_count=10, death_pattern="RANDOM", death_speed=4),
    col("Strobe Star", (1, 1, 1), (2.0, 2.8), (0.3, 0.22), 300, drag_quad=0.06, twinkle_freq=14,
        twinkle_amt=1.0, color_var=0.0),
    col("Heart Star", (1.0, 0.25, 0.55), (1.8, 2.2), (0.32, 0.2), 300, drag_quad=0.05, gravity=0.6,
        trail_kind="Ember", trail_rate=15),
    col("Rainbow Star", (1, 0.3, 0.1), (1.6, 2.2), (0.32, 0.2), 280, inherit_color=True, drag_quad=0.07,
        trail_kind="Ember", trail_rate=20),
    dict(col("Change Star", chem("BARIUM"), (1.8, 2.4), (0.32, 0.2), 280, drag_quad=0.07, trail_kind="Ember",
             trail_rate=20), color_mode="GRADIENT", color2=chem("STRONTIUM"), color_curve=2.0),
    # shells (rise, then burst)
    _shell("Peony", "Peony Star", 150, "SPHERE", 24),
    _shell("Chrysanthemum", "Chrysanthemum Star", 160, "SPHERE", 26),
    _shell("Willow", "Willow Star", 110, "SPHERE", 22),
    _shell("Palm", "Palm Arm", 8, "PALM", 30, trail_rate=220),
    _shell("Ring", "Ring Star", 64, "RING", 22),
    _shell("Crossette", "Crossette Star", 24, "SPHERE", 20),
    _shell("Crackle", "Crackle Star", 120, "SPHERE", 22),
    _shell("Strobe", "Strobe Star", 140, "SPHERE", 22),
    _shell("Heart", "Heart Star", 90, "HEART", 22),
    dict(_shell("Multicolor", "Rainbow Star", 150, "SPHERE", 24), hue_random=1.0, color_mode="FIXED",
         color=(1, 0.2, 0.1)),
    _shell("Color Change", "Change Star", 150, "SPHERE", 24),
]

SHELLS = ["Peony", "Chrysanthemum", "Willow", "Palm", "Ring", "Crossette", "Crackle", "Strobe", "Heart",
          "Multicolor", "Color Change"]


def build_fireworks(context, coll, shells=None, rate=0.2):
    shells = shells or SHELLS
    s = new_system(context, coll, "Fireworks", FIREWORK_KINDS, display="STREAKS", streak_length=0.04,
                   substeps=2, max_particles=4_000_000)
    span = 120.0
    for i, name in enumerate(shells):
        x = -span / 2 + span * (i + 0.5) / len(shells)
        tilt = math.radians(6) * math.sin(i * 2.1)
        emitter(coll, s, f"Launcher {name}", "Shell " + name, (x, 0, 0), (tilt, 0, 0), "SINGLE_ARROW", 3.0,
                shape="POINT", direction="OBJECT_Z", spread=math.radians(5), rate=rate, random_timing=True,
                speed=48, speed_var=0.08, seed=i * 7 + 1)
    return s


# fire ---------------------------------------------------------------------

def build_campfire(context, coll):
    s = new_system(context, coll, "Campfire", [
        bb("Ember", 1500, (2.0, 4.5), (0.006, 0.003), 18, temp_var=250, cool=0.25, cool_rad=0.5, fluid_drag=3.0,
           drag_lin=0.3, twinkle_freq=4, twinkle_amt=0.5, fade_out=0.3, collide="BOUNCE", bounce=0.1),
        bb("Pop Spark", 2100, (0.3, 0.8), (0.004, 0.0015), 30, drag_quad=0.6, cool=2.0, fluid_drag=0.8),
    ], turb_amp=2.5, turb_freq=1.5, substeps=2,
        fluid=dict(buoy_heat=2.2, buoy_smoke=0.15, vorticity=0.7, turb_amp=7.0, turb_freq=4.0, cool=1.4,
                   cool_rad=0.4, burn_rate=1.8, heat_release=1.6, ignite=0.2, smoke_yield=0.35, expansion=0.4,
                   flame_decay=6.0, smoke_decay=0.15, density_mult=4.0, flame_mult=2.0, heat_mult=1.2))
    domain(coll, s, (1.6, 1.6, 2.6), (0, 0, 1.3), 96)
    ground(coll, 8)
    log_mat = _charred_wood()
    for i in range(4):
        a = i * math.pi / 2 + 0.4
        _mesh(coll, f"Log {i + 1}", lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=10,
                                                                      radius1=0.06, radius2=0.05, depth=0.7),
              (0.18 * math.cos(a), 0.18 * math.sin(a), 0.12), (math.radians(70), 0, a + math.pi / 2), log_mat)
    emitter(coll, s, "Fire Source", "", (0, 0, 0.14), size=0.25, scale=(1, 1, 0.4), shape="SPHERE", radius=0.25,
            rate=0, fl_enabled=True, fl_fuel=1.4, fl_heat=0.8, fl_speed=0.6, fl_noise=0.7, direction="OBJECT_Z")
    emitter(coll, s, "Ember Source", "Ember", (0, 0, 0.2), size=0.2, shape="SPHERE", radius=0.2, rate=25,
            speed=1.2, speed_var=0.6, spread=0.6)
    emitter(coll, s, "Pops", "Pop Spark", (0, 0, 0.18), size=0.15, shape="SPHERE", radius=0.15, rate=10,
            random_timing=True, speed=4, speed_var=0.5, spread=0.9)
    return s


def build_torch(context, coll):
    s = new_system(context, coll, "Torch", [
        bb("Ember", 1600, (1.0, 2.0), (0.004, 0.002), 14, cool=0.4, fluid_drag=4.0, twinkle_freq=5,
           twinkle_amt=0.4),
    ], turb_amp=1.5, turb_freq=3.0,
        fluid=dict(buoy_heat=3.0, buoy_smoke=0.1, vorticity=0.5, turb_amp=3.0, turb_freq=6.0, cool=1.8,
                   cool_rad=0.4, burn_rate=4.0, heat_release=1.6, smoke_yield=0.15, expansion=0.3,
                   flame_decay=8.0, smoke_decay=0.3, density_mult=3.0, flame_mult=9.0, heat_mult=3.0))
    domain(coll, s, (0.8, 0.8, 1.4), (0, 0, 1.62), 80)
    handle_mat = _plain_material("Nova Torch Handle", (0.08, 0.05, 0.03), 0.8)
    _mesh(coll, "Torch Handle", lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.02,
                                                                 radius2=0.035, depth=0.6), (0, 0, 0.62),
          mat=handle_mat)
    emitter(coll, s, "Torch Flame", "Ember", (0, 0, 0.98), size=0.06, shape="SPHERE", radius=0.05, rate=8,
            speed=0.8, fl_enabled=True, fl_fuel=1.2, fl_heat=1.0, fl_speed=1.2, fl_noise=0.6)
    return s


def build_explosion(context, coll):
    s = new_system(context, coll, "Explosion", [
        bb("Debris", 1800, (1.0, 2.5), (0.05, 0.025), 12, drag_quad=0.05, cool=0.7, collide="BOUNCE", bounce=0.3,
           trail_kind="Debris Trail", trail_rate=30, fl_smoke=1.5, fl_heat=0.6),
        bb("Debris Trail", 1600, (0.3, 0.8), (0.035, 0.0), 6, drag_lin=2.0, cool=1.0),
    ], frame_end=120, substeps=2,
        fluid=dict(buoy_heat=3.0, buoy_smoke=0.04, vorticity=1.0, turb_amp=5.0, turb_freq=0.5, cool=0.5,
                   cool_rad=0.12, burn_rate=3.0, heat_release=2.0, ignite=0.15, smoke_yield=1.5, expansion=8.0,
                   flame_decay=2.5, smoke_decay=0.02, density_mult=1.2, flame_mult=3.0, heat_mult=0.8,
                   max_sub=4, smoke_color=(0.22, 0.21, 0.2)))
    domain(coll, s, (16, 16, 16), (0, 0, 8), 96)
    ground(coll, 60)
    emitter(coll, s, "Blast Core", "", (0, 0, 1.5), size=1.2, shape="SPHERE", radius=1.2, rate=0,
            fl_enabled=True, fl_fuel=4.0, fl_heat=1.5, fl_density=0.5, fl_noise=0.6, frame_end=context.scene.frame_start + 1)
    emitter(coll, s, "Debris Burst", "Debris", (0, 0, 1.5), size=0.5, shape="SPHERE", radius=0.5, rate=0,
            burst=150, burst_frame=context.scene.frame_start, direction="NORMAL", speed=24, speed_var=0.5,
            spread=0.3)
    sun = bpy.data.lights.new("Nova Sun", "SUN")
    sun.energy = 2.0
    sun_ob = bpy.data.objects.new("Nova Sun", sun)
    sun_ob.rotation_euler = (math.radians(55), 0, math.radians(-35))
    coll.objects.link(sun_ob)
    return s


# magic --------------------------------------------------------------------

def build_magic_dust(context, coll):
    s = new_system(context, coll, "Magic Dust", [
        dict(name="Dust", color_mode="GRADIENT", color=(0.25, 0.7, 1.0), color2=(0.9, 0.3, 1.0), color_var=0.3,
             life_min=0.8, life_max=2.0, size_start=0.012, size_end=0.0, size_curve=0.7, gravity=-0.05,
             drag_lin=2.5, emit=1.8, emit_var=0.6, twinkle_freq=10, twinkle_amt=0.75, fade_in=0.05,
             fade_out=0.6, collide="NONE"),
        col("Glint", (1, 0.95, 0.85), (0.15, 0.4), (0.03, 0.0), 120, drag_lin=3, gravity=0.0, fade_out=0.8),
    ], turb_amp=3.0, turb_freq=2.0, turb_speed=1.0)
    wand = emitter(coll, s, "Wand Tip", "Dust", (0, 0, 1.2), size=0.05, shape="SPHERE", radius=0.03, rate=1500,
                   direction="RANDOM", speed=0.25, speed_var=0.5, inherit=0.25)
    emitter(coll, s, "Wand Glints", "Glint", (0, 0, 0), size=0.03, shape="SPHERE", radius=0.04, rate=40,
            direction="RANDOM", speed=0.4).parent = wand
    # a figure-eight flight path so it looks right on the first play
    f0, f1 = context.scene.frame_start, context.scene.frame_start + 119
    for i in range(13):
        t = i / 12
        a = t * 2 * math.pi
        wand.location = (1.2 * math.sin(a), 0.6 * math.sin(2 * a), 1.2 + 0.25 * math.sin(3 * a))
        wand.keyframe_insert("location", frame=f0 + t * (f1 - f0))
    return s


def build_embers(context, coll):
    s = new_system(context, coll, "Drifting Embers", [
        bb("Ember", 1400, (4.0, 8.0), (0.012, 0.006), 14, temp_var=250, cool=0.15, cool_rad=0.3, gravity=0.0,
           buoyancy=0.6, drag_lin=1.0, twinkle_freq=3, twinkle_amt=0.4, fade_in=0.1, fade_out=0.3),
    ], turb_amp=1.5, turb_freq=0.6, wind=(1.0, 0, 0))
    _plane = _mesh(coll, "Ember Field", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=3),
                   (0, 0, 0.05))
    _plane.hide_render = True
    _plane.display_type = "WIRE"
    emitter(coll, s, "Ember Field", "Ember", None, ob=_plane, shape="SURFACE", rate=150, speed=0.6, spread=0.5,
            direction="NORMAL")
    return s


def build_vortex(context, coll):
    s = new_system(context, coll, "Energy Vortex", [
        dict(name="Energy", color_mode="GRADIENT", color=(0.2, 0.55, 1.0), color2=(0.75, 0.2, 1.0), color_var=0.25,
             color_curve=0.7, life_min=4, life_max=6, size_start=0.012, size_end=0.004, gravity=0.0, drag_lin=0.8,
             emit=1.6, emit_var=0.5, twinkle_freq=3, twinkle_amt=0.3, fade_in=0.1, fade_out=0.4, collide="NONE"),
    ], turb_amp=0.6, turb_freq=0.8, display="STREAKS", streak_length=0.12)
    emitter(coll, s, "Energy Disc", "Energy", (0, 0, 0), size=3.5, scale=(1, 1, 0.08), shape="SPHERE", radius=3.5,
            rate=1500, direction="RANDOM", speed=0.2)
    for name, t, st, r in (("Vortex", "VORTEX", 5.0, 0.0), ("Core Pull", "ATTRACT", 1.2, 3.0)):
        ob = _empty(coll, name, (0, 0, 0), kind="CIRCLE" if t == "VORTEX" else "SPHERE", size=1.5)
        f = ob.nova_force
        f.enabled, f.type, f.strength, f.radius = True, t, st, r
    return s


def build_snow(context, coll):
    s = new_system(context, coll, "Snow", [
        col("Flake", (0.95, 0.97, 1.0), (15, 20), (0.008, 0.008), 0.0, drag_lin=8.0, collide="STICK",
            fade_out=0.05, color_var=0.0),
    ], turb_amp=1.0, turb_freq=0.3, wind=(0.5, 0, 0), shading="LIT")
    sky = _mesh(coll, "Snow Sky", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=10),
                (0, 0, 10))
    sky.hide_render = True
    sky.display_type = "WIRE"
    emitter(coll, s, "Snow Sky", "Flake", None, ob=sky, shape="SURFACE", rate=800, direction="RANDOM", speed=0.2)
    ground(coll, 20)
    sun = bpy.data.lights.new("Nova Sun", "SUN")
    sun.energy = 3.0
    sun_ob = bpy.data.objects.new("Nova Sun", sun)
    sun_ob.rotation_euler = (math.radians(50), 0, math.radians(30))
    coll.objects.link(sun_ob)
    return s


def build_lightning(context, coll):
    """A cloud-to-ground strike from 50 m (inside the stage's cloud deck), with molten spatter where it lands."""
    s = new_system(context, coll, "Lightning Impact", [
        bb("Spark", 3200, (0.3, 0.9), (0.05, 0.015), 80, drag_quad=0.3, cool=2.5, cool_rad=0.8,
           collide="BOUNCE", bounce=0.3, friction=0.4, split_kind="Spark", split_rate=0.8, split_count=2,
           split_speed=1.5, split_max_gen=1),
    ], display="STREAKS", streak_length=0.03, substeps=2)
    ground(coll, 300)
    em = emitter(coll, s, "Lightning Impact Point", "Spark", (0, 0, 0.05), display="SPHERE", size=0.3,
                 shape="POINT", direction="OBJECT_Z", spread=1.3, rate=0, burst=150, speed=11, speed_var=0.5)
    lightning.add(context, coll, (0, 0, 50), strike_frame=24, impact=em)
    return s


def text_object(coll, name, body, size=1.0, loc=(0, 0, 0), rot=(math.radians(90), 0, 0)):
    """A centred text object standing up facing -Y (the default front view), hidden in renders."""
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    cu.size = size
    ob = bpy.data.objects.new(name, cu)
    ob.location, ob.rotation_euler = loc, rot
    ob.hide_render = True
    ob.display_type = "WIRE"
    coll.objects.link(ob)
    return ob


def build_formation(context, coll):
    """Dust swirls in, assembles into a word, holds, and is released into the turbulence."""
    s = new_system(context, coll, "Particle Logo", [
        dict(name="Mote", color_mode="GRADIENT", color=(0.25, 0.65, 1.0), color2=(1.0, 0.35, 0.85), color_var=0.25,
             color_curve=1.0, life_min=40, life_max=40, size_start=0.012, size_end=0.008, gravity=0.0,
             drag_lin=0.8, emit=5.0, emit_var=0.5, twinkle_freq=4, twinkle_amt=0.4, fade_in=0.02, fade_out=0.05,
             collide="NONE"),
    ], turb_amp=1.2, turb_freq=0.7, turb_speed=0.4)
    logo = text_object(coll, "Logo Text", "NOVA", size=1.6, loc=(0, 0, 1.2))
    logo.nova_shape.mode, logo.nova_shape.points = "SURFACE", 30000
    f0 = s.nova.frame_start
    emitter(coll, s, "Dust Cloud", "Mote", (0, 0, 1.2), size=4.0, scale=(1.4, 0.6, 1.0), shape="SPHERE", radius=4.0,
            rate=0, burst=30000, burst_frame=f0, direction="RANDOM", speed=0.4, speed_var=0.8)
    form = _empty(coll, "Logo Form", (0, 0, 1.2), kind="PLAIN_AXES", size=0.6)
    fc = form.nova_force
    fc.enabled, fc.type, fc.target, fc.snap, fc.damping, fc.system = True, "FORM", logo, 2.5, 0.9, s
    for frame, pull in ((f0, 0.0), (f0 + 20, 0.0), (f0 + 60, 1.0), (f0 + 140, 1.0), (f0 + 160, 0.0)):
        fc.pull = pull
        fc.keyframe_insert("pull", frame=frame)
    return s


def burn_particles(context, coll, ob, name=None):
    """A Nova system with embers and ash coming off a disintegrating object's front."""
    s = new_system(context, coll, name or f"{ob.name} Burn", [
        bb("Ember", 1800, (0.8, 1.8), (0.004, 0.0015), 16, temp_var=250, cool=0.6, cool_rad=0.3, gravity=0.0,
           buoyancy=3.5, drag_lin=1.5, turb=1.0, fluid_drag=2.0, twinkle_freq=6, twinkle_amt=0.5, fade_out=0.4),
        dict(name="Ash", color_mode="GRADIENT", color=(0.05, 0.045, 0.04), color2=(0.012, 0.011, 0.01),
             color_var=0.3, life_min=2.0, life_max=4.0, size_start=0.006, size_end=0.004, size_var=0.5,
             gravity=-0.08, drag_lin=2.5, turb=1.4, fluid_drag=2.0, emit=0.0, fade_in=0.0,
             fade_out=0.5, collide="NONE"),
    ], turb_amp=1.6, turb_freq=1.8, turb_speed=0.8, wind=(0.15, 0, 0), substeps=2, shading="LIT")
    s.nova.frame_start = context.scene.frame_start
    # embers leave upward (hot air), ash peels off the surface
    for kind, density, direction, speed, spread in (("Ember", 1200.0, "OBJECT_Z", 0.8, 1.1),
                                                    ("Ash", 2500.0, "NORMAL", 0.2, 0.6)):
        emitter(coll, s, f"{ob.name} {kind}", kind, ob.location.copy(), display="PLAIN_AXES", size=0.1,
                shape="DISSOLVE", dissolve_source=ob, rate=density, direction=direction, speed=speed,
                speed_var=0.6, spread=spread, frame_start=context.scene.frame_start)
    return s


def build_disintegrate(context, coll):
    """A monkey head burns away from the bottom up: glowing ragged edge, char, embers and ash."""
    me = bpy.data.meshes.new("Burning Monkey")
    bm = bmesh.new()
    bmesh.ops.create_monkey(bm)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Burning Monkey", me)
    ob.location = (0, 0, 1.0)
    coll.objects.link(ob)
    sub = ob.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = sub.render_levels = 2
    mat = _plain_material("Nova Monkey Paint", (0.55, 0.42, 0.3), 0.6)
    me.materials.append(mat)
    context.view_layer.update()
    f0 = context.scene.frame_start
    dissolve.setup(context, ob, (f0 + 10, f0 + 130), "PLANE")
    ob.nova_dissolve.detail = 1
    # a warm key from the front-left and a cool rim, so the surface reads against the dark
    for name, kind, energy, color, loc, size in (("Nova Key", "AREA", 120.0, (1.0, 0.85, 0.7), (-2.2, -2.6, 2.6), 1.5),
                                                 ("Nova Rim", "AREA", 80.0, (0.6, 0.75, 1.0), (2.0, 2.4, 2.2), 1.0)):
        light = bpy.data.lights.new(name, kind)
        light.energy, light.color, light.size = energy, color, size
        lob = bpy.data.objects.new(name, light)
        lob.location = loc
        lob.rotation_euler = (Vector((0, 0, 1.1)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        coll.objects.link(lob)
    return burn_particles(context, coll, ob, name="Disintegrate")


def build_liquid(context, coll):
    """Dam break: a column of water falls, hits a ball and sloshes around a tank."""
    s = new_system(context, coll, "Splash Tank", [
        dict(name="Water", liquid=True, color_mode="FIXED", color=(0.25, 0.5, 0.9), color_var=0.0, life_min=1e5,
             life_max=1e5, size_start=0.01, size_end=0.01, size_var=0.0, emit=0.0, gravity=1.0, fade_in=0.0,
             fade_out=0.0, collide="BOUNCE"),
    ], frame_end=min(context.scene.frame_end, 160), substeps=1, shading="LIT")
    fl = s.nova.fluid
    domain(coll, s, (2.4, 1.0, 1.4), (0, 0, 0.7), 64, mode="LIQUID", flip=0.95, walls="TANK", cfl=1.0, max_sub=8)
    dx = 2.4 / 64
    block = _mesh(coll, "Water Column", lambda bm: bmesh.ops.create_cube(bm, size=1.0), (-0.8, 0, 0.42))
    block.scale = (0.7, 0.9, 0.8)
    block.display_type, block.hide_render = "WIRE", True
    count = int(0.7 * 0.9 * 0.8 / dx ** 3 * 8)  # eight particles per cell
    f0 = s.nova.frame_start
    emitter(coll, s, "Water Column", "Water", None, ob=block, shape="VOLUME", rate=0, burst=count, burst_frame=f0,
            direction="RANDOM", speed=0.0, speed_var=0.0)
    rock_mat = _plain_material("Nova Stone", (0.18, 0.17, 0.16), 0.5)
    ball = _mesh(coll, "Obstacle", lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16,
                                                                          radius=0.22), (0.35, 0.05, 0.22),
                 mat=rock_mat)
    for f in ball.data.polygons:
        f.use_smooth = True
    ball.nova_collider.enabled, ball.nova_collider.shape = True, "SPHERE"
    tank_mat = _plain_material("Nova Tank", (0.35, 0.37, 0.4), 0.4)
    tiles = _plain_material("Nova Tank Tiles", (0.7, 0.72, 0.75), 0.3)
    nt = tiles.node_tree
    if not any(n.type == "TEX_CHECKER" for n in nt.nodes):  # a pattern under the water shows the refraction
        chk = nt.nodes.new("ShaderNodeTexChecker")
        chk.inputs["Scale"].default_value = 12.0
        chk.inputs["Color1"].default_value = (0.75, 0.78, 0.8, 1)
        chk.inputs["Color2"].default_value = (0.25, 0.32, 0.4, 1)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        nt.links.new(tc.outputs["Object"], chk.inputs["Vector"])
        nt.links.new(chk.outputs["Color"], next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"])
    _mesh(coll, "Tank Floor", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0),
          (0, 0, 0.0), mat=tiles).scale = (1.25, 0.55, 1)
    back = _mesh(coll, "Tank Back", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0),
                 (0, 0.52, 0.7), (math.radians(90), 0, 0), tank_mat)
    back.scale = (1.25, 0.75, 1)
    sun = bpy.data.lights.new("Nova Sun", "SUN")
    sun.energy, sun.angle = 3.0, math.radians(2)
    sun_ob = bpy.data.objects.new("Nova Sun", sun)
    sun_ob.rotation_euler = (math.radians(50), 0, math.radians(-30))
    coll.objects.link(sun_ob)
    render.sync_liquid(s)
    return s


def liquid_kind(name, color, viscosity=0.0, **kw):
    d = dict(name=name, liquid=True, color_mode="FIXED", color=color, color_var=0.0, life_min=1e5, life_max=1e5,
             size_start=0.004, size_end=0.004, size_var=0.0, emit=0.0, fade_in=0.0, fade_out=0.0, collide="BOUNCE",
             viscosity=viscosity)
    d.update(kw)
    return d


def liquid_system(context, coll, name, kinds, size, center, resolution, look, frame_end=None, **fluid):
    s = new_system(context, coll, name, kinds, frame_end=frame_end, substeps=1, shading="LIT")
    opts = dict(mode="LIQUID", look=look, flip=0.3, walls="TANK", cfl=3.0, max_sub=16)
    opts.update(fluid)
    domain(coll, s, size, center, resolution, **opts)
    render.sync_liquid(s)  # the surface is sized from the domain's cells: set it up now that there is one
    return s


def nozzle(coll, s, name, kind, loc, radius, speed, dx, rot=(math.radians(180), 0, 0), **em):
    """A liquid source that pours like a bottle: a sphere of the given radius, pointing along -Z by default,
    emitting eight particles per cell of the stream it makes."""
    rate = math.pi * radius * radius * speed / dx ** 3 * 8
    return emitter(coll, s, name, kind, loc, rot, "SINGLE_ARROW", radius * 3, shape="SPHERE", radius=radius,
                   direction="OBJECT_Z", spread=0.0, rate=rate, speed=speed, speed_var=0.0, nozzle=True, **em)


def _light(coll, name, kind, energy, loc, target, size=1.0, color=(1, 1, 1)):
    light = bpy.data.lights.new(name, kind)
    light.energy, light.color = energy, color
    if kind == "AREA":
        light.size = size
    ob = bpy.data.objects.new(name, light)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    coll.objects.link(ob)
    return ob


def build_honey(context, coll):
    """Honey poured from 20 cm onto a plate: the rope buckles and coils as it lands (viscous coiling)."""
    res, height = 100, 0.25
    dx = height / res
    s = liquid_system(context, coll, "Honey Pour", [
        liquid_kind("Honey", (1.0, 0.6, 0.1), viscosity=100.0),
    ], (0.16, 0.16, height), (0, 0, height / 2), res, "HONEY", visc_couple=2)
    nozzle(coll, s, "Honey Nozzle", "Honey", (0, 0, 0.215), 0.005, 0.25, dx)
    plate = _mesh(coll, "Plate", lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=0.075,
                                                                   radius2=0.085, depth=0.006),
                  (0, 0, 0.0), mat=_plain_material("Nova Plate", (0.9, 0.9, 0.88), 0.15))
    for f in plate.data.polygons:
        f.use_smooth = True
    plate.location.z = -0.003
    # a cream studio sweep behind: clear honey needs something light to glow against
    sweep = _mesh(coll, "Backdrop", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5),
                  (0, 0.22, 0.2), (math.radians(90), 0, 0), _plain_material("Nova Backdrop", (0.85, 0.78, 0.66), 0.7))
    sweep.scale = (1.2, 0.8, 1)
    _light(coll, "Nova Key", "AREA", 30.0, (-0.25, -0.3, 0.35), (0, 0, 0.06), 0.25, (1.0, 0.92, 0.8))
    _light(coll, "Nova Back", "AREA", 25.0, (0.1, 0.18, 0.3), (0, 0, 0.1), 0.15, (1.0, 0.8, 0.5))
    return s


def build_lava(context, coll):
    """Lava from a vent runs down a slope: runny and bright where hot, a dark stiff crust where it cools."""
    s = liquid_system(context, coll, "Lava Flow", [
        liquid_kind("Lava", (1, 0.3, 0.05), viscosity=1.5, visc_temp=6.0, color_mode="BLACKBODY", temp0=1450,
                    temp_var=40, cool=0.02, crust=0.4, conduct=0.6, emit=4.0),
    ], (2.4, 1.2, 0.9), (0, 0, 0.45), 96, "LAVA", visc_couple=1, flip=0.2)
    dx = 2.4 / 96
    slope = _mesh(coll, "Slope", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=2.0),
                  (0, 0, 0.22), (0, math.radians(14), 0), _plain_material("Nova Basalt", (0.03, 0.028, 0.027), 0.9))
    slope.nova_collider.enabled, slope.nova_collider.shape = True, "PLANE"
    nozzle(coll, s, "Lava Vent", "Lava", (-0.95, 0, 0.6), 0.08, 0.5, dx, rot=(0, math.radians(110), 0))
    return s


def build_melt(context, coll):
    """Wax letters soften under a heat lamp and slump into a puddle."""
    s = liquid_system(context, coll, "Melting Text", [
        liquid_kind("Wax", (0.95, 0.85, 0.7), viscosity=1e6, visc_temp=60.0, color_mode="FIXED", temp0=300,
                    temp_var=0.0, cool=0.0, conduct=1.2),
    ], (2.0, 0.6, 0.9), (0, 0, 0.45), 100, "PARTICLE", visc_couple=1, flip=0.1)
    word = text_object(coll, "Melting Word", "NOVA", size=0.55, loc=(0, 0, 0.24))
    word.data.extrude = 0.06
    context.view_layer.update()
    me = bpy.data.meshes.new_from_object(word.evaluated_get(context.evaluated_depsgraph_get()))
    solid = bpy.data.objects.new("Melting Word Volume", me)
    solid.matrix_world = word.matrix_world.copy()
    solid.hide_render, solid.display_type = True, "WIRE"
    coll.objects.link(solid)
    bpy.data.objects.remove(word)
    dx = 2.0 / 100
    corners = [solid.matrix_world @ Vector(c) for c in solid.bound_box]
    ext = Vector([max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3)])
    count = int(ext.x * ext.y * ext.z / dx ** 3 * 8 * 0.45)  # letters fill about 45% of their box
    emitter(coll, s, "Melting Word Volume", "Wax", None, ob=solid, shape="VOLUME", rate=0, burst=count,
            burst_frame=s.nova.frame_start, direction="RANDOM", speed=0.0, speed_var=0.0)
    lamp = _empty(coll, "Heat Lamp", (-0.2, -0.1, 0.75), kind="CONE", size=0.15)
    f = lamp.nova_force
    f.enabled, f.type, f.system, f.temperature, f.heat_rate, f.radius, f.falloff = \
        True, "HEAT", s, 700.0, 0.8, 0.45, 2.0
    lamp.location.x = -0.9
    lamp.keyframe_insert("location", frame=s.nova.frame_start)
    lamp.location.x = 0.9
    lamp.keyframe_insert("location", frame=s.nova.frame_start + 140)
    _light(coll, "Nova Lamp Glow", "AREA", 80.0, (0, -0.8, 1.2), (0, 0, 0.2), 0.8, (1.0, 0.85, 0.65))
    return s


def build_slime(context, coll):
    """A blob of slime drops onto a staircase and oozes down it."""
    s = liquid_system(context, coll, "Slime", [
        liquid_kind("Slime", (0.35, 1.0, 0.25), viscosity=25.0),
    ], (1.4, 0.6, 1.1), (0, 0, 0.55), 96, "SLIME", visc_couple=2, flip=0.2)
    dx = 1.4 / 96
    step_mat = _plain_material("Nova Steps", (0.3, 0.3, 0.32), 0.6)
    for i in range(4):
        st = _mesh(coll, f"Step {i + 1}", lambda bm: bmesh.ops.create_cube(bm, size=1.0),
                   (-0.45 + i * 0.3, 0, 0.3 - i * 0.075), mat=step_mat)
        st.scale = (0.3, 0.58, 0.6 - i * 0.15)
        st.location.z = (0.6 - i * 0.15) / 2
        st.nova_collider.enabled, st.nova_collider.shape = True, "BOX"
    blob = _mesh(coll, "Slime Blob", lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12,
                                                                          radius=0.16), (-0.5, 0, 0.95))
    blob.hide_render, blob.display_type = True, "WIRE"
    count = int(4.18879 * 0.16 ** 3 / dx ** 3 * 8)
    emitter(coll, s, "Slime Blob", "Slime", None, ob=blob, shape="VOLUME", rate=0, burst=count,
            burst_frame=s.nova.frame_start, direction="RANDOM", speed=0.0, speed_var=0.0)
    return s


def build_blood(context, coll):
    """A pool of blood wells up on a tiled floor and creeps across it. Pools are only millimetres thick, so this
    is a small, flat, fine domain (3 mm cells); a slight tilt of gravity makes it creep one way."""
    s = liquid_system(context, coll, "Blood", [
        liquid_kind("Blood", (0.25, 0.0, 0.01), viscosity=0.05),  # stage blood: thicker than the real thing
    ], (0.6, 0.6, 0.06), (0, 0, 0.03), 200, "BLOOD", visc_couple=1, flip=0.3, walls="TANK", surface_smooth=14)
    s.nova.gravity = (9.81 * math.sin(math.radians(3)), 0.0, -9.81 * math.cos(math.radians(3)))
    dx = 0.6 / 200
    _mesh(coll, "Floor", lambda bm: bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=0.6),
          (0, 0, 0.0), mat=_plain_material("Nova Tiles", (0.55, 0.55, 0.53), 0.3))
    nozzle(coll, s, "Blood Source", "Blood", (-0.18, 0.02, 0.02), 0.014, 0.12, dx)
    return s


# magic ---------------------------------------------------------------------

def _spin(ob, frames, turns, axis=2):
    """Keyframe a steady spin about a local axis (linear, so it never eases)."""
    rot = list(ob.rotation_euler)
    ob.keyframe_insert("rotation_euler", index=axis, frame=frames[0])
    rot[axis] += turns * 2 * math.pi
    ob.rotation_euler = rot
    ob.keyframe_insert("rotation_euler", index=axis, frame=frames[1])
    _linear(ob)


def _linear(ob):
    ad = ob.animation_data
    if ad is None or ad.action is None:
        return
    try:
        from bpy_extras import anim_utils
        bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
        curves = bag.fcurves if bag else []
    except (ImportError, AttributeError):
        curves = ad.action.fcurves
    for fc in curves:
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"


def _force(coll, name, loc, kind, system, **kw):
    ob = _empty(coll, name, loc, kind="SPHERE" if kind != "VORTEX" else "CIRCLE", size=kw.pop("size", 0.5))
    f = ob.nova_force
    f.enabled, f.type, f.system = True, kind, system
    for k, v in kw.items():
        setattr(f, k, v)
    return ob


def build_portal(context, coll):
    """A spinning ring of sparks: sparks flung off the rim, ribbons of light swirling inside."""
    f0, f1 = context.scene.frame_start, context.scene.frame_end
    sparks = new_system(context, coll, "Portal Sparks", [
        bb("Rim Spark", 2300, (0.35, 0.9), (0.012, 0.003), 30, drag_quad=0.4, cool=1.6, collide="BOUNCE",
           bounce=0.35, friction=0.3, split_kind="Ember", split_rate=0.6, split_count=2, split_speed=0.8,
           split_max_gen=1),
        bb("Ember", 1900, (0.2, 0.6), (0.006, 0.0), 15, drag_quad=1.0, cool=2.0),
    ], display="STREAKS", streak_length=0.025, substeps=2)
    ring = _mesh(coll, "Portal Ring", lambda bm: bmesh.ops.create_circle(bm, cap_ends=False, segments=180,
                                                                         radius=1.1), (0, 0, 1.5),
                 (math.radians(90), 0, 0))
    ring.hide_render = True
    emitter(coll, sparks, None, "Rim Spark", None, ob=ring, shape="VERTS", rate=7000, direction="TANGENT",
            speed=4.5, speed_var=0.4, spread=0.25, inherit=0.0)
    _spin(ring, (f0, f1), -(f1 - f0) / 24 * 0.6)
    ground(coll, 12)
    glow = new_system(context, coll, "Portal Glow", [
        dict(name="Swirl", color_mode="GRADIENT", color=(1.0, 0.55, 0.12), color2=(1.0, 0.85, 0.4), color_var=0.2,
             life_min=0.8, life_max=1.6, size_start=0.006, size_end=0.002, gravity=0.0, drag_lin=1.0, emit=6.0,
             emit_var=0.4, fade_in=0.1, fade_out=0.5, collide="NONE"),
    ], display="RIBBONS", ribbon_frames=10)
    emitter(coll, glow, "Portal Disc", "Swirl", (0, 0, 1.5), (math.radians(90), 0, 0), "CIRCLE", 1.1,
            scale=(1, 1, 0.02), shape="SPHERE", radius=1.05, rate=900, direction="RANDOM", speed=0.2)
    _force(coll, "Portal Swirl", (0, 0, 1.5), "VORTEX", glow, strength=4.0, radius=1.2,
           size=1.1).rotation_euler = (math.radians(90), 0, 0)
    _force(coll, "Portal Pull", (0, 0, 1.5), "ATTRACT", glow, strength=1.5, radius=1.0, falloff=0.0)
    return sparks


def sigil_mesh(name, rings=(1.0, 0.86, 0.5), star=7, marks=28):
    """A spell circle as edges: rings, a star polygon and rune marks between the outer rings."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    def loop(r, n, z=0.0, phase=0.0):
        vs = [bm.verts.new((r * math.cos(phase + 2 * math.pi * i / n), r * math.sin(phase + 2 * math.pi * i / n), z))
              for i in range(n)]
        for i in range(n):
            bm.edges.new((vs[i], vs[(i + 1) % n]))
        return vs

    for r in rings:
        loop(r, 160)
    pts = [bm.verts.new((rings[1] * math.cos(2 * math.pi * i / star + math.pi / 2),
                         rings[1] * math.sin(2 * math.pi * i / star + math.pi / 2), 0)) for i in range(star)]
    step = 3 if star >= 7 else 2
    for i in range(star):
        bm.edges.new((pts[i], pts[(i + step) % star]))
    for i in range(marks):  # little runes: a stroke and a hook, rotated around the band
        a = 2 * math.pi * (i + 0.5) / marks
        c, s = math.cos(a), math.sin(a)
        r0, r1 = rings[1] + 0.025, rings[0] - 0.025
        mid = (r0 + r1) / 2
        k = (i * 7) % 3
        p = [(r0, 0), (r1, 0)] if k == 0 else ([(r0, -0.02), (mid, 0.02), (r1, -0.02)] if k == 1 else
                                               [(r0, 0.02), (r1, 0.02), (mid, -0.03)])
        vs = [bm.verts.new((x * c - y * s, x * s + y * c, 0)) for x, y in p]
        for j in range(len(vs) - 1):
            bm.edges.new((vs[j], vs[j + 1]))
    bm.to_mesh(me)
    bm.free()
    return me


def build_spell_circle(context, coll):
    """Motes drift in and draw a spell circle on the ground; it turns slowly and lights rise from it."""
    f0, f1 = context.scene.frame_start, context.scene.frame_end
    s = new_system(context, coll, "Spell Circle", [
        dict(name="Sigil Mote", color_mode="FIXED", color=(0.3, 0.8, 1.0), color_var=0.15, life_min=60, life_max=60,
             size_start=0.0035, size_end=0.0035, gravity=0.0, drag_lin=1.0, emit=3.5, emit_var=0.3, twinkle_freq=3,
             twinkle_amt=0.4, fade_in=0.05, fade_out=0.02, collide="NONE"),
        dict(name="Rising Mote", color_mode="GRADIENT", color=(0.4, 0.85, 1.0), color2=(0.6, 0.3, 1.0),
             color_var=0.2, life_min=1.5, life_max=3.0, size_start=0.008, size_end=0.0, gravity=-0.12,
             drag_lin=0.6, turb=1.0, force=0.0, emit=5.0, emit_var=0.5, fade_in=0.1, fade_out=0.6, collide="NONE"),
    ], turb_amp=0.8, turb_freq=1.2, turb_speed=0.6)
    sig = bpy.data.objects.new("Sigil", sigil_mesh("Sigil"))
    sig.location = (0, 0, 0.01)
    sig.scale = (1.5, 1.5, 1.5)
    sig.hide_render, sig.display_type = True, "WIRE"
    coll.objects.link(sig)
    sig.nova_shape.mode, sig.nova_shape.points = "EDGES", 60000
    _spin(sig, (f0, f1), (f1 - f0) / 24 * 0.05)
    emitter(coll, s, "Mote Cloud", "Sigil Mote", (0, 0, 1.0), size=2.0, scale=(1.6, 1.6, 0.8), shape="SPHERE",
            radius=2.0, rate=0, burst=60000, burst_frame=f0, direction="RANDOM", speed=0.3)
    form = _force(coll, "Sigil Form", (0, 0, 0), "FORM", s, target=sig, snap=2.5, damping=1.0, size=0.3)
    for fr, pull in ((f0, 0.0), (f0 + 10, 0.0), (f0 + 50, 1.0)):
        form.nova_force.pull = pull
        form.nova_force.keyframe_insert("pull", frame=fr)
    rise = emitter(coll, s, None, "Rising Mote", None, ob=sig, shape="VERTS", rate=400, direction="OBJECT_Z",
                   speed=0.4, speed_var=0.6, spread=0.3, frame_start=f0 + 45)
    rise.nova_emitter.frame_start = f0 + 45
    ground(coll, 12)
    return s


def build_wisps(context, coll):
    """Will-o'-wisps: a few soft lights wander through the dark, drawing trails and shedding motes."""
    s = new_system(context, coll, "Wisps", [
        dict(name="Wisp", color_mode="FIXED", color=(0.45, 1.0, 0.85), color_var=0.25, hue_random=0.08,
             life_min=60, life_max=60, size_start=0.03, size_end=0.03, size_var=0.3, gravity=0.0, drag_lin=0.8,
             turb=1.0, emit=5.0, emit_var=0.3, twinkle_freq=1.2, twinkle_amt=0.35, fade_in=0.03, fade_out=0.02,
             collide="BOUNCE", bounce=0.5, trail_kind="Wisp Mote", trail_rate=25, trail_inherit=0.1,
             trail_jitter=0.08, inherit_color=False),
        dict(name="Wisp Mote", color_mode="FIXED", color=(0.5, 1.0, 0.9), color_var=0.2, life_min=0.6, life_max=1.4,
             size_start=0.006, size_end=0.0, gravity=-0.03, drag_lin=2.0, turb=0.6, emit=4.0, emit_var=0.4,
             fade_in=0.0, fade_out=0.6, collide="NONE", inherit_color=True),
    ], turb_amp=1.4, turb_freq=0.35, turb_speed=0.25, display="RIBBONS", ribbon_frames=24, ribbon_taper=0.05,
        ribbon_heads=True, ribbon_glow=0.25)
    emitter(coll, s, "Wisp Spawn", "Wisp", (0, 0, 1.0), size=1.2, scale=(2.0, 1.2, 0.5), shape="SPHERE",
            radius=1.0, rate=0, burst=7, burst_frame=s.nova.frame_start, direction="RANDOM", speed=0.6)
    ground(coll, 14)
    return s


def build_arcane_orb(context, coll):
    """A floating orb: light orbits it in ribbons and arcs of lightning crackle out to the air around it."""
    f0, f1 = context.scene.frame_start, context.scene.frame_end
    c = (0, 0, 1.4)
    s = new_system(context, coll, "Arcane Orb", [
        dict(name="Orbit", color_mode="GRADIENT", color=(0.7, 0.35, 1.0), color2=(0.3, 0.8, 1.0), color_var=0.2,
             life_min=1.5, life_max=3.0, size_start=0.005, size_end=0.002, gravity=0.0, drag_lin=2.0, emit=2.5,
             emit_var=0.4, fade_in=0.1, fade_out=0.4, collide="NONE"),
    ], display="RIBBONS", ribbon_frames=8, turb_amp=0.3, turb_freq=2.0)
    # terminal orbit speed = spin / drag = 1.2 m/s; the pull supplies the v^2 / r that keeps them circling
    emitter(coll, s, "Orbit Shell", "Orbit", c, size=0.6, shape="SPHERE", radius=0.6, rate=900,
            direction="RANDOM", speed=0.2)
    _force(coll, "Orb Spin", c, "VORTEX", s, strength=2.4, radius=0.0, size=0.7)
    _force(coll, "Orb Pull", c, "ATTRACT", s, strength=2.6, radius=0.0)
    core_mat = _plain_material("Nova Orb Core", (0.05, 0.02, 0.1), 0.2, (0.7, 0.4, 1.0), 25.0)
    orb = _mesh(coll, "Orb", lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.18),
                c, mat=core_mat)
    for p in orb.data.polygons:
        p.use_smooth = True
    # tendrils: short bolts from the orb to points in the air around it, one after another
    import random
    rng = random.Random(3)
    frame = f0 + 6
    i = 0
    while frame < f1 - 10 and i < 10:
        a, e = rng.uniform(0, 2 * math.pi), rng.uniform(-0.6, 0.9)
        r = rng.uniform(0.9, 1.3)
        tgt = _empty(coll, f"Arc Target {i + 1}", (c[0] + r * math.cos(a) * math.cos(e),
                                                   c[1] + r * math.sin(a) * math.cos(e), c[2] + r * math.sin(e)),
                     kind="PLAIN_AXES", size=0.05)
        lightning.add(context, coll, c, name=f"Arc {i + 1}", target=tgt, ground=c[2] - 2.0, strike_frame=int(frame),
                      leader_frames=2, strokes=2, stroke_gap=2.0, afterglow=5.0, radius=0.006, detail=2,
                      roughness=0.3, branching=0.7, brightness=60.0, light_power=400.0, temperature=12000,
                      seed=i * 11 + 2)
        frame += rng.uniform(5, 14)
        i += 1
    return s


def build_spirit_smoke(context, coll):
    """Glowing spirit smoke: mist that shines cyan where it is fresh and fades to violet, with motes."""
    s = new_system(context, coll, "Spirit Smoke", [
        dict(name="Mote", color_mode="GRADIENT", color=(0.4, 0.9, 1.0), color2=(0.7, 0.3, 1.0), color_var=0.2,
             life_min=1.5, life_max=3.0, size_start=0.006, size_end=0.0, gravity=0.0, drag_lin=0.5,
             fluid_drag=2.0, emit=6.0, emit_var=0.5, twinkle_freq=4, twinkle_amt=0.5, fade_in=0.1, fade_out=0.5,
             collide="NONE"),
    ], turb_amp=0.5, turb_freq=1.5,
        fluid=dict(buoy_heat=1.0, buoy_smoke=-0.05, vorticity=0.9, turb_amp=4.0, turb_freq=2.0, turb_speed=0.6,
                   cool=0.5, cool_rad=0.0, burn_rate=0.0, smoke_decay=0.25, density_mult=4.0, flame_mult=8.0,
                   gas_look="SPIRIT"))
    domain(coll, s, (2.0, 2.0, 3.0), (0, 0, 1.5), 96)
    emitter(coll, s, "Spirit Source", "Mote", (0, 0, 0.25), size=0.3, shape="SPHERE", radius=0.25, rate=80,
            speed=0.3, speed_var=0.6, spread=0.8, fl_enabled=True, fl_density=1.2, fl_heat=0.8, fl_fuel=0.0,
            fl_speed=0.6, fl_noise=0.7)
    ground(coll, 12)
    return s


# weather -------------------------------------------------------------------

def _glass_material(name="Nova Glass"):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = _plain_material(name, (1, 1, 1), 0.01)
        b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        b.inputs["Transmission Weight"].default_value = 1.0
        b.inputs["IOR"].default_value = 1.5
    return mat

def _sun(coll, energy=3.0, rot=(50, 0, 30)):
    sun = bpy.data.lights.new("Nova Sun", "SUN")
    sun.energy = energy
    ob = bpy.data.objects.new("Nova Sun", sun)
    ob.rotation_euler = tuple(math.radians(a) for a in rot)
    coll.objects.link(ob)
    return ob


def _sky_emitter(coll, s, name, kind, size, height, rate, **em):
    sky = _mesh(coll, name, lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2),
                (0, 0, height))
    sky.hide_render, sky.display_type = True, "WIRE"
    return emitter(coll, s, name, kind, None, ob=sky, shape="SURFACE", rate=rate, **em)


def _shape(coll, name, me, mat):
    return shapes_display._object(coll, name, me, mat)


def flake(name, size, drag, **kw):
    d = col(name, (0.95, 0.97, 1.0), (30, 40), (size, size), 0.0, drag_lin=drag, collide="STICK", fade_out=0.02,
            color_var=0.02)
    d.update(kw)
    return d


def build_powder_snow(context, coll):
    """Fine, dry powder: thousands of tiny flakes drifting and swirling."""
    s = new_system(context, coll, "Powder Snow", [flake("Powder", 0.004, 6.0, size_var=0.5)],
                   turb_amp=1.6, turb_freq=0.5, turb_speed=0.4, wind=(0.3, 0.1, 0), shading="LIT")
    _sky_emitter(coll, s, "Powder Sky", "Powder", 12, 8, 4000, direction="RANDOM", speed=0.2)
    ground(coll, 20)
    _sun(coll, 2.5)
    return s


def build_wet_snow(context, coll):
    """Big wet flakes: six-armed crystals that rock and tumble on the way down and lie where they land."""
    flake_ob = _shape(coll, "Snowflake Shape", shapes_display.flake_mesh(),
                      shapes_display.tinted_material("Nova Snowflake", (0.95, 0.97, 1.0), 0.35, sss=0.4))
    s = new_system(context, coll, "Wet Snow", [
        dict(flake("Flake", 0.016, 7.0, size_var=0.35), shape_object=flake_ob, shape_align="TUMBLE",
             shape_spin=3.0),
    ], turb_amp=0.7, turb_freq=0.4, turb_speed=0.3, wind=(0.2, 0, 0), shading="LIT", display="SHAPES")
    _sky_emitter(coll, s, "Snow Sky", "Flake", 8, 6, 350, direction="RANDOM", speed=0.1)
    ground(coll, 16)
    _sun(coll, 2.5)
    return s


def build_blizzard(context, coll):
    """A blizzard: snow driven sideways by a strong, gusting wind, streaking past."""
    s = new_system(context, coll, "Blizzard", [
        flake("Driven Snow", 0.003, 2.5, size_var=0.5, life_min=4, life_max=6, collide="NONE"),
    ], turb_amp=4.0, turb_freq=0.25, turb_speed=1.2, wind=(11.0, 1.5, -0.5), shading="LIT", display="STREAKS",
        streak_length=0.03)
    box = _mesh(coll, "Blizzard Source", lambda bm: bmesh.ops.create_cube(bm, size=1.0), (-12, 0, 3))
    box.scale = (2, 14, 6)
    box.hide_render, box.display_type = True, "WIRE"
    emitter(coll, s, "Blizzard Source", "Driven Snow", None, ob=box, shape="VOLUME", rate=40000,
            direction="RANDOM", speed=2.0)
    ground(coll, 40)
    _sun(coll, 1.2, (70, 0, 20))
    return s


def build_sleet(context, coll):
    """Sleet: icy pellets falling fast, bouncing off the ground and chipping."""
    pellet = _shape(coll, "Sleet Shape", shapes_display.pellet_mesh(),
                    shapes_display.tinted_material("Nova Ice", (0.85, 0.9, 0.95), 0.08, trans=0.6))
    s = new_system(context, coll, "Sleet", [
        dict(col("Pellet", (0.9, 0.95, 1.0), (4, 6), (0.0025, 0.0025), 0.0, drag_quad=0.12, collide="BOUNCE",
                 bounce=0.45, friction=0.3, hit_kind="Ice Chip", hit_count=0.6, hit_speed=1.0, color_var=0.0),
             shape_object=pellet, shape_align="TUMBLE"),
        dict(col("Ice Chip", (0.9, 0.95, 1.0), (0.3, 0.8), (0.0012, 0.0012), 0.0, drag_quad=0.5, collide="BOUNCE",
                 bounce=0.2, color_var=0.0), shape_object=pellet, shape_align="TUMBLE"),
    ], turb_amp=0.4, turb_freq=0.3, wind=(1.0, 0, 0), shading="LIT", display="SHAPES", substeps=2)
    _sky_emitter(coll, s, "Sleet Sky", "Pellet", 8, 7, 2500, direction="RANDOM", speed=0.5)
    ground(coll, 16)
    _sun(coll, 2.0)
    return s


def build_snow_globe(context, coll):
    """A shaken snow globe: flakes swirl inside the glass and settle slowly on the little scene inside."""
    flake_ob = _shape(coll, "Globe Flake Shape", shapes_display.flake_mesh("Nova Globe Flake"),
                      shapes_display.tinted_material("Nova Snowflake", (0.95, 0.97, 1.0), 0.35, sss=0.4))
    f0 = context.scene.frame_start
    s = new_system(context, coll, "Snow Globe", [
        dict(flake("Globe Flake", 0.006, 4.0, size_var=0.4), shape_object=flake_ob, shape_align="TUMBLE",
             shape_spin=20.0),
    ], gravity=(0, 0, -1.5), turb_amp=1.2, turb_freq=3.0, turb_speed=0.8, shading="LIT", display="SHAPES")
    # the glass and the scene inside it (the flakes move in liquid: weak gravity, strong drag)
    glass = _mesh(coll, "Globe Glass", lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24,
                                                                          radius=0.5), (0, 0, 0.62),
                  mat=_glass_material())
    for p in glass.data.polygons:
        p.use_smooth = True
    glass.nova_collider.enabled, glass.nova_collider.shape = True, "SHELL"
    base = _mesh(coll, "Globe Base", lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=0.42,
                                                                      radius2=0.36, depth=0.2), (0, 0, 0.1),
                 mat=_plain_material("Nova Globe Base", (0.12, 0.05, 0.03), 0.4))
    floor = _mesh(coll, "Globe Floor", lambda bm: bmesh.ops.create_circle(bm, cap_ends=True, segments=48,
                                                                          radius=0.44), (0, 0, 0.26),
                  mat=_plain_material("Nova Globe Snow", (0.9, 0.92, 0.95), 0.7))
    floor.nova_collider.enabled, floor.nova_collider.shape = True, "PLANE"
    tree = _mesh(coll, "Globe Tree", lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=0.1,
                                                                      radius2=0.0, depth=0.32), (0.05, 0.05, 0.42),
                 mat=_plain_material("Nova Globe Tree", (0.03, 0.18, 0.06), 0.6))
    tree.nova_collider.enabled, tree.nova_collider.shape = True, "MESH"
    emitter(coll, s, "Globe Shake", "Globe Flake", (0, 0, 0.4), size=0.3, shape="SPHERE", radius=0.3, rate=0,
            burst=4000, burst_frame=f0, direction="RANDOM", speed=1.4, speed_var=0.6)
    _light(coll, "Nova Key", "AREA", 60.0, (-0.8, -1.0, 1.4), (0, 0, 0.6), 0.6, (1.0, 0.95, 0.9))
    _light(coll, "Nova Rim", "AREA", 40.0, (0.7, 0.9, 1.0), (0, 0, 0.6), 0.5, (0.7, 0.8, 1.0))
    return s


def build_rain(context, coll):
    """Rain: streaking drops that burst into splashes on a wet surface; the splashes ring it with ripples."""
    water = shapes_display.tinted_material("Nova Rain", (0.8, 0.85, 0.9), 0.05, trans=0.9)
    drop = _shape(coll, "Raindrop Shape", shapes_display.drop_mesh(), water)
    pellet = _shape(coll, "Splash Shape", shapes_display.pellet_mesh("Nova Splash Drop"), water)
    ring = _shape(coll, "Ripple Shape", shapes_display.ripple_mesh(),
                  shapes_display.tinted_material("Nova Ripple", (0.75, 0.8, 0.85), 0.05))
    s = new_system(context, coll, "Rain", [
        dict(col("Rain", (1, 1, 1), (3, 3), (0.12, 0.12), 0.0, drag_quad=0.02, collide="DIE", hit_kind="Splash",
                 hit_count=4, hit_speed=1.4, color_var=0.0), shape_object=drop, shape_align="VELOCITY",
             shape_scale=1.6),
        dict(col("Splash", (1, 1, 1), (0.2, 0.5), (0.0025, 0.0015), 0.0, collide="DIE", hit_kind="Ripple",
                 hit_count=0.5, hit_speed=0.0, color_var=0.0), shape_object=pellet, shape_align="UP"),
        dict(col("Ripple", (1, 1, 1), (0.5, 0.9), (0.005, 0.09), 0.0, gravity=0.0, drag_lin=60.0, collide="STICK",
                 size_curve=0.6, color_var=0.0), shape_object=ring, shape_align="FLAT"),
    ], wind=(0.6, 0, 0), shading="LIT", display="SHAPES", substeps=2)
    _sky_emitter(coll, s, "Rain Sky", "Rain", 8, 7, 3000, direction="RANDOM", speed=0.0)
    for ob in s.users_collection[0].objects:
        if ob.name == "Rain Sky":
            ob.nova_emitter.direction, ob.nova_emitter.speed = "OBJECT_Z", 0.0
    s.nova.kinds["Rain"].life_min = s.nova.kinds["Rain"].life_max = 3.0
    puddle = ground(coll, 16)
    puddle.data.materials[0] = _plain_material("Nova Wet Ground", (0.04, 0.04, 0.045), 0.05)
    _sun(coll, 0.8, (60, 0, 30))
    return s


def build_sakura(context, coll):
    """Cherry blossoms: pink petals drift on the breeze, fluttering as they fall, and gather on the ground."""
    petal = _shape(coll, "Petal Shape", shapes_display.petal_mesh(),
                   shapes_display.tinted_material("Nova Petal", (1, 1, 1), 0.45, sss=0.3))
    s = new_system(context, coll, "Cherry Blossoms", [
        dict(col("Petal", (1.0, 0.72, 0.8), (20, 30), (0.016, 0.016), 0.0, drag_lin=3.5, collide="STICK",
                 color_var=0.15, size_var=0.3, fade_out=0.02, turb=1.4), shape_object=petal, shape_align="TUMBLE",
             shape_spin=9.0),
    ], turb_amp=2.0, turb_freq=0.7, turb_speed=0.6, wind=(1.4, 0.4, 0), shading="LIT", display="SHAPES")
    canopy = emitter(coll, s, "Blossom Canopy", "Petal", (-2.5, 0, 4), size=1.5, scale=(2.0, 2.0, 0.8),
                     shape="SPHERE", radius=1.5, rate=450, direction="RANDOM", speed=0.4)
    ground(coll, 20).data.materials[0] = _plain_material("Nova Grass", (0.1, 0.18, 0.06), 0.8)
    _sun(coll, 1.4, (45, 0, -40))
    return s


def build_autumn(context, coll):
    """Autumn leaves in reds, oranges and yellows tumble down on a gusting wind and settle on the ground."""
    leaf = _shape(coll, "Leaf Shape", shapes_display.leaf_mesh(),
                  shapes_display.tinted_material("Nova Leaf", (1, 1, 1), 0.55, sss=0.15))
    s = new_system(context, coll, "Autumn Leaves", [
        dict(col("Leaf", (0.95, 0.42, 0.08), (20, 30), (0.05, 0.05), 0.0, drag_lin=2.6, collide="STICK",
                 color_var=0.35, hue_random=0.07, size_var=0.25, fade_out=0.02, turb=1.2), shape_object=leaf,
             shape_align="TUMBLE", shape_spin=5.0),
    ], turb_amp=1.6, turb_freq=0.5, turb_speed=0.5, wind=(1.0, 0, 0), shading="LIT", display="SHAPES")
    emitter(coll, s, "Tree Crown", "Leaf", (-2, 0, 4.5), size=1.8, scale=(2.2, 2.2, 1.0), shape="SPHERE",
            radius=1.8, rate=150, direction="RANDOM", speed=0.3)
    ground(coll, 20).data.materials[0] = _plain_material("Nova Earth", (0.12, 0.08, 0.05), 0.85)
    _sun(coll, 1.5, (40, 0, 30))
    return s


# liquid effects ------------------------------------------------------------

def build_splatter(context, coll):
    """Blood splatter: a spray of drops that break up in flight and leave ragged stains where they land, flat on
    the wall and the floor alike."""
    blood = shapes_display.tinted_material("Nova Blood Drop", (1, 1, 1), 0.12)
    drop = _shape(coll, "Blood Drop Shape", shapes_display.pellet_mesh("Nova Blood Pellet"), blood)
    splat = _shape(coll, "Stain Shape", shapes_display.splat_mesh(), blood)
    f0 = context.scene.frame_start
    s = new_system(context, coll, "Blood Splatter", [
        dict(col("Drop", (0.22, 0.0, 0.01), (2, 3), (0.004, 0.004), 0.0, drag_quad=0.15, collide="DIE",
                 hit_kind="Stain", hit_count=1, hit_speed=0.0, color_var=0.05, size_var=0.6, split_kind="Drop",
                 split_rate=1.5, split_count=2, split_speed=0.6, split_inherit=0.9, split_max_gen=2),
             shape_object=drop, shape_align="VELOCITY", shape_scale=1.0),
        dict(col("Stain", (0.16, 0.0, 0.008), (60, 60), (0.012, 0.012), 0.0, gravity=0.0, collide="STICK",
                 color_var=0.05, size_var=0.6, fade_out=0.0), shape_object=splat, shape_align="VELOCITY"),
    ], shading="LIT", display="SHAPES", substeps=3)
    wall_mat = _plain_material("Nova Plaster", (0.75, 0.74, 0.72), 0.7)
    floor = ground(coll, 6)
    floor.data.materials[0] = _plain_material("Nova Concrete Floor", (0.55, 0.54, 0.52), 0.6)
    wall = _mesh(coll, "Wall", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.5),
                 (0, 0.9, 1.5), (math.radians(90), 0, 0), wall_mat)
    wall.nova_collider.enabled, wall.nova_collider.shape = True, "PLANE"  # turned +90 about X: +Z faces the room
    emitter(coll, s, "Impact", "Drop", (0, -0.4, 1.3), (math.radians(-70), 0, 0), "SINGLE_ARROW", 0.3,
            shape="SPHERE", radius=0.03, direction="OBJECT_Z", spread=0.32, rate=0, burst=2200, burst_frame=f0 + 2,
            speed=6.5, speed_var=0.6)
    _sun(coll, 2.0, (55, 0, -25))
    return s


def build_ink(context, coll):
    """Ink dropped into a tank of still water sinks in curling, billowing tendrils."""
    s = new_system(context, coll, "Ink", [
        dict(name="Speck", color_mode="FIXED", color=(0.05, 0.1, 0.5), life_min=1, life_max=1, emit=0.0,
             collide="NONE"),
    ], fluid=dict(buoy_heat=0.0, buoy_smoke=0.5, vorticity=1.6, turb_amp=0.5, turb_freq=12.0, turb_speed=0.3,
                  smoke_decay=0.0, cool=0.0, burn_rate=0.0, density_mult=400.0, gas_look="INK",
                  ink_color=(0.02, 0.05, 0.45), closed_floor=True))
    domain(coll, s, (0.44, 0.44, 0.64), (0, 0, 0.34), 128)
    f0 = context.scene.frame_start
    emitter(coll, s, "Ink Drop", "", (0.02, 0.0, 0.62), (math.radians(180), 0, 0), "SINGLE_ARROW", 0.05,
            shape="SPHERE", radius=0.012, rate=0, direction="OBJECT_Z", fl_enabled=True, fl_density=3.0,
            fl_heat=0.0, fl_fuel=0.0, fl_speed=0.35, fl_noise=0.3, frame_end=f0 + 24)
    # backlit on white, the way ink-in-water is photographed (a glass tank would only frost and soften it)
    _light(coll, "Nova Backlight", "AREA", 120.0, (0, 0.9, 0.4), (0, 0, 0.35), 0.8)
    _light(coll, "Nova Key", "AREA", 40.0, (-0.8, -0.8, 0.8), (0, 0, 0.35), 0.5)
    back = _mesh(coll, "Backdrop", lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0),
                 (0, 0.6, 0.5), (math.radians(90), 0, 0), _plain_material("Nova White Sweep", (0.95, 0.95, 0.95), 0.6))
    back.scale = (2, 1, 1)
    return s


def build_whitewater(context, coll):
    """A wall of water crashes over a block: spray thrown off the crest, foam riding the surface, bubbles rising."""
    white = (0.95, 0.97, 1.0)
    s = new_system(context, coll, "Whitewater", [
        dict(name="Water", liquid=True, color_mode="FIXED", color=(0.25, 0.5, 0.9), life_min=1e5, life_max=1e5,
             size_start=0.01, size_end=0.01, size_var=0.0, emit=0.0, fade_in=0.0, fade_out=0.0, collide="BOUNCE",
             spray_kind="Spray", spray_rate=6.0, bubble_kind="Bubble", bubble_rate=1.5, ww_speed=1.4),
        col("Spray", white, (0.6, 1.4), (0.004, 0.002), 0.0, drag_quad=0.6, liq_contact="DIE", death_kind="Foam",
            death_count=1, death_speed=0.0, death_inherit=0.2, collide="DIE", color_var=0.0, fade_out=0.2),
        col("Foam", white, (2.0, 4.0), (0.006, 0.004), 0.0, liq_contact="RIDE", collide="STICK", color_var=0.0,
            fade_out=0.4, size_var=0.5),
        col("Bubble", white, (1.0, 2.5), (0.003, 0.003), 0.0, gravity=-0.4, fluid_drag=6.0, air_contact="DIE",
            collide="NONE", color_var=0.0, fade_out=0.1),
    ], frame_end=min(context.scene.frame_end, 160), substeps=1, shading="LIT")
    domain(coll, s, (3.0, 1.0, 1.4), (0, 0, 0.7), 96, mode="LIQUID", flip=0.95, walls="TANK", cfl=1.0, max_sub=8)
    dx = 3.0 / 96
    block = _mesh(coll, "Water Wall", lambda bm: bmesh.ops.create_cube(bm, size=1.0), (-1.15, 0, 0.5))
    block.scale = (0.6, 0.94, 0.95)
    block.display_type, block.hide_render = "WIRE", True
    emitter(coll, s, "Water Wall", "Water", None, ob=block, shape="VOLUME", rate=0,
            burst=int(0.6 * 0.94 * 0.95 / dx ** 3 * 8), burst_frame=s.nova.frame_start, direction="RANDOM",
            speed=0.0, speed_var=0.0)
    rock = _mesh(coll, "Breakwater", lambda bm: bmesh.ops.create_cube(bm, size=1.0), (0.35, 0, 0.18),
                 mat=_plain_material("Nova Stone", (0.18, 0.17, 0.16), 0.5))
    rock.scale = (0.3, 0.94, 0.36)
    rock.nova_collider.enabled, rock.nova_collider.shape = True, "BOX"
    floor = ground(coll, 8)  # spray thrown out of the tank lands here (and dies)
    floor.data.materials[0] = _plain_material("Nova Wet Ground", (0.04, 0.04, 0.045), 0.05)
    _sun(coll, 3.0, (50, 0, -30))
    render.sync_liquid(s)
    return s


def build_empty(context, coll):
    s = new_system(context, coll, "Nova System", [
        dict(name="Particle", color_mode="BLACKBODY", temp0=2400, life_min=1, life_max=2, emit=20),
    ])
    emitter(coll, s, "Nova Emitter", "Particle", (0, 0, 0), shape="POINT", rate=500, speed=4, spread=0.4)
    return s


PRESETS = [
    ("FIREWORKS", "Fireworks Show", "Eleven shell types: peony, chrysanthemum, willow, palm, ring, crossette, "
                                    "crackle, strobe, heart, multicolor, colour change", build_fireworks),
    ("SPARKLER", "Sparkler", "Branching incandescent iron sparks", build_sparkler),
    ("CAMPFIRE", "Campfire", "Fluid fire with combustion, embers riding the flow, popping sparks", build_campfire),
    ("TORCH", "Torch", "Small licking flame on a handle", build_torch),
    ("EXPLOSION", "Explosion", "Expanding fireball with debris trailing smoke", build_explosion),
    ("GRINDER", "Grinder Sparks", "Directional spark spray that bounces and spatters", build_grinder),
    ("FOUNTAIN", "Spark Fountain", "Gerb fountain with glitter", build_fountain),
    ("MAGIC", "Magic Dust", "Twinkling trail behind a moving wand", build_magic_dust),
    ("EMBERS", "Drifting Embers", "Ambient embers carried by wind and heat", build_embers),
    ("VORTEX", "Energy Vortex", "Particles swirling around a vortex force", build_vortex),
    ("SNOW", "Snow", "Lit snowfall that settles", build_snow),
    ("POWDER", "Powder Snow", "Fine dry powder drifting and swirling", build_powder_snow),
    ("WETSNOW", "Wet Snow", "Big six-armed flakes that rock and tumble down and lie where they land",
     build_wet_snow),
    ("BLIZZARD", "Blizzard", "Snow driven sideways by a strong gusting wind", build_blizzard),
    ("SLEET", "Sleet", "Icy pellets that fall fast, bounce and chip", build_sleet),
    ("GLOBE", "Snow Globe", "A shaken snow globe: flakes swirl inside the glass and settle", build_snow_globe),
    ("RAIN", "Rain", "Streaking rain that splashes and rings a wet surface with ripples", build_rain),
    ("SAKURA", "Cherry Blossoms", "Pink petals drift and flutter on the breeze and gather on the ground",
     build_sakura),
    ("AUTUMN", "Autumn Leaves", "Red, orange and yellow leaves tumble down on the wind and settle",
     build_autumn),
    ("LIGHTNING", "Lightning", "Branching cloud-to-ground strike: stepped leader, return strokes, afterglow",
     build_lightning),
    ("FORMATION", "Particle Logo", "Dust assembles into a word (any text, logo or mesh), holds, then scatters",
     build_formation),
    ("LIQUID", "Splash Tank", "FLIP liquid: a column of water falls around an obstacle and sloshes in a tank",
     build_liquid),
    ("HONEY", "Honey Pour", "Thick honey poured onto a plate: the stream buckles and coils as it lands",
     build_honey),
    ("LAVA", "Lava Flow", "Glowing lava runs down a slope and grows a dark crust as it cools", build_lava),
    ("MELT", "Melting Text", "Wax letters soften under a moving heat lamp and slump into a puddle", build_melt),
    ("SLIME", "Slime", "A blob of slime drops onto steps and oozes down them", build_slime),
    ("BLOOD", "Blood", "Blood runs off a ledge and spreads into a pool", build_blood),
    ("PORTAL", "Portal", "A spinning ring flings sparks while ribbons of light swirl inside it", build_portal),
    ("SPELL", "Spell Circle", "Motes draw a turning spell circle on the ground; lights rise from it",
     build_spell_circle),
    ("WISPS", "Wisps", "Will-o'-wisps wander through the dark, drawing trails and shedding motes", build_wisps),
    ("ORB", "Arcane Orb", "Light orbits a floating orb while arcs of lightning crackle out from it",
     build_arcane_orb),
    ("SPIRIT", "Spirit Smoke", "Glowing mist that shines where it is fresh and fades violet, with motes",
     build_spirit_smoke),
    ("SPLATTER", "Blood Splatter", "A spray of blood drops that break up in flight and stain the wall and floor",
     build_splatter),
    ("INK", "Ink in Water", "Ink dropped into still water sinks in curling, billowing tendrils", build_ink),
    ("WHITEWATER", "Whitewater", "A wall of water crashes over a block: spray, foam riding the surface, bubbles",
     build_whitewater),
    ("DISINTEGRATE", "Burn Away", "An object burns away along a ragged glowing front, shedding embers and ash",
     build_disintegrate),
    ("EMPTY", "Empty System", "One type, one emitter: start from scratch", build_empty),
]


def build(context, key, setup_scene=False):
    _k, label, _d, fn = next(p for p in PRESETS if p[0] == key)
    coll = _collection(context, "Nova " + label)
    sysob = fn(context, coll)
    cursor = context.scene.cursor.location.copy()
    if cursor.length > 1e-6:
        _offset(coll, cursor)
    if setup_scene:
        setup_stage(context, coll, key, cursor)
    sim.free_cache(sysob)
    return sysob


STAGES = {
    "FIREWORKS": ((0, -150, 12), (0, 0, 62), 28, True),
    "SPARKLER": ((0.35, -0.85, 1.1), (0, 0, 0.98), 50, True),
    "CAMPFIRE": ((0, -3.2, 1.0), (0, 0, 0.7), 40, True),
    "TORCH": ((0, -2.0, 1.4), (0, 0, 1.3), 50, True),
    "EXPLOSION": ((0, -38, 5), (0, 0, 6.5), 35, "DUSK"),
    "GRINDER": ((2.5, -2.5, 1.0), (0, -0.6, 0.3), 35, True),
    "FOUNTAIN": ((0, -9, 2.0), (0, 0, 2.2), 35, True),
    "MAGIC": ((0, -4.5, 1.4), (0, 0, 1.2), 40, True),
    "EMBERS": ((0, -8, 2.0), (0, 0, 2.0), 35, True),
    "VORTEX": ((0, -8.5, 5.5), (0, 0, 0), 35, True),
    "SNOW": ((0, -14, 2.5), (0, 0, 2.5), 35, "DUSK"),
    "LIGHTNING": ((0, -95, 7), (0, 0, 23), 30, True),
    "FORMATION": ((0, -9, 1.3), (0, 0, 1.2), 35, True),
    "DISINTEGRATE": ((0, -4.2, 1.3), (0, 0, 1.15), 45, True),
    "PORTAL": ((0.6, -5.2, 1.4), (0, 0, 1.4), 35, True),
    "SPLATTER": ((0.9, -1.9, 1.35), (0, 0.6, 0.9), 35, "DAY"),
    "INK": ((0, -1.25, 0.36), (0, 0, 0.34), 45, "DAY"),
    "WHITEWATER": ((0.6, -4.2, 1.4), (0, 0, 0.4), 32, "DAY"),
    "POWDER": ((0, -5, 1.6), (0, 0, 1.8), 35, "DUSK"),
    "WETSNOW": ((0, -2.6, 1.3), (0, 0, 1.2), 40, "DUSK"),
    "BLIZZARD": ((6, -8, 1.6), (0, 0, 1.6), 28, "DUSK"),
    "SLEET": ((0, -5, 1.2), (0, 0, 0.8), 35, "DUSK"),
    "GLOBE": ((0, -2.2, 0.75), (0, 0, 0.55), 50, "DUSK"),
    "RAIN": ((0, -6, 1.0), (0, 0, 0.5), 32, "DUSK"),
    "SAKURA": ((0.5, -4.2, 1.6), (-0.6, 0, 1.9), 35, "DAY"),
    "AUTUMN": ((0.5, -4.2, 1.6), (-0.6, 0, 1.8), 35, "DAY"),
    "SPELL": ((0, -3.6, 2.9), (0, 0, 0.1), 32, True),
    "WISPS": ((0, -5.0, 1.3), (0, 0, 1.0), 35, True),
    "ORB": ((0, -4.0, 1.5), (0, 0, 1.4), 40, True),
    "SPIRIT": ((0, -5.5, 1.6), (0, 0, 1.4), 35, True),
    "LIQUID": ((0.4, -3.6, 1.5), (0, 0, 0.35), 32, "DAY"),
    "HONEY": ((0.0, -0.46, 0.13), (0, 0, 0.11), 35, "DAY"),
    "LAVA": ((0.5, -1.9, 1.0), (-0.3, 0, 0.3), 32, "DUSK"),
    "MELT": ((0, -2.4, 0.7), (0, 0, 0.25), 40, "DUSK"),
    "SLIME": ((0.9, -2.2, 1.2), (0, 0, 0.35), 32, "DAY"),
    "BLOOD": ((0.15, -0.55, 0.38), (0.0, 0, 0.0), 35, "DAY"),
    "EMPTY": ((0, -10, 3), (0, 0, 2), 35, False),
}


def cloud_deck(coll, z0, z1, size=400.0, density=0.06, name="Nova Cloud Deck"):
    """A slab of procedural storm cloud (volume), for flashes to light from inside."""
    ob = _mesh(coll, name, lambda bm: bmesh.ops.create_cube(bm, size=1.0), (0, 0, 0.5 * (z0 + z1)))
    ob.scale = (size, size, z1 - z0)
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.035  # world metres: billows ~30 m across
    noise.inputs["Detail"].default_value = 6.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.42, 0.68
    # thin out toward the bottom of the slab so the base reads as a ragged cloud base
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    base = nt.nodes.new("ShaderNodeMapRange")
    base.inputs["From Min"].default_value, base.inputs["From Max"].default_value = -0.5, -0.1
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    dens = nt.nodes.new("ShaderNodeMath")
    dens.operation = "MULTIPLY"
    dens.inputs[1].default_value = density
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.55, 0.58, 0.65, 1)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    L = nt.links.new
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    L(geo.outputs["Position"], noise.inputs["Vector"])
    L(noise.outputs["Fac"], ramp.inputs["Fac"])
    L(tc.outputs["Object"], sep.inputs[0])
    L(sep.outputs["Z"], base.inputs["Value"])
    L(ramp.outputs["Color"], mul.inputs[0])
    L(base.outputs[0], mul.inputs[1])
    L(mul.outputs[0], dens.inputs[0])
    L(dens.outputs[0], vol.inputs["Density"])
    L(vol.outputs[0], out.inputs["Volume"])
    ob.data.materials.append(mat)
    return ob


def setup_stage(context, coll, key, offset):
    loc, target, lens, night = STAGES[key]
    camera(context, coll, Vector(loc) + offset, Vector(target) + offset, lens)
    if key == "LIGHTNING":
        cloud_deck(coll, 42, 60).location += offset
    if night == "DAY":
        day_world(context)
    elif night == "DUSK":
        night_world(context, (0.06, 0.07, 0.1))
    elif night:
        night_world(context)
    if night != "DAY":
        render.setup_glow(context.scene)
