"""Shapes display: every particle type can be drawn as a mesh of its own (a snowflake, a petal, a leaf, a raindrop,
a ripple ring), instanced on its particles by Geometry Nodes on a companion "<system> Shapes" object.

Orientation per type:
  TUMBLE    random, and turning as the particle travels (angle grows with distance along its path, so a leaf
            that lands stops turning)
  VELOCITY  the shape's Z axis along the motion (raindrops, streaks)
  FLAT      lying flat, turned randomly about Z (ripples, settled flakes)
  UP        no rotation
The instance is scaled by the particle's radius (shape meshes are about 1 unit across) and carries the particle's
colour as the instancer attribute "Cd", so one leaf mesh can be red, orange and yellow.
"""

import math

import bmesh
import bpy
from mathutils import Vector

ALIGN = [
    ("TUMBLE", "Tumble", "Random orientation that turns as the particle travels"),
    ("VELOCITY", "Along Motion", "Point the shape's Z axis along the motion (raindrops)"),
    ("FLAT", "Flat", "Lie flat, turned randomly about Z (ripples)"),
    ("UP", "Upright", "No rotation"),
]


def shapes_object(sysob, create=True):
    name = sysob.name + " Shapes"
    ob = bpy.data.objects.get(name)
    if ob is not None and ob.type == "MESH":
        return ob
    if not create:
        return None
    ob = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    for coll in sysob.users_collection:
        coll.objects.link(ob)
    ob.hide_select = True
    return ob


