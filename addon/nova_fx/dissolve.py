"""Disintegrate: an object burns away along a moving front.

One number per point decides everything: the dissolve value v (metres). A Geometry Nodes modifier writes it
as the `nova_dissolve` attribute: the distance past a front object (a plane sweeping along its Z axis, or a
sphere growing with its scale), broken up with noise that sticks to the object. Then

  v < 0                  gone (transparent)
  0 <= v < Edge          the burning edge: blackbody glow, hottest at the front
  Edge <= v < Edge+Char  charred: the material darkens toward black
  beyond                 untouched

The material reads the attribute (so it renders anywhere, Cycles or EEVEE, no handlers), and Dissolve Front
emitters read the same evaluated attribute, so embers, ash and flames come off exactly where the surface
went, at the sub-frame moment it crossed zero.
"""

import math

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from mathutils import Vector

ATTR = "nova_dissolve"
MOD = "Nova Dissolve"
GN_TREE = "Nova Dissolve Mask"
SH_TREE = "Nova Dissolve Surface"
COPY = "nova_dissolve_of"  # on material copies: the original material's name


_BUSY = set()  # objects being set up: their property writes must not each re-sync


def _update(self, context):
    ob = self.id_data
    if ob.name in _BUSY:
        return
    if self.enabled:
        sync(ob)
    else:
        remove(ob)


