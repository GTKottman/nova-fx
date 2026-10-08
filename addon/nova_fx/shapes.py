"""Point sets sampled from objects: the shapes particles form (Form force) or burst into (Shape pattern).

Any object Blender can turn into a mesh works: meshes, text (and MoBlend MoText), curves and imported SVG
logos. Each object keeps its own sampling settings (Object > nova_shape), so one logo can serve several
forces and firework types.
"""

import bpy
import numpy as np
from bpy.props import EnumProperty, IntProperty, PointerProperty

MODES = [
    ("SURFACE", "Surface", "Filled: spread over the faces (area weighted)"),
    ("OUTLINE", "Outline", "The edges of the shape only (a flat logo or text reads best this way)"),
    ("EDGES", "Edges", "Every edge (wireframe)"),
    ("VERTS", "Vertices", "The vertices"),
]


class NovaShape(bpy.types.PropertyGroup):
    mode: EnumProperty(name="Sample", items=MODES, default="SURFACE",
                       description="Where on the shape the points go")
    points: IntProperty(name="Points", default=20000, min=16, max=2_000_000,
                        description="How many points to sample (bursts pick an even subset of them)")
    seed: IntProperty(name="Seed", default=0, min=0)


def _mesh_arrays(ob, depsgraph):
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        nv, ne = len(me.vertices), len(me.edges)
        co = np.empty(nv * 3, np.float32)
        me.vertices.foreach_get("co", co)
        ed = np.empty(ne * 2, np.int32)
        me.edges.foreach_get("vertices", ed)
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", tri)
        # faces per edge, for the outline
        nl = len(me.loops)
        le = np.empty(nl, np.int32)
        me.loops.foreach_get("edge_index", le)
        uses = np.bincount(le, minlength=ne) if nl else np.zeros(ne, np.int64)
        return co.reshape(-1, 3), ed.reshape(-1, 2), tri.reshape(-1, 3), uses
    finally:
        ev.to_mesh_clear()


def _on_edges(co, ed, n, rng):
    a, b = co[ed[:, 0]], co[ed[:, 1]]
    ln = np.linalg.norm(b - a, axis=1)
    if ln.sum() <= 0:
        return None
    e = np.searchsorted(np.cumsum(ln) / ln.sum(), rng.random(n))
    e = np.minimum(e, len(ed) - 1)
    t = rng.random(n)[:, None]
    return a[e] + (b[e] - a[e]) * t


def sample(ob, depsgraph, mode="SURFACE", n=20000, seed=0):
    """n points in the object's local space, in random order (so any prefix is an even subset)."""
    rng = np.random.default_rng([seed, n, 7])
    co, ed, tri, uses = _mesh_arrays(ob, depsgraph)
    if len(co) == 0:
        return np.zeros((0, 3), np.float32)
    pts = None
    if mode == "SURFACE" and len(tri):
        a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
        area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
        if area.sum() > 0:
            t = np.minimum(np.searchsorted(np.cumsum(area) / area.sum(), rng.random(n)), len(tri) - 1)
            u, v = rng.random(n), rng.random(n)
            flip = u + v > 1
            u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
            pts = a[t] + (b[t] - a[t]) * u[:, None] + (c[t] - a[t]) * v[:, None]
    if pts is None and mode in {"SURFACE", "OUTLINE"} and len(ed):
        # outline: edges with exactly one face. A curve or text without fill has no faces: all its edges are
        # the outline already
        border = ed[uses == 1] if len(tri) and (uses == 1).any() else ed
        pts = _on_edges(co, border, n, rng)
    if pts is None and mode in {"SURFACE", "OUTLINE", "EDGES"} and len(ed):
        pts = _on_edges(co, ed, n, rng)
    if pts is None:
        pts = co[rng.integers(0, len(co), n)]
    return np.ascontiguousarray(pts, np.float32)


def world(ob, pts):
    M = np.array(ob.matrix_world, np.float32)
    return np.ascontiguousarray(pts @ M[:3, :3].T + M[:3, 3], np.float32)


def burst(ob, pts):
    """Directions for a Shape burst: centred on the shape, turned (and stretched) like the object, longest
    reach = 1. The burst speed then sets the size."""
    if len(pts) == 0:
        return pts
    lo, hi = pts.min(0), pts.max(0)
    M = np.array(ob.matrix_world.to_3x3(), np.float32)
    d = (pts - (lo + hi) / 2) @ M.T
    r = float(np.linalg.norm(d, axis=1).max())
    return np.ascontiguousarray(d / max(r, 1e-9), np.float32)


def key(ob, purpose):
    """Changes whenever the sampled points would."""
    s = ob.nova_shape
    me = ob.data
    nverts = len(me.vertices) if isinstance(me, bpy.types.Mesh) else 0
    body = me.body if isinstance(me, bpy.types.TextCurve) else ""
    m = ob.matrix_world if purpose == "form" else ob.matrix_world.to_3x3()
    return (purpose, s.mode, s.points, s.seed, me.name if me else "", nverts, body,
            tuple(round(v, 5) for row in m for v in row))


CLASSES = (NovaShape,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.nova_shape = PointerProperty(type=NovaShape)


def unregister():
    del bpy.types.Object.nova_shape
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
