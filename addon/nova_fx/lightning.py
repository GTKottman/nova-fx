"""Lightning: a branching bolt grown by the dielectric breakdown model in the core, drawn as curves.

The core grows the channel on a lattice (nv_lightning). Here the tree is pruned of tiny side branches,
split into polylines (the main channel first), given fractal detail below the lattice scale and written to a
Curves object with per-point attributes: nova_birth (when the stepped leader reached the point, 0..1),
nova_main (1 on the channel that connects) and nova_weight (share of the current a branch carries). The
material and two flash lights are driven by keyframes, so the bolt renders anywhere without handlers.

Timeline of a cloud-to-ground strike: a faint stepped leader branches down over a few frames, the return
stroke floods the main channel and its branches when it connects, a few re-strikes follow down the main
channel only (dart leaders take the hot path, not the branches), and the channel cools from blue-white plasma
to orange as it fades.
"""

import ctypes as C
import math

import bpy
import numpy as np
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty
from mathutils import Vector

from . import core

MAT = "Nova Lightning"
_BUSY = set()  # bolts being rebuilt (property writes inside a rebuild must not trigger another)


def _rebuild_cb(self, context):
    ob = self.id_data
    if ob.name not in _BUSY and self.enabled:
        rebuild(ob)


def _animate_cb(self, context):
    ob = self.id_data
    if ob.name not in _BUSY and self.enabled:
        animate(ob)


class NovaLightning(bpy.types.PropertyGroup):
    enabled: BoolProperty(default=False)
    # shape
    seed: IntProperty(name="Seed", default=1, min=0, update=_rebuild_cb)
    ground: FloatProperty(name="Ground", default=0.0, unit="LENGTH", update=_rebuild_cb,
                          description="World height the bolt strikes when there is no target")
    target: PointerProperty(name="Strike Target", type=bpy.types.Object, update=_rebuild_cb,
                            description="Optional: the bolt is drawn to this object's origin and strikes it")
    branching: FloatProperty(name="Branching", default=0.5, min=0, max=1, update=_rebuild_cb,
                             description="How readily side branches split off (growth exponent 16 down to 8)")
    field: FloatProperty(name="Directness", default=0.3, min=0, max=1, update=_rebuild_cb,
                         description="Strength of the cloud-to-ground field against the channel's own charge: "
                                     "higher strikes straighter")
    segment: FloatProperty(name="Step", default=0.0, min=0, soft_max=5, unit="LENGTH", update=_rebuild_cb,
                           description="Length of one leader step (0 = automatic, height / 130)")
    prune: IntProperty(name="Min Branch", default=4, min=1, max=100, update=_rebuild_cb,
                       description="Side branches with fewer steps than this are dropped")
    detail: IntProperty(name="Detail", default=2, min=0, max=4, update=_rebuild_cb,
                        description="Levels of fractal kinks below the step length")
    roughness: FloatProperty(name="Roughness", default=0.25, min=0, max=0.6, update=_rebuild_cb,
                             description="How far each fractal kink bends")
    radius: FloatProperty(name="Radius", default=0.05, min=0.0005, soft_max=1, unit="LENGTH", update=_rebuild_cb,
                          description="Main channel radius; branches are thinner")
    # timing (frames)
    strike_frame: IntProperty(name="Strike Frame", default=20, update=_animate_cb,
                              description="Frame the return stroke connects")
    leader_frames: IntProperty(name="Leader", default=8, min=0, max=200, update=_animate_cb,
                               description="Frames the stepped leader takes to come down")
    strokes: IntProperty(name="Strokes", default=3, min=1, max=10, update=_animate_cb,
                         description="Return strokes down the same channel (the flicker)")
    stroke_gap: FloatProperty(name="Stroke Gap", default=3.0, min=0.5, soft_max=20, update=_animate_cb,
                              description="Average frames between strokes")
    afterglow: FloatProperty(name="Afterglow", default=10.0, min=0, soft_max=60, update=_animate_cb,
                             description="Frames the channel takes to cool and fade after the last stroke")
    # look
    brightness: FloatProperty(name="Brightness", default=40.0, min=0, soft_max=500, update=_animate_cb)
    branch_glow: FloatProperty(name="Branch Glow", default=0.35, min=0, max=1, update=_animate_cb,
                               description="Brightness of the branches in the first stroke, relative to the channel")
    temperature: FloatProperty(name="Temperature", default=25000, min=1000, soft_max=40000, update=_animate_cb,
                               description="Plasma temperature (K): sets the colour; the afterglow cools to 3000 K")
    light_power: FloatProperty(name="Flash Power", default=3e5, min=0, soft_max=1e8, unit="POWER",
                               update=_animate_cb, description="Peak power of the flash lights")
    impact: PointerProperty(name="Impact Emitter", type=bpy.types.Object,
                            description="Nova emitter moved to the strike point and burst on the strike frame")