class NovaDissolve(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Disintegrate", default=False, update=_update)
    front: PointerProperty(name="Front", type=bpy.types.Object, update=_update,
                           description="Plane: sweeps along its Z axis, everything behind it is gone. "
                                       "Sphere: everything inside its radius (= the object's X scale) is gone")
    mode: EnumProperty(name="Shape", items=[
        ("PLANE", "Plane", "A front that sweeps along the front object's Z axis"),
        ("SPHERE", "Sphere", "A hole that grows with the front object's scale"),
    ], default="PLANE", update=_update)
    noise: FloatProperty(name="Ragged", default=0.25, min=0, soft_max=5, unit="LENGTH", update=_update,
                         description="How far the noise pushes the front back and forth")
    noise_scale: FloatProperty(name="Noise Scale", default=3.0, min=0.01, soft_max=50, update=_update,
                               description="Size of the front's wiggles (higher = smaller)")
    detail: IntProperty(name="Edge Detail", default=1, min=0, max=5, update=_update,
                        description="Subdivisions so the mask follows the noise on coarse meshes "
                                    "(each level is four times the faces)")
    edge: FloatProperty(name="Edge", default=0.04, min=0.0005, soft_max=1, unit="LENGTH", update=_update,
                        description="Width of the glowing edge")
    char: FloatProperty(name="Char", default=0.12, min=0, soft_max=2, unit="LENGTH", update=_update,
                        description="Width of the scorched band behind the glow")
    temperature: FloatProperty(name="Temperature", default=1500, min=600, soft_max=4000, update=_update,
                               description="Colour of the glowing edge (K)")
    glow: FloatProperty(name="Glow", default=12.0, min=0, soft_max=200, update=_update,
                        description="Emission strength of the edge")
    fine: FloatProperty(name="Fine Edge", default=0.01, min=0, soft_max=0.1, unit="LENGTH", update=_update,
                        description="Extra small-scale raggedness drawn by the material only")


# ------------------------------------------------------------------ geometry nodes: the mask

def _sock(tree, name, kind, in_out="INPUT", default=None, **kw):
    s = tree.interface.new_socket(name, in_out=in_out, socket_type=kind)
    if default is not None:
        s.default_value = default
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def mask_tree():
    tree = bpy.data.node_groups.get(GN_TREE)
    if tree is not None:
        return tree
    tree = bpy.data.node_groups.new(GN_TREE, "GeometryNodeTree")
    _sock(tree, "Geometry", "NodeSocketGeometry")
    _sock(tree, "Geometry", "NodeSocketGeometry", "OUTPUT")
    _sock(tree, "Front", "NodeSocketObject")
    _sock(tree, "Sphere", "NodeSocketBool", default=False)
    _sock(tree, "Ragged", "NodeSocketFloat", default=0.25)
    _sock(tree, "Noise Scale", "NodeSocketFloat", default=3.0)
    _sock(tree, "Detail", "NodeSocketInt", default=1, min_value=0, max_value=5)
    N, L = tree.nodes.new, tree.links.new
    gi, go = N("NodeGroupInput"), N("NodeGroupOutput")

    def math(op, a, b=None, vec=False):
        m = N("ShaderNodeVectorMath" if vec else "ShaderNodeMath")
        m.operation = op
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                m.inputs[i].default_value = x
            else:
                L(x, m.inputs[i])
        return m.outputs["Value" if op in {"DOT_PRODUCT", "LENGTH"} else 0]

    sub = N("GeometryNodeSubdivideMesh")
    L(gi.outputs["Geometry"], sub.inputs["Mesh"])
    L(gi.outputs["Detail"], sub.inputs["Level"])
    pos = N("GeometryNodeInputPosition").outputs[0]
    me = N("GeometryNodeObjectInfo")
    L(N("GeometryNodeSelfObject").outputs[0], me.inputs["Object"])
    pw = N("FunctionNodeTransformPoint")  # world position
    L(pos, pw.inputs["Vector"])
    L(me.outputs["Transform"], pw.inputs["Transform"])
    fr = N("GeometryNodeObjectInfo")
    L(gi.outputs["Front"], fr.inputs["Object"])
    rel = math("SUBTRACT", pw.outputs[0], fr.outputs["Location"], vec=True)
    # plane: distance along the front's Z axis (in metres, whatever the front's scale)
    ax = N("FunctionNodeTransformDirection")
    ax.inputs["Direction"].default_value = (0, 0, 1)
    L(fr.outputs["Transform"], ax.inputs["Transform"])
    axis = math("NORMALIZE", ax.outputs[0], vec=True)
    d_plane = math("DOT_PRODUCT", rel, axis, vec=True)  # ahead of the arrow: solid; behind it: gone
    # sphere: distance outside the radius (the front's X scale)
    sx = N("ShaderNodeSeparateXYZ")
    L(fr.outputs["Scale"], sx.inputs[0])
    d_sphere = math("SUBTRACT", math("LENGTH", rel, vec=True), sx.outputs["X"])
    sw = N("GeometryNodeSwitch")
    sw.input_type = "FLOAT"
    L(gi.outputs["Sphere"], sw.inputs["Switch"])
    L(d_plane, sw.inputs["False"])
    L(d_sphere, sw.inputs["True"])
    # ragged: noise in the object's own space, so it travels with the object
    nz = N("ShaderNodeTexNoise")
    nz.noise_dimensions = "3D"
    nz.inputs["Detail"].default_value = 3.0
    nz.inputs["Roughness"].default_value = 0.55
    L(pos, nz.inputs["Vector"])
    L(gi.outputs["Noise Scale"], nz.inputs["Scale"])
    centred = math("MULTIPLY", math("SUBTRACT", nz.outputs["Factor"], 0.5), 2.0)
    v = math("ADD", sw.outputs[0], math("MULTIPLY", centred, gi.outputs["Ragged"]))
    st = N("GeometryNodeStoreNamedAttribute")
    st.data_type, st.domain = "FLOAT", "POINT"
    st.inputs["Name"].default_value = ATTR
    L(sub.outputs[0], st.inputs["Geometry"])
    L(v, st.inputs["Value"])
    L(st.outputs[0], go.inputs["Geometry"])
    return tree


# ------------------------------------------------------------------ material: the look

def surface_tree():
    tree = bpy.data.node_groups.get(SH_TREE)
    if tree is not None:
        return tree
    tree = bpy.data.node_groups.new(SH_TREE, "ShaderNodeTree")
    _sock(tree, "Shader", "NodeSocketShader")
    _sock(tree, "Shader", "NodeSocketShader", "OUTPUT")
    for name, d in (("Edge", 0.04), ("Char", 0.12), ("Temperature", 1500.0), ("Glow", 12.0), ("Fine", 0.01)):
        _sock(tree, name, "NodeSocketFloat", default=d)
    N, L = tree.nodes.new, tree.links.new
    gi, go = N("NodeGroupInput"), N("NodeGroupOutput")

    def m(op, a, b=None, clamp=False):
        n = N("ShaderNodeMath")
        n.operation, n.use_clamp = op, clamp
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = x
            else:
                L(x, n.inputs[i])
        return n.outputs[0]

    at = N("ShaderNodeAttribute")
    at.attribute_type, at.attribute_name = "GEOMETRY", ATTR
    tc = N("ShaderNodeTexCoord")
    fn = N("ShaderNodeTexNoise")
    fn.inputs["Scale"].default_value = 60.0
    fn.inputs["Detail"].default_value = 2.0
    L(tc.outputs["Object"], fn.inputs["Vector"])
    v = m("ADD", at.outputs["Fac"], m("MULTIPLY", m("MULTIPLY", m("SUBTRACT", fn.outputs["Fac"], 0.5), 2.0),
                                          gi.outputs["Fine"]))
    # solid: a soft step 1 mm wide, so the cut is antialiased
    solid = N("ShaderNodeMapRange")
    solid.interpolation_type = "SMOOTHSTEP"
    solid.inputs["From Min"].default_value, solid.inputs["From Max"].default_value = 0.0, 0.001
    L(v, solid.inputs["Value"])
    near = m("SUBTRACT", 1.0, m("DIVIDE", v, gi.outputs["Edge"]), clamp=True)  # 1 at the front, 0 past the edge
    glow = m("MULTIPLY", m("MULTIPLY", near, near), gi.outputs["Glow"])
    bb = N("ShaderNodeBlackbody")
    L(m("MULTIPLY", gi.outputs["Temperature"], m("ADD", 0.6, m("MULTIPLY", near, 0.4))), bb.inputs[0])
    em = N("ShaderNodeEmission")
    L(bb.outputs[0], em.inputs["Color"])
    L(glow, em.inputs["Strength"])
    char = m("SUBTRACT", 1.0, m("DIVIDE", m("SUBTRACT", v, gi.outputs["Edge"]),
                                m("MAXIMUM", gi.outputs["Char"], 1e-5)), clamp=True)
    burnt = N("ShaderNodeBsdfPrincipled")
    burnt.inputs["Base Color"].default_value = (0.012, 0.009, 0.007, 1)
    burnt.inputs["Roughness"].default_value = 0.95
    mix_char = N("ShaderNodeMixShader")
    L(char, mix_char.inputs[0])
    L(gi.outputs["Shader"], mix_char.inputs[1])
    L(burnt.outputs[0], mix_char.inputs[2])
    add = N("ShaderNodeAddShader")
    L(mix_char.outputs[0], add.inputs[0])
    L(em.outputs[0], add.inputs[1])
    tr = N("ShaderNodeBsdfTransparent")
    cut = N("ShaderNodeMixShader")
    L(solid.outputs["Result"], cut.inputs[0])
    L(tr.outputs[0], cut.inputs[1])
    L(add.outputs[0], cut.inputs[2])
    L(cut.outputs[0], go.inputs["Shader"])
    return tree


def _wrap_material(mat, d):
    """Insert the surface group between the material output and whatever fed it."""
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or \
        next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    g = nt.nodes.get("Nova Dissolve")
    if g is None:
        g = nt.nodes.new("ShaderNodeGroup")
        g.name = g.label = "Nova Dissolve"
        g.node_tree = surface_tree()
        g.location = out.location + Vector((-200, 0))
        src = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].links else None
        if src is None:
            src = nt.nodes.new("ShaderNodeBsdfPrincipled").outputs[0]
        nt.links.new(src, g.inputs["Shader"])
        nt.links.new(g.outputs["Shader"], out.inputs["Surface"])
    for name, val in (("Edge", d.edge), ("Char", d.char), ("Temperature", d.temperature), ("Glow", d.glow),
                      ("Fine", d.fine)):
        g.inputs[name].default_value = val
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"


