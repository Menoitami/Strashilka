extends Node3D
const RuntimePaths = preload("res://runtime_paths.gd")

var surface: MeshInstance3D
var skeleton: Skeleton3D
var animation: AnimationPlayer
var walk_name := ""
var walking := false
var mutation := true
var mutation_amount := 1.0
var walk_speed := 1.0
var time := 0.0
var motion_mix := 0.0
var multiform := false
var material: ShaderMaterial
var form_weights := Vector3(1, 0, 0)
var manual_form := 0.0
var automatic := true
var transition_seconds := 3.0
var hold_seconds := 1.0
var color_blend := 1.0
var relief_blend := 1.0
var relief_strength := .7
var roughness_value := .75
var debug_view := 0
var cycle_time := 0.0
var flow_amount := .06
var flow_speed := 1.0
var flow_clock := 0.0
var monochrome := .85
var contrast_value := 1.6
var form_names := ["Костяной", "Раздутый", "Панцирный"]
var shape_indices: Array[int] = []
var live := false
var live_progress := 0.0
var live_sequence := 0
var live_seed := 0
var live_seconds := 0.0
var live_lora := false
var skin_detail := .65
var skin_wetness := .35
var face_transition_seconds := 1.2
var face_progress := 0.0
var face_maps := {}
var face_from := Vector4.ZERO
var face_target := Vector4.ZERO
var face_shape := Vector4.ZERO
var face_geometry := 1.0
var anatomy_amount := 1.0
var effects_amount := .75
var mutation_audio := .35
var mutation_plan := {}
var head_bounds := Vector2(2.25, 2.9)
var face_revision := 0

func face_transition_finished() -> bool:
    return face_maps.is_empty() or face_progress >= face_transition_seconds

func clear_face() -> void:
    face_maps.clear()
    face_progress = 0
    if material:
        material.set_shader_parameter("face_enabled", false)

func inherit_face(other: Node3D) -> void:
    face_maps = other.face_maps.duplicate()
    face_progress = other.face_progress
    face_from = other.face_from
    face_target = other.face_target
    face_shape = other.face_shape
    face_revision = other.face_revision
    _update_face(0)

func load_face(directory: String) -> Error:
    if not material or not face_transition_finished():
        return ERR_BUSY
    var loaded := {}
    for channel in ["albedo", "normal", "mask"]:
        if not FileAccess.file_exists(directory.path_join(channel+".png")):
            return ERR_FILE_NOT_FOUND
        var image := Image.load_from_file(directory.path_join(channel+".png"))
        if image == null or image.is_empty():
            return ERR_FILE_NOT_FOUND
        image.generate_mipmaps()
        loaded[channel] = ImageTexture.create_from_image(image)
    var next_maps := {}
    for channel in ["albedo", "normal"]:
        next_maps[channel+"_previous"] = face_maps.get(channel+"_next", material.get_shader_parameter(channel+"_2"))
        next_maps[channel+"_next"] = loaded[channel]
    next_maps["mask"] = loaded.mask
    next_maps["flow_enabled"] = false
    var metadata = JSON.parse_string(FileAccess.get_file_as_string(directory.path_join("face.json")))
    if metadata is Dictionary and metadata.has("portrait_view"):
        var portraits := {}
        for channel in ["portrait_previous", "portrait_next", "flow_forward", "flow_backward"]:
            if not FileAccess.file_exists(directory.path_join(channel+".png")):
                return ERR_FILE_NOT_FOUND
            var image := Image.load_from_file(directory.path_join(channel+".png"))
            if image == null or image.is_empty():
                return ERR_FILE_NOT_FOUND
            portraits[channel] = ImageTexture.create_from_image(image)
        next_maps.merge(portraits, true)
        var view: Array = metadata.portrait_view
        if view.size() != 3 or float(view[2]) <= 0:
            return ERR_INVALID_DATA
        next_maps["projection"] = Vector3(view[0], view[1], view[2])
        next_maps["flow_enabled"] = true
        set_face_shape(metadata.get("face_traits", [0,0,0,0]))
    face_maps = next_maps
    face_revision += 1
    face_progress = 0
    _update_face(0)
    return OK

func _update_face(delta: float) -> void:
    if not material:
        return
    if mutation:
        face_progress += delta
    var mix_ := smoothstep(0, 1, clampf(face_progress/maxf(.1, face_transition_seconds), 0, 1))
    face_shape = face_from.lerp(face_target, mix_)
    material.set_shader_parameter("face_shape", face_shape*face_geometry)
    if face_maps.is_empty():
        return
    for name_ in face_maps:
        material.set_shader_parameter("face_"+name_, face_maps[name_])
    material.set_shader_parameter("face_enabled", true)
    material.set_shader_parameter("face_mix", mix_)