# ------------------------------------------------------------------ growth

def grow(lt, start, ground_z, target=None, max_nodes=20000):
    """Run the core. Returns (positions (n, 3), parent (n,), connected)."""
    goal_z = target.z if target is not None else ground_z
    h = lt.segment or max(0.02, (start.z - goal_z) / 130.0)
    eta = 16.0 - 8.0 * lt.branching
    t = target if target is not None else Vector((0, 0, 0))
    p = np.array([start.x, start.y, start.z, ground_z, h, eta, lt.field, lt.seed,
                  1.0 if target is not None else 0.0, t.x, t.y, t.z], np.float32)
    pos = np.zeros(3 * max_nodes, np.float32)
    par = np.zeros(max_nodes, np.int32)
    n = core.lib().nv_lightning(core.fptr(p), max_nodes, core.fptr(pos), par.ctypes.data_as(C.POINTER(C.c_int)))
    m = abs(n)
    return pos[:3 * m].reshape(-1, 3).astype(np.float64), par[:m].copy(), n > 0, h


def analyze(par, connected, prune):
    """Subtree sizes, the main channel (root to the strike point) and the nodes to keep."""
    n = len(par)
    size = np.ones(n, np.int64)
    for i in range(n - 1, 0, -1):  # children always come after their parent
        size[par[i]] += size[i]
    main = np.zeros(n, bool)
    if connected:
        i = n - 1
        while i >= 0:
            main[i] = True
            i = par[i]
    keep = main | (size >= prune)  # sizes only grow toward the root, so a kept node's parent is kept
    keep[0] = True
    return size, main, keep


def chains(par, size, main, keep):
    """Split the kept tree into polylines: follow the heaviest child (the main channel first); every other
    child starts a new chain at its branch point. Returns lists of node indices."""
    n = len(par)
    kids = [[] for _ in range(n)]
    for i in range(1, n):
        if keep[i]:
            kids[par[i]].append(i)
    out, stack = [], [0]
    while stack:
        s = stack.pop()
        line = [s] if s == 0 else [par[s], s]
        cur = s
        while kids[cur]:
            ks = sorted(kids[cur], key=lambda k: (main[k], size[k]), reverse=True)
            stack.extend(ks[1:])
            cur = ks[0]
            line.append(cur)
        if len(line) > 1:
            out.append(line)
    return out


def _fractal(pts, attrs, levels, rough, rng):
    """Midpoint displacement: each level inserts a kinked midpoint in every segment."""
    for _ in range(levels):
        a, b = pts[:-1], pts[1:]
        seg = b - a
        ln = np.linalg.norm(seg, axis=1, keepdims=True)
        off = rng.normal(size=seg.shape)
        off -= (np.sum(off * seg, axis=1, keepdims=True) / np.maximum(ln ** 2, 1e-12)) * seg  # perpendicular
        off /= np.maximum(np.linalg.norm(off, axis=1, keepdims=True), 1e-12)
        mid = 0.5 * (a + b) + off * ln * rough * rng.uniform(0.3, 1.0, size=(len(seg), 1))
        new = np.empty((2 * len(pts) - 1, 3))
        new[0::2], new[1::2] = pts, mid
        pts = new
        for k, v in attrs.items():
            nv = np.empty(2 * len(v) - 1)
            nv[0::2], nv[1::2] = v, 0.5 * (v[:-1] + v[1:])
            attrs[k] = nv
    return pts, attrs