def _materials(ob):
    """The object's materials as dissolve copies (other objects sharing a material are left alone)."""
    me = ob.data
    if not me.materials:
        base = bpy.data.materials.new(f"{ob.name} Surface")
        base.use_nodes = True
        me.materials.append(base)
    for i, mat in enumerate(me.materials):
        if mat is None:
            mat = bpy.data.materials.new(f"{ob.name} Surface")
            mat.use_nodes = True
        if not mat.get(COPY):
            orig = mat
            mat = orig.copy()
            mat.name = f"{orig.name} (Nova Dissolve)"
            mat[COPY] = orig.name
            if not mat.use_nodes:
                mat.use_nodes = True
        me.materials[i] = mat
        yield mat


# ------------------------------------------------------------------ setup / sync

def sync(ob):
    d = ob.nova_dissolve
    if ob.type != "MESH" or d.front is None:
        return
    mod = ob.modifiers.get(MOD)
    if mod is None:
        mod = ob.modifiers.new(MOD, "NODES")
        mod.node_group = mask_tree()
    from .render import _mod_input
    for name, val in (("Front", d.front), ("Sphere", d.mode == "SPHERE"), ("Ragged", d.noise),
                      ("Noise Scale", d.noise_scale), ("Detail", d.detail)):
        _mod_input(mod, name, val)
    for mat in _materials(ob):
        _wrap_material(mat, d)
    ob.update_tag()