func set_face_shape(values: Array) -> void:
    if values.size() != 4:
        return
    for value in values:
        if not (value is float or value is int) or not is_finite(float(value)):
            return
    face_from = face_shape
    face_target = Vector4(clampf(values[0],-1,1),clampf(values[1],-1,1),clampf(values[2],-1,1),clampf(values[3],-1,1))
    face_progress = 0

func transition_finished() -> bool:
    return not live or live_progress >= transition_seconds+hold_seconds


func load_maps(path: String) -> Error:
    var directory := RuntimePaths.resolve(path).get_base_dir()
    if not FileAccess.file_exists(directory.path_join("forms.json")):
        return OK
    var manifest = JSON.parse_string(FileAccess.get_file_as_string(directory.path_join("forms.json")))
    if not manifest is Dictionary or manifest.get("forms", []).size() != 3:
        return ERR_INVALID_DATA
    live = bool(manifest.get("live", false))
    live_sequence = int(manifest.get("sequence", 0))
    live_lora = manifest.get("lora") != null
    live_seed = int(manifest.get("seed", 0))
    live_seconds = float(manifest.get("seconds", 0))
    mutation_plan = manifest.get("mutation", {})
    if live:
        automatic = false
        manual_form = 1
        form_weights = Vector3(0, 1, 0)
    material = ShaderMaterial.new()
    material.shader = preload("res://shaders/multiform.gdshader")
    for index in range(3):
        for channel in ["albedo", "normal"]:
            var image := Image.load_from_file(directory.path_join(manifest.forms[index]+"_"+channel+".png"))
            if image == null or image.is_empty():
                return ERR_FILE_NOT_FOUND
            image.generate_mipmaps()
            material.set_shader_parameter(channel+"_"+str(index), ImageTexture.create_from_image(image))
    for name_ in manifest.geometry_targets:
        var found := -1
        for index in range(surface.get_blend_shape_count()):
            if str(surface.mesh.get_blend_shape_name(index)) == name_:
                found = index
        if found < 0:
            return ERR_INVALID_DATA
        shape_indices.append(found)
    if shape_indices.size() != 2:
        return ERR_INVALID_DATA
    surface.material_override = material
    multiform = true
    return OK

func select_form(value: float) -> void:
    manual_form = clampf(value, 0, 2)
    automatic = false
    mutation = true
    _update_form(0)

func _update_form(delta: float) -> void:
    if not multiform:
        if surface.get_blend_shape_count() > 0 and mutation:
            surface.set_blend_shape_value(0, mutation_amount*(.5+.5*sin(flow_clock*1.6)))
        if mutation:
            flow_clock += delta
        return
    if mutation:
        flow_clock += delta
        var position := manual_form
        if live:
            live_progress += delta
            position = 1+smoothstep(0, 1, clampf(live_progress/maxf(.1, transition_seconds), 0, 1))
        elif automatic:
            cycle_time += delta
            var segment := maxf(.1, transition_seconds)+hold_seconds
            var cycle := fposmod(cycle_time, segment*3)
            var start := int(cycle/segment)
            var progress := clampf((fposmod(cycle, segment)-hold_seconds)/maxf(.1, transition_seconds), 0, 1)
            position = start+smoothstep(0, 1, progress)
        var first := int(floor(position))%3
        var second := (first+1)%3
        form_weights = Vector3.ZERO
        form_weights[first] = 1-fposmod(position, 1)
        form_weights[second] += fposmod(position, 1)
    surface.set_blend_shape_value(shape_indices[0], form_weights.y*mutation_amount)
    surface.set_blend_shape_value(shape_indices[1], form_weights.z*mutation_amount)
    material.set_shader_parameter("form_weights", form_weights)
    material.set_shader_parameter("color_blend", color_blend)
    material.set_shader_parameter("relief_blend", relief_blend)
    material.set_shader_parameter("relief_strength", relief_strength)
    material.set_shader_parameter("roughness_value", roughness_value)
    material.set_shader_parameter("debug_view", debug_view)
    material.set_shader_parameter("flow_clock", flow_clock)
    for property in ["flow_amount", "flow_speed", "monochrome", "contrast_value", "skin_detail", "skin_wetness"]:
        material.set_shader_parameter(property, get(property))