def rebuild(ob):
    """Grow the bolt and rewrite its curves, then its animation."""
    lt = ob.nova_lightning
    _BUSY.add(ob.name)
    try:
        mw = ob.matrix_world
        start = mw.translation.copy()
        target = lt.target.matrix_world.translation.copy() if lt.target else None
        P, par, ok, h = grow(lt, start, lt.ground, target)
        rng = np.random.default_rng(lt.seed * 7919 + 17)
        n = len(P)
        if n < 2:
            return
        # break the lattice up: jitter every node but the root and the strike point
        jit = rng.uniform(-0.35, 0.35, size=P.shape) * h
        jit[0] = 0
        if ok:
            jit[-1] = 0
        P = P + jit
        size, main, keep = analyze(par, ok, lt.prune)
        side = keep & ~main
        big = size[side].max() if side.any() else 1
        weight = np.where(main, 1.0, 0.2 + 0.6 * np.sqrt(size / big))
        birth = np.arange(n) / max(1, n - 1)
        inv = mw.inverted()
        Ploc = np.array([inv @ Vector(p) for p in P])
        cv = ob.data
        cv.remove_curves()
        lines, sizes = [], []
        for line in chains(par, size, main, keep):
            idx = np.array(line)
            a = {"birth": birth[idx], "main": main[idx].astype(float), "weight": weight[idx]}
            if idx[0] != 0 or not main[idx[1]]:  # a branch: the junction point takes the branch's look
                a["main"][0], a["weight"][0] = a["main"][1], a["weight"][1]
            pts, a = _fractal(Ploc[idx], a, lt.detail, lt.roughness, rng)
            lines.append((pts, a))
            sizes.append(len(pts))
        cv.add_curves(sizes)
        cv.set_types(type="POLY")
        pos = np.concatenate([l[0] for l in lines]).astype(np.float32)
        cv.position_data.foreach_set("vector", pos.ravel())
        for key in ("birth", "main", "weight"):
            vals = np.concatenate([l[1][key] for l in lines]).astype(np.float32)
            name = "nova_" + key
            at = cv.attributes.get(name) or cv.attributes.new(name, "FLOAT", "POINT")
            at.data.foreach_set("value", vals)
        m = np.concatenate([l[1]["main"] for l in lines])
        w = np.concatenate([l[1]["weight"] for l in lines])
        rad = (lt.radius * np.where(m > 0.5, 1.0, 0.25 + 0.45 * w)).astype(np.float32)
        at = cv.attributes.get("radius") or cv.attributes.new("radius", "FLOAT", "POINT")
        at.data.foreach_set("value", rad)
        cv.update_tag()
        # where it lands, and where the flash lights go
        if ok:
            ob["nova_strike"] = tuple(P[-1])
        elif "nova_strike" in ob:
            del ob["nova_strike"]
        chan = P[main] if ok else P
        top, low = Vector(chan[0]), Vector(chan[int(len(chan) * 0.7)] if ok else chan[-1])
        _place_lights(ob, top, low)
        if lt.impact and ok:
            lt.impact.location = Vector(P[-1]) + Vector((0, 0, 0.05))
        if not cv.materials:
            cv.materials.append(material(ob))
    finally:
        _BUSY.discard(ob.name)
    animate(ob)


# ------------------------------------------------------------------ look

def _node(nt, t, loc, **props):
    n = nt.nodes.new(t)
    n.location = loc
    for k, v in props.items():
        setattr(n, k, v)
    return n


