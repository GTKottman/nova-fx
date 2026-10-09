"""Materials, streak display (Geometry Nodes) and glow for Nova systems."""

import bpy
from mathutils import Vector

PMAT = "Nova Particles"
VMAT = "Nova Fire"
DISPLAY_GROUP = "Nova Display"


def _node(nt, t, loc, **props):
    n = nt.nodes.new(t)
    n.location = loc
    for k, v in props.items():
        setattr(n, k, v)
    return n


def _first(nt, t):
    return next((n for n in nt.nodes if n.bl_idname == t), None)


# ------------------------------------------------------------------ particle material

def particle_material(sysob):
    name = f"{PMAT} · {sysob.name}"
    mat = bpy.data.materials.get(name)
    if mat and mat.node_tree and mat.get("nova_v") == 3:
        return mat
    mat = mat or bpy.data.materials.new(name)
    mat["nova_v"] = 3
    if not mat.node_tree:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = _node(nt, "ShaderNodeOutputMaterial", (900, 0))
    cd = _node(nt, "ShaderNodeAttribute", (-500, 150), attribute_name="Cd", attribute_type="GEOMETRY", label="Cd")
    em = _node(nt, "ShaderNodeAttribute", (-500, -100), attribute_name="emit", attribute_type="GEOMETRY",
               label="emit")
    mul = _node(nt, "ShaderNodeMath", (-250, -100), operation="MULTIPLY", label="Brightness")
    mul.name = "nova_brightness"
    emis = _node(nt, "ShaderNodeEmission", (100, 150))
    bsdf = _node(nt, "ShaderNodeBsdfPrincipled", (100, -200))
    mix = _node(nt, "ShaderNodeMixShader", (600, 0))
    mix.name = "nova_lit"
    L = nt.links
    L.new(em.outputs["Fac"], mul.inputs[0])
    L.new(cd.outputs["Color"], emis.inputs["Color"])
    L.new(mul.outputs[0], emis.inputs["Strength"])
    L.new(cd.outputs["Color"], bsdf.inputs["Base Color"])
    L.new(cd.outputs["Color"], bsdf.inputs["Emission Color"])
    L.new(mul.outputs[0], bsdf.inputs["Emission Strength"])  # lit systems can mix glowing and dull types
    L.new(emis.outputs[0], mix.inputs[1])
    L.new(bsdf.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], out.inputs["Surface"])
    # glowing pixels are mostly light, not surface: keep them cheap in Cycles
    return mat


# ------------------------------------------------------------------ volume material

def volume_material(sysob):
    name = f"{VMAT} · {sysob.name}"
    mat = bpy.data.materials.get(name)
    look = sysob.nova.fluid.gas_look
    if mat and mat.node_tree and mat.get("nova_v") == 4 and mat.get("look", "FIRE") == look:
        return mat
    mat = mat or bpy.data.materials.new(name)
    mat["nova_v"] = 4
    mat["look"] = look
    if look == "SPIRIT":
        return _spirit_material(mat)
    if not mat.node_tree:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = _node(nt, "ShaderNodeOutputMaterial", (900, 0))
    vol = _node(nt, "ShaderNodeVolumePrincipled", (550, 0))
    vol.name = "nova_volume"
    heat = _node(nt, "ShaderNodeAttribute", (-700, -150), attribute_name="heat", label="heat")
    flame = _node(nt, "ShaderNodeAttribute", (-700, -400), attribute_name="flame", label="flame")
    kel = _node(nt, "ShaderNodeMath", (-450, -50), operation="MULTIPLY_ADD", label="Kelvin")
    kel.name = "nova_kelvin"
    kel.inputs[2].default_value = 300.0
    bb = _node(nt, "ShaderNodeBlackbody", (-250, -50))
    # glowing gas: nothing below a threshold, then a steep (T^3) rise, like hot gas really looks
    sub = _node(nt, "ShaderNodeMath", (-600, -250), operation="SUBTRACT")
    sub.inputs[1].default_value = 0.25
    pos = _node(nt, "ShaderNodeMath", (-520, -250), operation="MAXIMUM")
    pos.inputs[1].default_value = 0.0
    sq = _node(nt, "ShaderNodeMath", (-450, -250), operation="POWER")
    sq.inputs[1].default_value = 3.0
    fm = _node(nt, "ShaderNodeMath", (-250, -420), operation="MULTIPLY_ADD", label="Flame")
    fm.name = "nova_flame"  # flame * flame_mult + heat_mult
    fm.inputs[2].default_value = 1.0
    hm = _node(nt, "ShaderNodeMath", (0, -300), operation="MULTIPLY", label="Glow")
    L = nt.links
    L.new(heat.outputs["Fac"], kel.inputs[0])
    L.new(kel.outputs[0], bb.inputs[0])
    L.new(bb.outputs[0], vol.inputs["Emission Color"])
    L.new(heat.outputs["Fac"], sub.inputs[0])
    L.new(sub.outputs[0], pos.inputs[0])
    L.new(pos.outputs[0], sq.inputs[0])
    L.new(sq.outputs[0], hm.inputs[0])
    L.new(flame.outputs["Fac"], fm.inputs[0])
    L.new(fm.outputs[0], hm.inputs[1])
    L.new(hm.outputs[0], vol.inputs["Emission Strength"])
    L.new(vol.outputs[0], out.inputs["Volume"])
    vol.inputs["Density Attribute"].default_value = "density"
    vol.inputs["Temperature Attribute"].default_value = ""
    vol.inputs["Blackbody Intensity"].default_value = 0.0
    return mat


