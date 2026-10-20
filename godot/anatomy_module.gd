extends Node3D
## Reuses real neural skin/UVs, with a local three-bone rig independent of the body.
var rig := Skeleton3D.new()
var surface := MeshInstance3D.new()
var collar := MeshInstance3D.new()
var material: ShaderMaterial
var specification := {}
var length := 1.0
var growth := 0.0
var target := 1.0
var clock := 0.0
var canonical_origin := Vector3.ZERO
var canonical_basis := Basis.IDENTITY
var birth_delay := 0.0

func build(actor: Node3D, spec: Dictionary) -> void:
    specification = spec.duplicate(true)
    add_child(rig)
    rig.name = "ModuleRig"
    add_child(surface)
    surface.skeleton = surface.get_path_to(rig)
    surface.extra_cull_margin = 2
    var arrays := _geometry(actor, str(spec.kind))
    var mesh := ArrayMesh.new()
    mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
    var builder := SurfaceTool.new()
    builder.create_from(mesh,0)
    builder.generate_tangents()
    surface.mesh = builder.commit()
    for i in range(3):
        rig.add_bone("Segment"+str(i))
        if i > 0:
            rig.set_bone_parent(i, i-1)
        var y := 0.0 if i == 0 else length*(.45 if i == 1 else .33)
        rig.set_bone_rest(i, Transform3D(Basis.IDENTITY,Vector3(0,y,0)))
    rig.reset_bone_poses()
    surface.skin = rig.create_skin_from_rest_transforms()
    material = actor.material.duplicate()
    material.set_shader_parameter("module_mode", 2 if spec.kind == "head" else 1)
    material.set_shader_parameter("module_length", length)
    material.set_shader_parameter("canonical_origin", canonical_origin)
    material.set_shader_parameter("canonical_basis", canonical_basis)
    material.set_shader_parameter("growth", 0.0)
    surface.material_override = material
    var tissue := SphereMesh.new()
    tissue.radius = .09 if spec.kind != "head" else .10
    tissue.height = tissue.radius*2
    tissue.radial_segments = 16
    tissue.rings = 8
    collar.mesh = tissue
    var tissue_material := StandardMaterial3D.new()
    var colors: PackedColorArray = arrays[Mesh.ARRAY_COLOR]
    tissue_material.albedo_color = colors[0] if not colors.is_empty() else Color(.36,.30,.27)
    var texture: Texture2D = actor.material.get_shader_parameter("albedo_2")
    if texture:
        var image := texture.get_image()
        var uv: Vector2 = arrays[Mesh.ARRAY_TEX_UV][0]
        tissue_material.albedo_color = image.get_pixel(clampi(int(uv.x*image.get_width()),0,image.get_width()-1),clampi(int(uv.y*image.get_height()),0,image.get_height()-1))
    var tone: Color = tissue_material.albedo_color
    var luminance := tone.r*.2126+tone.g*.7152+tone.b*.0722
    tissue_material.albedo_color = Color(luminance*1.03,luminance*.94,luminance*.88)
    tissue_material.roughness = .8
    collar.material_override = tissue_material
    add_child(collar)