def material(ob):
    """Additive plasma: transparent + emission, so the bolt glows without blocking anything."""
    name = f"{MAT} · {ob.name}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    L = nt.links.new
    attr = {}
    for i, key in enumerate(("birth", "main", "weight")):
        attr[key] = _node(nt, "ShaderNodeAttribute", (-1400, 300 - 160 * i), attribute_name="nova_" + key,
                          attribute_type="GEOMETRY")
    val = {}
    for i, key in enumerate(("leader", "flash", "bflash", "lglow", "temp", "bright", "branch")):
        v = _node(nt, "ShaderNodeValue", (-1400, -260 - 90 * i))
        v.name = v.label = "nova_" + key
        val[key] = v

    def op(kind, a, b, loc):
        m = _node(nt, "ShaderNodeMath", loc, operation=kind)
        for k, x in enumerate((a, b)):
            if isinstance(x, (int, float)):
                m.inputs[k].default_value = x
            else:
                L(x, m.inputs[k])
        return m.outputs[0]

    birth, main, weight = (attr[k].outputs["Fac"] for k in ("birth", "main", "weight"))
    since = op("SUBTRACT", val["leader"].outputs[0], birth, (-1100, 300))
    vis = op("GREATER_THAN", since, -1e-4, (-900, 380))
    tip = op("EXPONENT", op("MULTIPLY", since, -25.0, (-900, 260)), 0, (-700, 260))
    lead = op("MULTIPLY", op("ADD", op("MULTIPLY", tip, 1.0, (-500, 260)), 0.02, (-300, 260)),
                val["lglow"].outputs[0], (-100, 260))
    # strokes: every stroke on the main channel; the branches only in the first (bflash), by their weight
    bw = op("MULTIPLY", op("MULTIPLY", weight, val["branch"].outputs[0], (-900, 100)), val["bflash"].outputs[0],
            (-700, 40))
    chan = op("MULTIPLY", main, val["flash"].outputs[0], (-700, 160))
    stroke = op("MAXIMUM", chan, bw, (-500, 100))
    inten = op("MULTIPLY", op("ADD", lead, stroke, (100, 200)), vis, (300, 200))
    strength = op("MULTIPLY", inten, val["bright"].outputs[0], (500, 200))
    # colour: the plasma temperature, keyframed as it cools
    bb = _node(nt, "ShaderNodeBlackbody", (-250, -200))
    L(val["temp"].outputs[0], bb.inputs[0])
    em = _node(nt, "ShaderNodeEmission", (700, 0))
    L(bb.outputs[0], em.inputs["Color"])
    L(strength, em.inputs["Strength"])
    tr = _node(nt, "ShaderNodeBsdfTransparent", (700, 150))
    add = _node(nt, "ShaderNodeAddShader", (900, 80))
    L(tr.outputs[0], add.inputs[0])
    L(em.outputs[0], add.inputs[1])
    out = _node(nt, "ShaderNodeOutputMaterial", (1100, 80))
    L(add.outputs[0], out.inputs["Surface"])
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    return mat


def _light(ob, suffix, radius):
    name = f"{ob.name} {suffix}"
    lob = bpy.data.objects.get(name)
    if lob is None or lob.type != "LIGHT":
        light = bpy.data.lights.new(name, "POINT")
        lob = bpy.data.objects.new(name, light)
        for coll in ob.users_collection:
            coll.objects.link(lob)
        lob.hide_select = True
    lob.data.shadow_soft_size = radius
    return lob


def _place_lights(ob, top, low):
    h = max(1.0, (top - low).length)
    _light(ob, "Cloud Flash", 0.15 * h).location = top
    _light(ob, "Flash", 0.05 * h).location = low


# ------------------------------------------------------------------ timeline

def timeline(lt):
    """Per-frame values from the leader's first frame to the end of the afterglow:
    (frame, leader progress, channel flash, branch flash, leader glow, temperature)."""
    rng = np.random.default_rng(lt.seed * 31 + 5)
    fs = lt.strike_frame
    L = max(lt.leader_frames, 0)
    times, amps = [float(fs)], [1.0]
    for k in range(1, lt.strokes):
        times.append(times[-1] + lt.stroke_gap * rng.uniform(0.6, 1.4))
        amps.append(rng.uniform(0.45, 0.85))
    last = times[-1]
    glow = max(lt.afterglow, 0.01)
    end = int(math.ceil(last + lt.afterglow)) + 1
    hot, cold = 1.0 / lt.temperature, 1.0 / 3000.0
    rows = []
    for f in range(fs - L - 1, end + 1):
        leader = (f - (fs - L)) / L if L else (1.0 if f >= fs else -1.0)
        flash = sum(a * math.exp(-(f - t) / 0.7) for t, a in zip(times, amps) if f >= t)
        if times[0] <= f < last:
            flash = max(flash, 0.06)  # continuing current between strokes keeps the channel lit
        if f >= last:
            flash = max(flash, 0.12 * math.exp(-(f - last) / (glow / 3)))
        bflash = math.exp(-(f - fs) / 0.6) if f >= fs else 0.0
        lglow = 1.0 if f < fs else math.exp(-(f - fs) / 1.5)
        # cooling, even on a reciprocal (mired) scale: blue-white to white to orange
        cool = 0.0 if f < last else 1.0 - math.exp(-(f - last) / (glow / 3))
        temp = 1.0 / (hot + cool * (cold - hot))
        if f >= end or f < fs - L:
            flash = bflash = lglow = 0.0
        rows.append((f, leader, flash, bflash, lglow, temp))
    return rows