def _spirit_material(mat):
    """Glowing mist: emission where it is dense, coloured by its remaining heat, barely absorbing."""
    if not mat.node_tree:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = _node(nt, "ShaderNodeOutputMaterial", (900, 0))
    vol = _node(nt, "ShaderNodeVolumePrincipled", (550, 0))
    vol.name = "nova_volume"
    dens = _node(nt, "ShaderNodeAttribute", (-700, 100), attribute_name="density", label="density")
    heat = _node(nt, "ShaderNodeAttribute", (-700, -150), attribute_name="heat", label="heat")
    ramp = _node(nt, "ShaderNodeMix", (-250, -150))
    ramp.data_type = "RGBA"
    ramp.name = "nova_spirit"
    clamp = _node(nt, "ShaderNodeMath", (-450, -150), operation="MULTIPLY", use_clamp=True)
    clamp.inputs[1].default_value = 1.5
    glow = _node(nt, "ShaderNodeMath", (-250, 100), operation="MULTIPLY", label="Glow")
    glow.name = "nova_spirit_glow"
    L = nt.links
    L.new(heat.outputs["Fac"], clamp.inputs[0])
    L.new(clamp.outputs[0], ramp.inputs["Factor"])
    L.new(dens.outputs["Fac"], glow.inputs[0])
    L.new(ramp.outputs["Result"], vol.inputs["Emission Color"])
    L.new(glow.outputs[0], vol.inputs["Emission Strength"])
    L.new(vol.outputs[0], out.inputs["Volume"])
    vol.inputs["Density Attribute"].default_value = "density"
    vol.inputs["Temperature Attribute"].default_value = ""
    vol.inputs["Blackbody Intensity"].default_value = 0.0
    return mat


def ensure_volume_material(sysob):
    vob = sysob.nova.fluid.volume
    if not vob:
        return
    mat = volume_material(sysob)
    if not vob.data.materials:
        vob.data.materials.append(mat)
    elif vob.data.materials[0] != mat:
        vob.data.materials[0] = mat
    sync_materials(sysob)


# ------------------------------------------------------------------ display (GN)