func _geometry(actor: Node3D, kind: String) -> Array:
    var source: Array = actor.surface.mesh.surface_get_arrays(0)
    var vertices: PackedVector3Array = source[Mesh.ARRAY_VERTEX]
    var normals: PackedVector3Array = source[Mesh.ARRAY_NORMAL]
    var uvs: PackedVector2Array = source[Mesh.ARRAY_TEX_UV] if source[Mesh.ARRAY_TEX_UV] != null else PackedVector2Array()
    var colors: PackedColorArray = source[Mesh.ARRAY_COLOR] if source[Mesh.ARRAY_COLOR] != null else PackedColorArray()
    var indices: PackedInt32Array = source[Mesh.ARRAY_INDEX]
    var shoulder: Vector3 = actor.skeleton.get_bone_global_rest(actor.skeleton.find_bone("ShoulderL")).origin
    canonical_origin = Vector3(0,actor.head_bounds.x,0) if kind == "head" else shoulder
    if kind == "arm":
        var wrist: Vector3 = actor.skeleton.get_bone_global_rest(actor.skeleton.find_bone("WristL")).origin
        var axis := (wrist-shoulder).normalized()
        var right := axis.cross(Vector3.FORWARD).normalized()
        canonical_basis = Basis(right,axis,right.cross(axis).normalized())
    var positions := PackedVector3Array()
    var out_normals := PackedVector3Array()
    var out_uvs := PackedVector2Array()
    var out_colors := PackedColorArray()
    var out_indices := PackedInt32Array()
    if kind == "tendril":
        length = 1.55
        var nearest := 0
        for i in range(vertices.size()):
            if vertices[i].distance_squared_to(shoulder) < vertices[nearest].distance_squared_to(shoulder):
                nearest = i
        for ring in range(25):
            var t := float(ring)/24
            var radius := .115*pow(1-t, .75)+.004
            for side in range(12):
                var angle := TAU*side/12.0
                var normal := Vector3(cos(angle),.08,sin(angle)).normalized()
                positions.append(Vector3(cos(angle)*radius,t*length,sin(angle)*radius))
                out_normals.append(normal)
                out_uvs.append(uvs[nearest]+Vector2(cos(angle),t)*.006 if not uvs.is_empty() else Vector2.ZERO)
                out_colors.append(colors[nearest] if not colors.is_empty() else Color(.4,.32,.28))
                if ring < 24:
                    var a := ring*12+side
                    var b := ring*12+(side+1)%12
                    out_indices.append_array(PackedInt32Array([a,b,a+12,b,b+12,a+12]))
    else:
        var selected := PackedByteArray()
        selected.resize(vertices.size())
        var skin_bones: PackedInt32Array = source[Mesh.ARRAY_BONES]
        var weights: PackedFloat32Array = source[Mesh.ARRAY_WEIGHTS]
        for i in range(vertices.size()):
            if kind == "head":
                selected[i] = int(vertices[i].y >= canonical_origin.y and absf(vertices[i].x) < (actor.head_bounds.y-actor.head_bounds.x)*.55)
            else:
                var influence := 0.0
                for j in range(4):
                    var bind := skin_bones[i*4+j]
                    var bone: int = actor.surface.skin.get_bind_bone(bind)
                    if bone < 0:
                        bone = actor.skeleton.find_bone(actor.surface.skin.get_bind_name(bind))
                    if bone >= 0 and actor.skeleton.get_bone_name(bone) in ["ShoulderL","ElbowL","WristL"]:
                        influence += weights[i*4+j]
                selected[i] = int(influence > .6)
        var remap := {}
        for triangle in range(0,indices.size(),3):
            var a := indices[triangle]
            var b := indices[triangle+1]
            var c := indices[triangle+2]
            if not (selected[a] and selected[b] and selected[c]):
                continue
            for old in [a,b,c]:
                if not remap.has(old):
                    remap[old] = positions.size()
                    var p := canonical_basis.transposed()*(vertices[old]-canonical_origin)
                    positions.append(p)
                    length = maxf(length,p.y)
                    out_normals.append(canonical_basis.transposed()*normals[old])
                    out_uvs.append(uvs[old] if not uvs.is_empty() else Vector2.ZERO)
                    out_colors.append(colors[old] if not colors.is_empty() else Color(.45,.37,.32))
                out_indices.append(remap[old])
        length = .001
        for p in positions:
            length = maxf(length,p.y)
    var bones := PackedInt32Array()
    var out_weights := PackedFloat32Array()
    for p in positions:
        var segment := clampf(p.y/length/.45,0,2)
        var first := mini(1,int(segment))
        var blend := segment-first
        bones.append_array(PackedInt32Array([first,first+1,0,0]))
        out_weights.append_array(PackedFloat32Array([1-blend,blend,0,0]))
    var arrays := []
    arrays.resize(Mesh.ARRAY_MAX)
    arrays[Mesh.ARRAY_VERTEX] = positions
    arrays[Mesh.ARRAY_NORMAL] = out_normals
    arrays[Mesh.ARRAY_TEX_UV] = out_uvs
    arrays[Mesh.ARRAY_COLOR] = out_colors
    arrays[Mesh.ARRAY_INDEX] = out_indices
    arrays[Mesh.ARRAY_BONES] = bones
    arrays[Mesh.ARRAY_WEIGHTS] = out_weights
    return arrays

func advance(delta: float, actor: Node3D, amount: float) -> void:
    clock += delta
    birth_delay = maxf(0,birth_delay-delta)
    if birth_delay <= 0:
        growth = move_toward(growth,target,delta/ .8)
    visible = amount > .001 and growth > .001
    var bone: int = actor.skeleton.find_bone(specification.bone)
    var pose: Transform3D = actor.skeleton.global_transform*actor.skeleton.get_bone_global_pose(bone)
    var angles: Array = specification.rotation
    var orient := Basis.from_euler(Vector3(deg_to_rad(angles[0]),deg_to_rad(angles[1]),deg_to_rad(angles[2])))
    # Attach in the animated bone frame, cancelling the A-pose rest orientation.
    var rest: Basis = actor.skeleton.get_bone_global_rest(bone).basis
    global_transform = Transform3D(pose.basis*rest.inverse()*orient,pose.origin)
    scale *= float(specification.scale)*maxf(.001,amount)
    material.set_shader_parameter("growth",smoothstep(0,1,growth))
    collar.scale = Vector3(.9,1.3,.85)*(.7+.3*sin(PI*growth))
    collar.visible = visible
    for i in range(1,3):
        var phase: float = specification.phase
        var bend := sin(clock*1.2+phase+i*.65)*.13
        if specification.kind == "tendril":
            bend = .4*sin(clock*1.6+phase+i)
        rig.set_bone_pose_rotation(i,Quaternion(Vector3.RIGHT,bend)*Quaternion(Vector3.FORWARD,.08*sin(clock+phase)))

func sync_material(actor: Node3D, face: Dictionary = {}) -> void:
    for channel in ["albedo", "normal"]:
        for i in range(3):
            material.set_shader_parameter(channel+"_"+str(i),actor.material.get_shader_parameter(channel+"_"+str(i)))
    for key in ["form_weights","use_vertex_color","use_normal_maps","skin_detail","skin_wetness","roughness_value","monochrome","contrast_value"]:
        material.set_shader_parameter(key,actor.material.get_shader_parameter(key))
    material.set_shader_parameter("flow_clock",clock)
    if specification.kind == "head":
        for key in face:
            material.set_shader_parameter("face_"+key,face[key])
        material.set_shader_parameter("face_enabled",not face.is_empty())
        material.set_shader_parameter("face_mix",actor.material.get_shader_parameter("face_mix"))
        var variant: float = specification.phase
        material.set_shader_parameter("face_shape",(actor.face_shape+Vector4(sin(variant),cos(variant),sin(variant*2),0)*.25)*actor.face_geometry)