func appearance_text() -> String:
    if live:
        return "LIVE ИИ · #%d · %.2f с · %s" % [live_sequence, live_seconds, "body horror LoRA" if live_lora else "без LoRA"]
    return "Кость %d%% · плоть %d%% · панцирь %d%%" % [form_weights.x*100, form_weights.y*100, form_weights.z*100]


func load_model(path: String) -> Error:
    var document := GLTFDocument.new()
    var state := GLTFState.new()
    var result := document.append_from_file(RuntimePaths.resolve(path), state)
    if result != OK:
        return result
    var scene := document.generate_scene(state)
    if scene == null:
        return ERR_INVALID_DATA
    add_child(scene)
    var meshes := scene.find_children("*", "MeshInstance3D", true, false)
    var skeletons := scene.find_children("*", "Skeleton3D", true, false)
    var players := scene.find_children("*", "AnimationPlayer", true, false)
    if meshes.is_empty() or skeletons.is_empty() or players.is_empty():
        scene.queue_free()
        return ERR_INVALID_DATA
    surface = meshes[0]
    skeleton = skeletons[0]
    animation = players[0]
    for index in range(surface.mesh.get_surface_count()):
        var original := surface.get_active_material(index) as StandardMaterial3D
        if original:
            var colored := original.duplicate() as StandardMaterial3D
            colored.vertex_color_use_as_albedo = true
            colored.roughness = .88
            surface.set_surface_override_material(index, colored)
    var maps_error := load_maps(path)
    if maps_error != OK:
        return maps_error
    head_bounds = Vector2(skeleton.get_bone_global_rest(skeleton.find_bone("Neck")).origin.y-.01, surface.mesh.get_aabb().end.y)
    if material == null:
        var original := surface.get_active_material(0) as StandardMaterial3D
        material = ShaderMaterial.new()
        material.shader = preload("res://shaders/multiform.gdshader")
        material.set_shader_parameter("use_vertex_color", original == null or original.albedo_texture == null)
        material.set_shader_parameter("use_normal_maps", false)
        if original and original.albedo_texture:
            for index in range(3):
                material.set_shader_parameter("albedo_"+str(index), original.albedo_texture)
        surface.material_override = material
    material.set_shader_parameter("head_bounds", head_bounds)
    for name_ in animation.get_animation_list():
        if str(name_).contains("CreepWalk"):
            walk_name = name_
    if walk_name.is_empty():
        return ERR_INVALID_DATA
    animation.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
    animation.get_animation(walk_name).loop_mode = Animation.LOOP_LINEAR
    animation.play(walk_name)
    animation.advance(0)
    _pose(0)
    return OK

func _pose(delta: float) -> void:
    if animation == null:
        return
    time += delta
    motion_mix = move_toward(motion_mix, 1.0 if walking else 0.0, delta*3.5)
    animation.advance(delta*walk_speed)
    for index in range(skeleton.get_bone_count()):
        var name_ := skeleton.get_bone_name(index)
        var animated := skeleton.get_bone_pose_rotation(index)
        var idle := Quaternion.IDENTITY
        if name_ == "Chest":
            idle = Quaternion(Vector3.RIGHT, .10+.009*sin(time*1.45))
            skeleton.set_bone_pose_scale(index, Vector3(1+.006*sin(time*1.45), 1.0, 1+.012*sin(time*1.45)))
        elif name_ == "Head":
            idle = Quaternion(Vector3(0, 0, 1), .065+.018*sin(time*.63))*Quaternion(Vector3.RIGHT, -.035+.012*sin(time*1.1))
        var pose := idle.slerp(animated, motion_mix)
        # Bring the source A-pose arms down while retaining the clip's arm swing.
        if name_.begins_with("Shoulder"):
            var side := -1.0 if name_.ends_with("L") else 1.0
            pose = Quaternion(Vector3(0, 0, 1), -side*.42)*pose
        skeleton.set_bone_pose_rotation(index, pose)
    var pelvis := skeleton.find_bone("Pelvis")
    if pelvis >= 0:
        var rest := skeleton.get_bone_rest(pelvis).origin
        var animated := skeleton.get_bone_pose_position(pelvis)
        skeleton.set_bone_pose_position(pelvis, rest.lerp(animated, motion_mix))
    _update_form(delta)
    _update_face(delta)
    if material:
        for property in ["flow_amount", "flow_speed", "flow_clock", "monochrome", "contrast_value", "skin_detail", "skin_wetness", "roughness_value"]:
            material.set_shader_parameter(property, get(property))