def display_group():
    """Streaks for a companion Curves object: read the system's points (Object Info), give each a
    2-point curve trailing behind its motion. Cycles only draws GN curves on Curves objects, and
    curves are ~18x cheaper to render than mesh tubes (1M streaks: 1.4 s vs 25 s)."""
    ng = bpy.data.node_groups.get(DISPLAY_GROUP)
    if ng and ng.get("nova_v") == 6:
        return ng
    if ng is None:
        ng = bpy.data.node_groups.new(DISPLAY_GROUP, "GeometryNodeTree")
    ng["nova_v"] = 6
    ng.nodes.clear()
    ng.interface.clear()
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("System", in_out="INPUT", socket_type="NodeSocketObject")
    s = ng.interface.new_socket("Length", in_out="INPUT", socket_type="NodeSocketFloat")
    s.default_value = 0.03
    s.min_value = 0.0
    ng.interface.new_socket("Material", in_out="INPUT", socket_type="NodeSocketMaterial")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi = _node(ng, "NodeGroupInput", (-1100, 0))
    go = _node(ng, "NodeGroupOutput", (1100, 0))
    info = _node(ng, "GeometryNodeObjectInfo", (-900, 200), transform_space="RELATIVE")
    vel = _node(ng, "GeometryNodeInputNamedAttribute", (-700, -250), data_type="FLOAT_VECTOR")
    vel.inputs["Name"].default_value = "velocity"
    rad = _node(ng, "GeometryNodeInputNamedAttribute", (-700, -450), data_type="FLOAT")
    rad.inputs["Name"].default_value = "radius"
    length = _node(ng, "ShaderNodeVectorMath", (-500, -250), operation="LENGTH")
    lmul = _node(ng, "ShaderNodeMath", (-300, -250), operation="MULTIPLY")
    r2 = _node(ng, "ShaderNodeMath", (-300, -450), operation="MULTIPLY")
    r2.inputs[1].default_value = 2.0
    lmax = _node(ng, "ShaderNodeMath", (-100, -300), operation="MAXIMUM")
    scale = _node(ng, "ShaderNodeCombineXYZ", (100, -350))
    scale.inputs["X"].default_value = 1.0
    scale.inputs["Y"].default_value = 1.0
    align = _node(ng, "FunctionNodeAlignRotationToVector", (100, -150))
    align.axis = "Z"
    # "radius" is a built-in name that realize does not carry onto curve points: keep a private copy
    keep = _node(ng, "GeometryNodeStoreNamedAttribute", (-500, 200), data_type="FLOAT", domain="POINT")
    keep.inputs["Name"].default_value = "nv_radius"
    line = _node(ng, "GeometryNodeCurvePrimitiveLine", (-100, 150))
    line.inputs["Start"].default_value = (0, 0, 0)
    line.inputs["End"].default_value = (0, 0, -1)
    inst = _node(ng, "GeometryNodeInstanceOnPoints", (300, 50))
    real = _node(ng, "GeometryNodeRealizeInstances", (500, 50))
    rad2 = _node(ng, "GeometryNodeInputNamedAttribute", (500, -250), data_type="FLOAT")
    rad2.inputs["Name"].default_value = "nv_radius"
    setrad = _node(ng, "GeometryNodeSetCurveRadius", (700, 50))
    setmat = _node(ng, "GeometryNodeSetMaterial", (900, 50))
    L = ng.links
    L.new(gi.outputs["System"], info.inputs["Object"])
    L.new(info.outputs["Geometry"], keep.inputs["Geometry"])
    L.new(rad.outputs["Attribute"], keep.inputs["Value"])
    L.new(vel.outputs["Attribute"], length.inputs[0])
    L.new(length.outputs["Value"], lmul.inputs[0])
    L.new(gi.outputs["Length"], lmul.inputs[1])
    L.new(rad.outputs["Attribute"], r2.inputs[0])
    L.new(lmul.outputs[0], lmax.inputs[0])
    L.new(r2.outputs[0], lmax.inputs[1])
    L.new(lmax.outputs[0], scale.inputs["Z"])
    L.new(vel.outputs["Attribute"], align.inputs["Vector"])
    L.new(keep.outputs["Geometry"], inst.inputs["Points"])
    L.new(line.outputs[0], inst.inputs["Instance"])
    L.new(align.outputs["Rotation"], inst.inputs["Rotation"])
    L.new(scale.outputs["Vector"], inst.inputs["Scale"])
    L.new(inst.outputs["Instances"], real.inputs["Geometry"])
    L.new(real.outputs["Geometry"], setrad.inputs["Curve"])
    L.new(rad2.outputs["Attribute"], setrad.inputs["Radius"])
    L.new(setrad.outputs[0], setmat.inputs["Geometry"])
    L.new(gi.outputs["Material"], setmat.inputs["Material"])
    L.new(setmat.outputs["Geometry"], go.inputs["Geometry"])
    return ng


def _mod_input(mod, name, value):
    ng = mod.node_group
    item = next((i for i in ng.interface.items_tree if getattr(i, "in_out", "") == "INPUT" and i.name == name), None)
    if item is None:
        return
    props = getattr(mod, "properties", None)  # Blender 5.2+: typed interface
    if props is not None and hasattr(props.inputs, item.identifier):
        getattr(props.inputs, item.identifier).value = value
    else:
        mod[item.identifier] = value