def remove(ob):
    mod = ob.modifiers.get(MOD)
    if mod is not None:
        ob.modifiers.remove(mod)
    me = ob.data
    for i, mat in enumerate(getattr(me, "materials", [])):
        if mat is not None and mat.get(COPY):
            orig = bpy.data.materials.get(mat[COPY])
            me.materials[i] = orig
            if mat.users == 0:
                bpy.data.materials.remove(mat)


def setup(context, ob, frames=(1, 100), mode="PLANE", axis="Z"):
    """Turn on Disintegrate for a mesh: a front plane below it, keyframed to sweep up through it."""
    d = ob.nova_dissolve
    deps = context.evaluated_depsgraph_get()
    corners = [ob.matrix_world @ Vector(c) for c in ob.evaluated_get(deps).bound_box]
    lo = Vector([min(c[i] for c in corners) for i in range(3)])
    hi = Vector([max(c[i] for c in corners) for i in range(3)])
    front = d.front
    if front is None:
        front = bpy.data.objects.new(f"{ob.name} Dissolve Front", None)
        front.empty_display_type = "SINGLE_ARROW" if mode == "PLANE" else "SPHERE"
        front.empty_display_size = max(0.5, (hi - lo).length * 0.4)
        for c in ob.users_collection:
            c.objects.link(front)
    margin = d.noise + d.edge + d.char + 0.05
    center = (lo + hi) / 2
    if mode == "PLANE":
        front.location = (center.x, center.y, lo.z - margin)
        front.keyframe_insert("location", frame=frames[0])
        front.location.z = hi.z + margin
        front.keyframe_insert("location", frame=frames[1])
    else:
        front.location = center
        r = (hi - lo).length / 2 + margin
        front.scale = (0.001, 0.001, 0.001)
        front.keyframe_insert("scale", frame=frames[0])
        front.scale = (r, r, r)
        front.keyframe_insert("scale", frame=frames[1])
    _BUSY.add(ob.name)
    try:
        d.front, d.mode, d.enabled = front, mode, True
    finally:
        _BUSY.discard(ob.name)
    sync(ob)
    return front


# ------------------------------------------------------------------ emission (from sim.emit_frame)