def _tree(sysob):
    """Build the instancing tree for the system's current types (rebuilt when they change)."""
    n = sysob.nova
    sig = tuple((k.name, k.shape_object.name if k.shape_object else "", k.shape_align, round(k.shape_spin, 4),
                 round(k.shape_scale, 4)) for k in n.kinds)
    name = f"Nova Shapes · {sysob.name}"
    tree = bpy.data.node_groups.get(name)
    if tree is not None and tree.get("sig") == repr(sig):
        return tree
    if tree is None:
        tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.nodes.clear()
    tree.interface.clear()
    tree["sig"] = repr(sig)
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = tree.nodes.new, tree.links.new
    go = N("NodeGroupOutput")
    pts = N("GeometryNodeObjectInfo")
    pts.transform_space = "RELATIVE"
    pts.inputs["Object"].default_value = sysob
    join = N("GeometryNodeJoinGeometry")
    kind_attr = N("GeometryNodeInputNamedAttribute")
    kind_attr.data_type = "INT"
    kind_attr.inputs["Name"].default_value = "kind"
    radius = N("GeometryNodeInputNamedAttribute")
    radius.data_type = "FLOAT"
    radius.inputs["Name"].default_value = "radius"
    vel = N("GeometryNodeInputNamedAttribute")
    vel.data_type = "FLOAT_VECTOR"
    vel.inputs["Name"].default_value = "velocity"
    idn = N("GeometryNodeInputNamedAttribute")
    idn.data_type = "INT"
    idn.inputs["Name"].default_value = "id"
    pos = N("GeometryNodeInputPosition")

    def rnd(seed, lo=0.0, hi=1.0, vec=False):
        r = N("FunctionNodeRandomValue")
        r.data_type = "FLOAT_VECTOR" if vec else "FLOAT"
        L(idn.outputs["Attribute"], r.inputs["ID"])
        r.inputs["Seed"].default_value = seed
        want = "VECTOR" if vec else "VALUE"  # socket order differs between versions: pick by name and type
        for sock in r.inputs:
            if sock.type == want and sock.name in ("Min", "Max"):
                v = lo if sock.name == "Min" else hi
                sock.default_value = (v, v, v) if vec else v
        return next(o for o in r.outputs if o.type == want)

    def vmath(op, a, b=None, scale=None):
        m = N("ShaderNodeVectorMath")
        m.operation = op
        L(a, m.inputs[0])
        if b is not None:
            if isinstance(b, (tuple, list)):
                m.inputs[1].default_value = b
            else:
                L(b, m.inputs[1])
        if scale is not None:
            if isinstance(scale, (int, float)):
                m.inputs["Scale"].default_value = scale
            else:
                L(scale, m.inputs["Scale"])
        return m.outputs[0]

    for ki, k in enumerate(n.kinds):
        sel = N("FunctionNodeCompare")
        sel.data_type, sel.operation = "INT", "EQUAL"
        L(kind_attr.outputs["Attribute"], sel.inputs["A"])
        sel.inputs["B"].default_value = ki
        sep = N("GeometryNodeSeparateGeometry")
        sep.domain = "POINT"
        L(pts.outputs["Geometry"], sep.inputs["Geometry"])
        L(sel.outputs["Result"], sep.inputs["Selection"])
        inst = N("GeometryNodeInstanceOnPoints")
        L(sep.outputs["Selection"], inst.inputs["Points"])
        if k.shape_object is not None:
            src = N("GeometryNodeObjectInfo")
            src.inputs["Object"].default_value = k.shape_object
            src.inputs["As Instance"].default_value = True
            L(src.outputs["Geometry"], inst.inputs["Instance"])
        else:
            ico = N("GeometryNodeMeshIcoSphere")
            ico.inputs["Radius"].default_value = 1.0
            ico.inputs["Subdivisions"].default_value = 1
            L(ico.outputs["Mesh"], inst.inputs["Instance"])
        # rotation
        if k.shape_align == "VELOCITY":
            al = N("FunctionNodeAlignRotationToVector")
            al.axis = "Z"
            L(vel.outputs["Attribute"], al.inputs["Vector"])
            L(al.outputs["Rotation"], inst.inputs["Rotation"])
        elif k.shape_align in {"TUMBLE", "FLAT"}:
            e2r = N("FunctionNodeEulerToRotation")
            if k.shape_align == "FLAT":
                comb = N("ShaderNodeCombineXYZ")
                L(rnd(ki * 13 + 1, 0.0, 2 * math.pi), comb.inputs["Z"])
                L(comb.outputs[0], e2r.inputs["Euler"])
            else:
                # a random start, plus an angle that grows with distance travelled along a random direction
                base = rnd(ki * 13 + 2, 0.0, 2 * math.pi, vec=True)
                axis = rnd(ki * 13 + 3, -1.0, 1.0, vec=True)
                travel = N("ShaderNodeVectorMath")
                travel.operation = "DOT_PRODUCT"
                L(pos.outputs[0], travel.inputs[0])
                L(axis, travel.inputs[1])
                spin = vmath("SCALE", rnd(ki * 13 + 4, -1.0, 1.0, vec=True), scale=None)
                spinf = N("ShaderNodeMath")
                spinf.operation = "MULTIPLY"
                L(travel.outputs["Value"], spinf.inputs[0])
                spinf.inputs[1].default_value = k.shape_spin
                sc = spin.node
                L(spinf.outputs[0], sc.inputs["Scale"])
                L(vmath("ADD", base, spin), e2r.inputs["Euler"])
            L(e2r.outputs["Rotation"], inst.inputs["Rotation"])
        mul = N("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        L(radius.outputs["Attribute"], mul.inputs[0])
        mul.inputs[1].default_value = k.shape_scale
        L(mul.outputs[0], inst.inputs["Scale"])
        L(inst.outputs["Instances"], join.inputs[0])
    L(join.outputs[0], go.inputs["Geometry"])
    return tree


def sync(sysob):
    """Show or hide the Shapes object and keep its tree in step with the system's types."""
    n = sysob.nova
    on = n.display == "SHAPES"
    ob = shapes_object(sysob, create=on)
    if ob is None:
        return
    ob.hide_render = ob.hide_viewport = not on
    if not on:
        return
    mod = ob.modifiers.get("Nova Shapes") or ob.modifiers.new("Nova Shapes", "NODES")
    tree = _tree(sysob)
    if mod.node_group != tree:
        mod.node_group = tree
    ob.matrix_world = sysob.matrix_world.copy()
    ob.update_tag()


# ------------------------------------------------------------------ the shapes themselves (about 1 unit across)

def _object(coll, name, me, mat=None):
    ob = bpy.data.objects.get(name)
    if ob is not None:
        return ob
    ob = bpy.data.objects.new(name, me)
    ob.hide_render = True
    ob.hide_viewport = True
    ob.location = (0, 0, -1000)
    coll.objects.link(ob)
    if mat is not None:
        me.materials.append(mat)
    return ob


def _faces(name, polys):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    for poly in polys:
        bm.faces.new([bm.verts.new(p) for p in poly])
    bm.to_mesh(me)
    bm.free()
    return me


def flake_mesh(name="Nova Flake"):
    """A six-armed dendrite crystal, flat in XY: arms with side branches."""
    polys = []
    w = 0.045
    for a in range(6):
        t = a * math.pi / 3
        c, s = math.cos(t), math.sin(t)

        def rot(x, y):
            return (x * c - y * s, x * s + y * c, 0.0)
        polys.append([rot(0, -w), rot(1.0, -w * 0.6), rot(1.0, w * 0.6), rot(0, w)])
        for r0, ln in ((0.35, 0.28), (0.6, 0.22), (0.82, 0.12)):
            for side in (1, -1):
                bx, by = r0, 0.0
                ex, ey = r0 + ln * math.cos(math.pi / 3), side * ln * math.sin(math.pi / 3)
                dx, dy = -(ey - by), (ex - bx)
                l = math.hypot(dx, dy)
                dx, dy = dx / l * w * 0.5, dy / l * w * 0.5
                polys.append([rot(bx - dx, by - dy), rot(ex - dx, ey - dy), rot(ex + dx, ey + dy), rot(bx + dx, by + dy)])
    return _faces(name, polys)


def petal_mesh(name="Nova Petal"):
    """A cherry-blossom petal: rounded, notched at the tip, cupped a little."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    pts = []
    for i in range(24):
        u = i / 23
        a = math.pi * u
        x = -0.7 + 1.5 * (1 - math.cos(a)) / 2
        half = 0.45 * math.sin(a) ** 0.8
        notch = 0.12 * math.exp(-((u - 1) / 0.08) ** 2)
        pts.append((x - notch, half))
    outline = [(x, y) for x, y in pts] + [(x, -y) for x, y in reversed(pts[1:-1])]
    verts = [bm.verts.new((x, y, 0.18 * (y * y) * 2.0)) for x, y in outline]
    bm.faces.new(verts)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    return me


def leaf_mesh(name="Nova Leaf"):
    """A pointed leaf with a fold along its midrib."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    side = []
    for i in range(16):
        u = i / 15
        x = -0.8 + 1.6 * u
        y = 0.42 * math.sin(math.pi * u) ** 0.9 * (1 - 0.35 * u)
        side.append((x, y))
    mid = [bm.verts.new((x, 0.0, 0.0)) for x, _ in side]
    up = [bm.verts.new((x, y, 0.12 * y)) for x, y in side]
    dn = [bm.verts.new((x, -y, 0.12 * y)) for x, y in side]
    for i in range(15):
        bm.faces.new((mid[i], mid[i + 1], up[i + 1], up[i])) if i not in (0,) else bm.faces.new((mid[0], mid[1], up[1]))
        bm.faces.new((mid[i], dn[i], dn[i + 1], mid[i + 1])) if i not in (0,) else bm.faces.new((mid[0], dn[1], mid[1]))
    stem = [bm.verts.new(p) for p in ((-0.8, -0.015, 0), (-1.0, -0.015, 0), (-1.0, 0.015, 0), (-0.8, 0.015, 0))]
    bm.faces.new(stem)
    bm.to_mesh(me)
    bm.free()
    return me


def drop_mesh(name="Nova Raindrop"):
    """A thin streak along Z (a raindrop smeared by its fall during the exposure)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.04, radius2=0.04, depth=1.0)
    bm.to_mesh(me)
    bm.free()
    return me


def ripple_mesh(name="Nova Ripple"):
    """A thin flat ring of radius 1."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    inner, outer = [], []
    for i in range(48):
        a = 2 * math.pi * i / 48
        inner.append(bm.verts.new((0.94 * math.cos(a), 0.94 * math.sin(a), 0)))
        outer.append(bm.verts.new((math.cos(a), math.sin(a), 0)))
    for i in range(48):
        j = (i + 1) % 48
        bm.faces.new((inner[i], outer[i], outer[j], inner[j]))
    bm.to_mesh(me)
    bm.free()
    return me


def splat_mesh(name="Nova Splat", seed=3):
    """A flat stain with a ragged, spiky rim (blood drops leave these), radius about 1, normal along Z."""
    import random
    rng = random.Random(seed)
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    rim = []
    n = 40
    for i in range(n):
        a = 2 * math.pi * i / n
        r = 0.75 + 0.2 * rng.random() + (0.45 * rng.random() if rng.random() < 0.18 else 0.0)
        rim.append(bm.verts.new((r * math.cos(a), r * math.sin(a), 0.002)))
    c = bm.verts.new((0, 0, 0.004))
    for i in range(n):
        bm.faces.new((c, rim[i], rim[(i + 1) % n]))
    bm.to_mesh(me)
    bm.free()
    return me


def pellet_mesh(name="Nova Pellet"):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    bm.to_mesh(me)
    bm.free()
    return me


def tinted_material(name, base, rough=0.5, trans=0.0, sss=0.0, emit=0.0):
    """Base colour multiplied by the particle colour carried on the instance (Cd, instancer attribute)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    cd = nt.nodes.new("ShaderNodeAttribute")
    cd.attribute_type, cd.attribute_name = "INSTANCER", "Cd"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    mix.inputs["A"].default_value = (*base, 1)
    nt.links.new(cd.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    b.inputs["Transmission Weight"].default_value = trans
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
    if emit:
        nt.links.new(mix.outputs["Result"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = emit
    mat.diffuse_color = (*base, 1)
    return mat