def streak_object(sysob, create=True):
    name = sysob.name + " Streaks"
    ob = bpy.data.objects.get(name)
    if ob is not None and ob.type == "CURVES":
        return ob
    if not create:
        return None
    ob = bpy.data.objects.new(name, bpy.data.hair_curves.new(name))
    for coll in sysob.users_collection:
        coll.objects.link(ob)
    ob.hide_select = True
    return ob


def sync_display(sysob):
    if sysob.type != "POINTCLOUD":
        return
    n = sysob.nova
    mat = particle_material(sysob)
    if not sysob.data.materials:
        sysob.data.materials.append(mat)
    old = sysob.modifiers.get("Nova Display")  # pre-1.1 streaks lived on the point cloud
    if old:
        sysob.modifiers.remove(old)
    streaks = n.display == "STREAKS"
    sob = streak_object(sysob, create=streaks)
    if sob is not None:
        mod = sob.modifiers.get("Nova Display") or sob.modifiers.new("Nova Display", "NODES")
        if mod.node_group is None or mod.node_group.get("nova_v") != 6:
            mod.node_group = display_group()
        _mod_input(mod, "System", sysob)
        _mod_input(mod, "Length", float(n.streak_length))
        _mod_input(mod, "Material", mat)
        sob.hide_render = not streaks
        sob.hide_viewport = not streaks
        sob.matrix_world = sysob.matrix_world.copy()
        if not sob.data.materials:
            sob.data.materials.append(mat)
        sob.update_tag()
    from . import ribbons
    rob = ribbons.ribbon_object(sysob, create=n.display == "RIBBONS")
    if rob is not None:
        rob.hide_render = rob.hide_viewport = n.display != "RIBBONS"
        if not rob.data.materials:
            rob.data.materials.append(mat)
    from . import shapes_display
    shapes_display.sync(sysob)
    lines = streaks or (n.display == "RIBBONS" and not n.ribbon_heads) or n.display == "SHAPES"
    # the points stay selectable (panels live on them) but show as a box while streaks or ribbons draw
    sysob.hide_render = lines
    sysob.display_type = "BOUNDS" if lines else "TEXTURED"
    sysob.update_tag()


def sync_materials(sysob):
    n = sysob.nova
    mat = bpy.data.materials.get(f"{PMAT} · {sysob.name}")
    if mat and mat.node_tree:
        b = mat.node_tree.nodes.get("nova_brightness")
        if b:
            b.inputs[1].default_value = n.emission_mult
        m = mat.node_tree.nodes.get("nova_lit")
        if m:
            m.inputs[0].default_value = 1.0 if n.shading == "LIT" else 0.0
    vmat = bpy.data.materials.get(f"{VMAT} · {sysob.name}")
    if vmat and vmat.node_tree and vmat.get("look", "FIRE") != n.fluid.gas_look and n.fluid.volume:
        ensure_volume_material(sysob)  # the look changed: rebuild (it calls back here)
        return
    if vmat and vmat.node_tree:
        fl = n.fluid
        nt = vmat.node_tree
        v = nt.nodes.get("nova_volume")
        if v:
            v.inputs["Density"].default_value = fl.density_mult
            v.inputs["Color"].default_value = (*fl.smoke_color, 1.0)
        sp = nt.nodes.get("nova_spirit")
        if sp:  # spirit: Color when fresh (hot), End Color as it fades; glow from Flame Brightness; thin
            sp.inputs["A"].default_value = (*fl.spirit_color2, 1)
            sp.inputs["B"].default_value = (*fl.spirit_color, 1)
            nt.nodes["nova_spirit_glow"].inputs[1].default_value = fl.flame_mult
            v.inputs["Density"].default_value = fl.density_mult * 0.05
        k = nt.nodes.get("nova_kelvin")
        if k:
            k.inputs[1].default_value = fl.temp_scale
        f = nt.nodes.get("nova_flame")
        if f:
            f.inputs[1].default_value = fl.flame_mult
            f.inputs[2].default_value = fl.heat_mult


# ------------------------------------------------------------------ glow