def animate(ob):
    """Keyframe the material and lights from the strike timeline (constant between frames)."""
    lt = ob.nova_lightning
    cv = ob.data
    mat = cv.materials[0] if cv.materials else None
    if mat is None or not mat.node_tree:
        return
    nt = mat.node_tree
    prefs = bpy.context.preferences.edit
    old = prefs.keyframe_new_interpolation_type
    prefs.keyframe_new_interpolation_type = "CONSTANT"
    try:
        nt.animation_data_clear()
        nodes = {k: nt.nodes.get("nova_" + k) for k in ("leader", "flash", "bflash", "lglow", "temp", "bright", "branch")}
        if any(v is None for v in nodes.values()):
            return
        nodes["bright"].outputs[0].default_value = lt.brightness
        nodes["branch"].outputs[0].default_value = lt.branch_glow
        lights = [bpy.data.objects.get(f"{ob.name} {s}") for s in ("Cloud Flash", "Flash")]
        lights = [l for l in lights if l is not None]
        col = core.blackbody(min(lt.temperature, 15000.0))
        col = col / max(col.max(), 1e-6)
        for l in lights:
            l.data.animation_data_clear()
            l.data.color = tuple(float(c) for c in col)
        rows = timeline(lt)
        for f, leader, flash, bflash, lglow, temp in rows:
            for key, v in (("leader", leader), ("flash", flash), ("bflash", bflash), ("lglow", lglow),
                           ("temp", temp)):
                sock = nodes[key].outputs[0]
                sock.default_value = v
                sock.keyframe_insert("default_value", frame=f)
            for i, l in enumerate(lights):
                # the cloud lights up from inside on every stroke; the low light also shows the leader
                e = lt.light_power * (max(flash, 0.5 * bflash) +
                                      (0.0 if i == 0 else 0.02 * lglow))
                l.data.energy = e
                l.data.keyframe_insert("energy", frame=f)
    finally:
        prefs.keyframe_new_interpolation_type = old
    if lt.impact:
        em = lt.impact.nova_emitter
        em.burst_frame = lt.strike_frame


# ------------------------------------------------------------------ creating

def add(context, coll, location, name="Nova Lightning", **settings):
    """A new bolt object at `location` (its cloud end). Returns the object."""
    cv = bpy.data.hair_curves.new(name)
    ob = bpy.data.objects.new(name, cv)
    ob.location = location
    coll.objects.link(ob)
    lt = ob.nova_lightning
    _BUSY.add(ob.name)
    try:
        lt.enabled = True
        for k, v in settings.items():
            setattr(lt, k, v)
    finally:
        _BUSY.discard(ob.name)
    cv.materials.append(material(ob))
    context.view_layer.update()
    rebuild(ob)
    return ob


class NOVA_OT_lightning_regrow(bpy.types.Operator):
    """Grow the bolt again (new seed, or after moving the object or its target)"""
    bl_idname = "nova.lightning_regrow"
    bl_label = "Regrow"
    bl_options = {"REGISTER", "UNDO"}
    new_seed: BoolProperty(name="New Seed", default=False)

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.nova_lightning.enabled

    def execute(self, context):
        ob = context.object
        if self.new_seed:
            ob.nova_lightning.seed += 1  # triggers the rebuild
        else:
            rebuild(ob)
        if "nova_strike" not in ob:
            self.report({"WARNING"}, "The bolt never reached the ground: raise Directness or Step")
        return {"FINISHED"}


CLASSES = (NovaLightning, NOVA_OT_lightning_regrow)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.nova_lightning = PointerProperty(type=NovaLightning)


def unregister():
    del bpy.types.Object.nova_lightning
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