def evaluated(ob, depsgraph):
    """(co local (n,3), tri (m,3), v (n,), tri normals (m,3), tri areas (m,)) of the dissolving mesh."""
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        nv = len(me.vertices)
        co = np.empty(nv * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", tri)
        tri = tri.reshape(-1, 3)
        at = me.attributes.get(ATTR)
        if at is None or at.domain != "POINT" or len(tri) == 0:
            return None
        v = np.empty(nv, np.float32)
        at.data.foreach_get("value", v)
    finally:
        ev.to_mesh_clear()
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    cr = np.cross(b - a, c - a)
    area = np.linalg.norm(cr, axis=1) * 0.5
    nrm = cr / np.maximum(2 * area, 1e-12)[:, None]
    return co, tri, v, nrm, area


def _in_tris(co, tri, sel, weights, n, rng):
    t = sel[np.minimum(np.searchsorted(np.cumsum(weights) / weights.sum(), rng.random(n)), len(sel) - 1)]
    u, w = rng.random(n), rng.random(n)
    flip = u + w > 1
    u[flip], w[flip] = 1 - u[flip], 1 - w[flip]
    bary = np.stack([1 - u - w, u, w], 1).astype(np.float32)
    return t, bary


def crossing(st, ob, depsgraph, density, rng, scale=1.0):
    """Points where the surface dissolved during this frame: (local positions, local normals, t in (0, 1]).
    density: particles per square metre of surface that disappears. st keeps the previous frame's values."""
    data = evaluated(ob, depsgraph)
    if data is None:
        return None
    co, tri, v, nrm, area = data
    prev = st.get("dis_v")
    st["dis_v"] = v
    if prev is None or len(prev) != len(v) or density <= 0:
        return None
    pv, nv = prev[tri], v[tri]
    # a triangle can only have lost surface if one of its corners was solid and one is gone now
    cand = np.nonzero((pv.max(1) > 0) & (nv.min(1) < 0))[0]
    if len(cand) == 0:
        return None
    w = area[cand] * scale * scale
    m = int(min(2_000_000, rng.poisson(density * w.sum())))
    if m == 0:
        return None
    t, bary = _in_tris(co, tri, cand, w, m, rng)
    p0 = (pv[t] * bary).sum(1)
    p1 = (nv[t] * bary).sum(1)
    keep = (p0 > 0) & (p1 <= 0)
    t, bary, p0, p1 = t[keep], bary[keep], p0[keep], p1[keep]
    pos = (co[tri[t]] * bary[:, :, None]).sum(1)
    when = (p0 / np.maximum(p0 - p1, 1e-9)).astype(np.float32)  # linear zero crossing inside the frame
    return pos.astype(np.float32), nrm[t].astype(np.float32), np.clip(when, 1e-4, 1.0)


def band(ob, depsgraph, width, n, rng):
    """n points on the glowing edge (0 <= v < width), for fluid sources. Local positions or None."""
    data = evaluated(ob, depsgraph)
    if data is None:
        return None
    co, tri, v, nrm, area = data
    tv = v[tri]
    cand = np.nonzero((tv.max(1) >= 0) & (tv.min(1) < width))[0]
    if len(cand) == 0:
        return None
    t, bary = _in_tris(co, tri, cand, area[cand], n * 3, rng)
    val = (tv[t] * bary).sum(1)
    keep = (val >= 0) & (val < width)
    pos = (co[tri[t[keep]]] * bary[keep][:, :, None]).sum(1)
    return pos[:n].astype(np.float32) if len(pos) else None


# ------------------------------------------------------------------ operator

class NOVA_OT_dissolve_setup(bpy.types.Operator):
    """Make the selected meshes burn away: a front sweeps through them, with embers and ash"""
    bl_idname = "nova.dissolve_setup"
    bl_label = "Disintegrate"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(name="Front", items=[("PLANE", "Sweep", "A front sweeps up through the object"),
                                            ("SPHERE", "Spread", "A hole grows from the middle")],
                       default="PLANE")
    frames: IntProperty(name="Frames", default=100, min=2, description="How long the front takes to cross")
    particles: BoolProperty(name="Embers & Ash", default=True,
                            description="Also add a Nova system with embers and ash coming off the front")

    @classmethod
    def poll(cls, context):
        return any(o.type == "MESH" for o in context.selected_objects)

    def execute(self, context):
        from . import presets
        f0 = context.scene.frame_current
        for ob in [o for o in context.selected_objects if o.type == "MESH" and not o.nova.is_system]:
            setup(context, ob, (f0, f0 + self.frames), self.mode)
            if self.particles:
                coll = ob.users_collection[0] if ob.users_collection else context.scene.collection
                presets.burn_particles(context, coll, ob)
        return {"FINISHED"}


CLASSES = (NOVA_OT_dissolve_setup,)


def register():
    bpy.utils.register_class(NovaDissolve)
    bpy.types.Object.nova_dissolve = PointerProperty(type=NovaDissolve)


def unregister():
    del bpy.types.Object.nova_dissolve
    bpy.utils.unregister_class(NovaDissolve)