def setup_glow(scene, strength=0.3, size=0.45, threshold=1.5):
    """Bloom in the compositor so bright sparks bleed light like a real lens."""
    ng = bpy.data.node_groups.get("Nova Glow")
    if ng is None:
        ng = bpy.data.node_groups.new("Nova Glow", "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl = _node(ng, "CompositorNodeRLayers", (-400, 0))
        gl = _node(ng, "CompositorNodeGlare", (0, 0))
        gl.name = "nova_glare"
        out = _node(ng, "NodeGroupOutput", (400, 0))
        ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
        ng.links.new(gl.outputs["Image"], out.inputs[0])
    gl = ng.nodes.get("nova_glare")
    if gl:
        sock = gl.inputs.get("Type")
        if sock is not None:
            try:
                sock.default_value = "Bloom"
            except TypeError:
                pass
        for key, val in (("Threshold", threshold), ("Strength", strength), ("Size", size)):
            s = gl.inputs.get(key)
            if s is not None:
                try:
                    s.default_value = val
                except TypeError:
                    pass
    scene.compositing_node_group = ng
    return ng


# ------------------------------------------------------------------ liquid surface

LIQ_TREE = "Nova Liquid Surface"
WATER = "Nova Water"


def liquid_tree():
    """Points marked nova_liquid -> signed distance grid -> Laplacian smoothing -> mesh."""
    tree = bpy.data.node_groups.get(LIQ_TREE)
    if tree is not None and tree.get("nova_v") == 5:
        return tree
    if tree is None:
        tree = bpy.data.node_groups.new(LIQ_TREE, "GeometryNodeTree")
    tree.nodes.clear()
    tree.interface.clear()
    tree["nova_v"] = 5
    for name, kind, in_out, default in (("Geometry", "NodeSocketGeometry", "INPUT", None),
                                        ("System", "NodeSocketObject", "INPUT", None),
                                        ("Radius", "NodeSocketFloat", "INPUT", 0.035),
                                        ("Voxel Size", "NodeSocketFloat", "INPUT", 0.025),
                                        ("Smoothing", "NodeSocketInt", "INPUT", 8),
                                        ("Offset", "NodeSocketFloat", "INPUT", -0.01),
                                        ("Box Min", "NodeSocketVector", "INPUT", (-1e4, -1e4, -1e4)),
                                        ("Box Max", "NodeSocketVector", "INPUT", (1e4, 1e4, 1e4)),
                                        ("Material", "NodeSocketMaterial", "INPUT", None),
                                        ("Geometry", "NodeSocketGeometry", "OUTPUT", None)):
        s = tree.interface.new_socket(name, in_out=in_out, socket_type=kind)
        if default is not None:
            s.default_value = default
    N, L = tree.nodes.new, tree.links.new
    gi, go = N("NodeGroupInput"), N("NodeGroupOutput")
    info = N("GeometryNodeObjectInfo")
    info.transform_space = "RELATIVE"
    L(gi.outputs["System"], info.inputs["Object"])
    attr = N("GeometryNodeInputNamedAttribute")
    attr.data_type = "BOOLEAN"
    attr.inputs["Name"].default_value = "nova_liquid"
    keep_out = N("FunctionNodeBooleanMath")
    keep_out.operation = "NOT"
    L(attr.outputs["Attribute"], keep_out.inputs[0])
    dele = N("GeometryNodeDeleteGeometry")
    dele.domain = "POINT"
    L(info.outputs["Geometry"], dele.inputs["Geometry"])
    L(keep_out.outputs[0], dele.inputs["Selection"])
    sdf = N("GeometryNodePointsToSDFGrid")
    L(dele.outputs[0], sdf.inputs["Points"])
    L(gi.outputs["Radius"], sdf.inputs["Radius"])
    L(gi.outputs["Voxel Size"], sdf.inputs["Voxel Size"])
    smooth = N("GeometryNodeSDFGridLaplacian")
    L(sdf.outputs[0], smooth.inputs["Grid"])
    L(gi.outputs["Smoothing"], smooth.inputs["Iterations"])
    shrink = N("GeometryNodeSDFGridOffset")  # big particle spheres blur well; pull back in to keep the volume
    L(smooth.outputs[0], shrink.inputs["Grid"])
    L(gi.outputs["Offset"], shrink.inputs["Distance"])
    mesh = N("GeometryNodeGridToMesh")
    L(shrink.outputs[0], mesh.inputs["Grid"])
    # carry the nearest particle's colour and glow onto the surface (lava glows where it is hot)
    near = N("GeometryNodeSampleNearest")
    near.domain = "POINT"
    L(dele.outputs[0], near.inputs["Geometry"])
    L(N("GeometryNodeInputPosition").outputs[0], near.inputs["Sample Position"])
    carried = mesh.outputs[0]
    for name, dtype in (("Cd", "FLOAT_VECTOR"), ("emit", "FLOAT")):
        get = N("GeometryNodeInputNamedAttribute")
        get.data_type = dtype
        get.inputs["Name"].default_value = name
        pick = N("GeometryNodeSampleIndex")
        pick.data_type, pick.domain = dtype, "POINT"
        L(dele.outputs[0], pick.inputs["Geometry"])
        L(get.outputs["Attribute"], pick.inputs["Value"])
        L(near.outputs["Index"], pick.inputs["Index"])
        put = N("GeometryNodeStoreNamedAttribute")
        put.data_type, put.domain = dtype, "POINT"
        put.inputs["Name"].default_value = name
        L(carried, put.inputs["Geometry"])
        L(pick.outputs["Value"], put.inputs["Value"])
        carried = put.outputs[0]
    # smoothing rounds a flat body of water out through the floor and walls where there are no particles to
    # hold it: keep the surface inside the domain, so water sits flat on the floor and against the walls
    pos = N("GeometryNodeInputPosition").outputs[0]
    lo = N("ShaderNodeVectorMath")
    lo.operation = "MAXIMUM"
    L(pos, lo.inputs[0])
    L(gi.outputs["Box Min"], lo.inputs[1])
    hi = N("ShaderNodeVectorMath")
    hi.operation = "MINIMUM"
    L(lo.outputs[0], hi.inputs[0])
    L(gi.outputs["Box Max"], hi.inputs[1])
    clip = N("GeometryNodeSetPosition")
    L(carried, clip.inputs["Geometry"])
    L(hi.outputs[0], clip.inputs["Position"])
    shade = N("GeometryNodeSetShadeSmooth")
    L(clip.outputs[0], shade.inputs["Mesh"])
    mat = N("GeometryNodeSetMaterial")
    L(shade.outputs[0], mat.inputs["Geometry"])
    L(gi.outputs["Material"], mat.inputs["Material"])
    # Points to SDF Grid crashes Blender 5.2 on zero points: only mesh when there are some (Switch is lazy)
    count = N("GeometryNodeAttributeDomainSize")
    count.component = "POINTCLOUD"
    L(dele.outputs[0], count.inputs[0])
    any_ = N("FunctionNodeCompare")
    any_.data_type, any_.operation = "INT", "GREATER_THAN"
    L(count.outputs["Point Count"], any_.inputs["A"])
    any_.inputs["B"].default_value = 0
    sw = N("GeometryNodeSwitch")
    sw.input_type = "GEOMETRY"
    L(any_.outputs[0], sw.inputs["Switch"])
    L(mat.outputs[0], sw.inputs["True"])
    L(sw.outputs[0], go.inputs["Geometry"])
    return tree


LOOKS = {
    # look: (base colour, roughness, transmission, IOR, absorption colour, absorption density, SSS weight)
    "WATER": ((0.85, 0.93, 1.0), 0.02, 1.0, 1.333, None, 0.0, 0.0),
    "HONEY": ((1.0, 0.95, 0.85), 0.05, 1.0, 1.49, (1.0, 0.9, 0.12), 120.0, 0.0),  # gold at 1 cm, amber deeper
    "BLOOD": ((0.05, 0.0, 0.002), 0.12, 0.0, 1.4, None, 0.0, 0.0),  # near-black red, wet gloss
    "CHOCOLATE": ((0.11, 0.045, 0.02), 0.25, 0.0, 1.45, None, 0.0, 0.1),
    "SLIME": ((0.35, 1.0, 0.25), 0.12, 0.85, 1.38, (0.3, 1.0, 0.15), 8.0, 0.0),
}


def liquid_material(look):
    """The surface material for a liquid look. Lava and Particle Colours read the carried Cd/emit."""
    if look == "WATER":
        return water_material()
    name = f"Nova {look.title()}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    if look in {"LAVA", "PARTICLE"}:
        cd = nt.nodes.new("ShaderNodeAttribute")
        cd.attribute_type, cd.attribute_name = "GEOMETRY", "Cd"
        em = nt.nodes.new("ShaderNodeAttribute")
        em.attribute_type, em.attribute_name = "GEOMETRY", "emit"
        nt.links.new(cd.outputs["Color"], b.inputs["Emission Color"])
        nt.links.new(em.outputs["Fac"], b.inputs["Emission Strength"])
        if look == "LAVA":  # cooled rock: black and rough; the glow comes through where it is hot
            b.inputs["Base Color"].default_value = (0.02, 0.018, 0.017, 1)
            b.inputs["Roughness"].default_value = 0.85
        else:
            nt.links.new(cd.outputs["Color"], b.inputs["Base Color"])
        mat.diffuse_color = (0.6, 0.15, 0.02, 1)
        return mat
    col, rough, trans, ior, absorb, dens, sss = LOOKS[look]
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Transmission Weight"].default_value = trans
    b.inputs["IOR"].default_value = ior
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = (0.02, 0.004, 0.003)
    if absorb is not None:  # colour deepens with thickness, like a jar of honey
        vol = nt.nodes.new("ShaderNodeVolumeAbsorption")
        vol.inputs["Color"].default_value = (*absorb, 1)
        vol.inputs["Density"].default_value = dens
        nt.links.new(vol.outputs[0], out.inputs["Volume"])
    if look == "SLIME":
        b.inputs["Emission Color"].default_value = (0.3, 1.0, 0.2, 1)
        b.inputs["Emission Strength"].default_value = 0.15
    mat.diffuse_color = (*col, 0.8)
    return mat


def water_material():
    mat = bpy.data.materials.get(WATER)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(WATER)
    mat.use_nodes = True
    b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (0.85, 0.93, 1.0, 1)
    b.inputs["Roughness"].default_value = 0.02
    b.inputs["IOR"].default_value = 1.333
    b.inputs["Transmission Weight"].default_value = 1.0
    mat.diffuse_color = (0.3, 0.55, 0.9, 0.6)
    return mat


def sync_liquid(sysob):
    """Make (or update, or hide) the meshed surface of a liquid system."""
    n = sysob.nova
    fl = n.fluid
    liquid = fl.enabled and fl.mode == "LIQUID"
    sob = fl.surface
    if not liquid:
        if sob is not None:
            sob.hide_render = sob.hide_viewport = True
        return None
    if sob is None or sob.name not in bpy.data.objects:
        me = bpy.data.meshes.new(sysob.name + " Surface")
        sob = bpy.data.objects.new(sysob.name + " Surface", me)
        for coll in sysob.users_collection:
            coll.objects.link(sob)
        fl.surface = sob
    sob.hide_render = sob.hide_viewport = False
    mod = sob.modifiers.get("Nova Surface") or sob.modifiers.new("Nova Surface", "NODES")
    if mod.node_group is None or mod.node_group.get("nova_v") != 5:
        mod.node_group = liquid_tree()
    dx = 0.05
    box = None
    if fl.domain:
        from . import sim
        try:
            _res, dx, _o = sim.fluid_layout(sysob)
            box = sim.domain_box(fl.domain)
        except Exception:
            pass
    if box is not None:  # in the surface object's space (it sits on the system)
        inv = sysob.matrix_world.inverted()
        lo, hi = inv @ Vector(box[0]), inv @ Vector(box[1])
        _mod_input(mod, "Box Min", tuple(min(a, b) for a, b in zip(lo, hi)))
        _mod_input(mod, "Box Max", tuple(max(a, b) for a, b in zip(lo, hi)))
    _mod_input(mod, "System", sysob)
    _mod_input(mod, "Radius", float(fl.surface_radius * dx))
    _mod_input(mod, "Voxel Size", float(dx * 0.5))
    _mod_input(mod, "Smoothing", int(fl.surface_smooth))
    _mod_input(mod, "Offset", float(-max(0.0, fl.surface_radius - 0.9) * dx))
    mat = liquid_material(fl.look)
    if not sob.data.materials:
        sob.data.materials.append(mat)
    elif sob.data.materials[0] is None or sob.data.materials[0].name.startswith("Nova "):
        sob.data.materials[0] = mat  # follow the Look unless the user put their own material on
    _mod_input(mod, "Material", sob.data.materials[0])
    sob.matrix_world = sysob.matrix_world.copy()
    # the water is the surface: the points stay for the viewport, out of the render
    sysob.hide_render = True
    sob.update_tag()
    return sob
