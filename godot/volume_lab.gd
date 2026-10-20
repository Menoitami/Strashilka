extends Node3D

var creature: Node3D
var surface: MeshInstance3D
var animation: AnimationPlayer
var camera: Camera3D
var label: Label
var elapsed := 0.0
var orbit := .32
var elevation := .12
var distance := 5.4
var rotating := false
var auto_orbit := false
var walking := true
var mutation := true
var rest_pose := false
var smoke_seconds := 0.0
var output := ""
var record_dir := ""
var record_index := 0
var shot_index := -1
var frame_ms: Array[float] = []
var last_tick := 0
var report_start := 0
var error_text := ""
var walk_name := ""
var mesh_path := "res://../artifacts/3d/generated/creature.glb"

func _ready() -> void:
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--model="):
            mesh_path = arg.trim_prefix("--model=")
        if arg.begins_with("--smoke-seconds="):
            smoke_seconds = float(arg.trim_prefix("--smoke-seconds="))
            auto_orbit = true
        if arg.begins_with("--output="):
            output = arg.trim_prefix("--output=")
        if arg.begins_with("--record-dir="):
            record_dir = arg.trim_prefix("--record-dir=")
            DirAccess.make_dir_recursive_absolute(record_dir)
    _world()
    _load_creature()
    _ui()
    last_tick = Time.get_ticks_usec()
    report_start = last_tick

func _world() -> void:
    var environment := WorldEnvironment.new()
    environment.environment = Environment.new()
    environment.environment.background_mode = Environment.BG_COLOR
    environment.environment.background_color = Color("0c1118")
    environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.environment.ambient_light_color = Color("8f9ead")
    environment.environment.ambient_light_energy = .48
    environment.environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
    add_child(environment)
    for side in [-1, 1]:
        var light := OmniLight3D.new()
        light.position = Vector3(side*3, 3.8, 2)
        light.light_color = Color("83d8d1") if side < 0 else Color("e6a290")
        light.light_energy = .85
        light.omni_range = 10
        light.shadow_enabled = true
        add_child(light)
    var rim := DirectionalLight3D.new()
    rim.rotation_degrees = Vector3(-40, 150, 0)
    rim.light_color = Color("8ca5dc")
    rim.light_energy = .35
    rim.shadow_enabled = true
    add_child(rim)
    var ground := MeshInstance3D.new()
    var plane := PlaneMesh.new()
    plane.size = Vector2(18, 18)
    ground.mesh = plane
    var ground_material := StandardMaterial3D.new()
    ground_material.albedo_color = Color("243039")
    ground_material.roughness = .95
    ground.material_override = ground_material
    add_child(ground)
    for x in range(-8, 9):
        for direction in [0, 1]:
            var line := MeshInstance3D.new()
            var box := BoxMesh.new()
            box.size = Vector3(.008, .002, 16) if direction == 0 else Vector3(16, .002, .008)
            line.mesh = box
            line.position = Vector3(x, .002, 0) if direction == 0 else Vector3(0, .002, x)
            var mat := StandardMaterial3D.new()
            mat.albedo_color = Color("35444d")
            line.material_override = mat
            add_child(line)
    camera = Camera3D.new()
    camera.fov = 48
    add_child(camera)
    camera.current = true

func _load_creature() -> void:
    var document := GLTFDocument.new()
    var state := GLTFState.new()
    var path := ProjectSettings.globalize_path(mesh_path)
    var result := document.append_from_file(path, state)
    if result != OK:
        error_text = "Cannot load model: " + path + " (run scripts/run_3d.sh --generate)"
        push_error(error_text)
        return
    creature = document.generate_scene(state)
    add_child(creature)
    var skeletons := creature.find_children("*", "Skeleton3D", true, false)
    var meshes := creature.find_children("*", "MeshInstance3D", true, false)
    var animations := creature.find_children("*", "AnimationPlayer", true, false)
    if skeletons.is_empty() or meshes.is_empty() or animations.is_empty():
        error_text = "Model must contain a skinned surface, skeleton and animation"
        push_error(error_text)
        return
    surface = meshes[0]
    # Runtime GLTFDocument leaves vertex-color multiplication off in this Godot build.
    # Explicitly enable it: the network stores appearance in COLOR_0, not a texture.
    for index in range(surface.mesh.get_surface_count()):
        var imported := surface.get_active_material(index) as StandardMaterial3D
        if imported:
            var colored := imported.duplicate() as StandardMaterial3D
            colored.vertex_color_use_as_albedo = true
            colored.roughness = .88
            surface.set_surface_override_material(index, colored)
    animation = animations[0]
    for name_ in animation.get_animation_list():
        if str(name_).contains("CreepWalk"):
            walk_name = name_
            animation.get_animation(name_).loop_mode = Animation.LOOP_LINEAR
            animation.play(name_)
    print("VOLUME MODEL: ", surface.mesh.get_surface_count(), " surfaces; ", skeletons[0].get_bone_count(), " bones; ", walk_name)

func _ui() -> void:
    var layer := CanvasLayer.new()
    add_child(layer)
    var panel := PanelContainer.new()
    panel.position = Vector2(22, 20)
    panel.custom_minimum_size = Vector2(370, 0)
    layer.add_child(panel)
    var margin := MarginContainer.new()
    for side in ["left", "right", "top", "bottom"]:
        margin.add_theme_constant_override("margin_"+side, 16)
    panel.add_child(margin)
    var stack := VBoxContainer.new()
    margin.add_child(stack)
    var title := Label.new()
    title.text = "SPOOKY / VOLUME LAB"
    title.add_theme_font_size_override("font_size", 22)
    stack.add_child(title)
    var description := Label.new()
    description.text = "Neural 3D surface  /  skinned mesh\n19 bones  /  real depth & lighting"
    stack.add_child(description)
    var hint := Label.new()
    hint.text = "Drag RMB: orbit   Wheel: zoom\nSpace: walk   M: shape shift\nR: rest pose   O: automatic orbit\nF12: screenshot   Esc: exit"
    stack.add_child(hint)
    label = Label.new()
    label.add_theme_color_override("font_color", Color("8dd4b9"))
    stack.add_child(label)

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_RIGHT:
            rotating = event.pressed
        if event.pressed and event.button_index == MOUSE_BUTTON_WHEEL_UP:
            distance = maxf(2.2, distance-.3)
        if event.pressed and event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
            distance = minf(12, distance+.3)
    if event is InputEventMouseMotion and rotating:
        orbit -= event.relative.x*.007
        elevation = clampf(elevation+event.relative.y*.006, -.35, .9)
        auto_orbit = false
    if event is InputEventKey and event.pressed and not event.echo:
        match event.keycode:
            KEY_ESCAPE: get_tree().quit()
            KEY_O: auto_orbit = not auto_orbit
            KEY_M: mutation = not mutation
            KEY_R:
                rest_pose = not rest_pose
                if animation:
                    if rest_pose:
                        animation.stop()
                        for skeleton in creature.find_children("*", "Skeleton3D", true, false):
                            skeleton.reset_bone_poses()
                    elif not walk_name.is_empty():
                        animation.play(walk_name)
            KEY_SPACE:
                walking = not walking
                if animation:
                    animation.speed_scale = 1 if walking else 0
            KEY_F12: _screenshot("user://volume_lab.png")

func _process(delta: float) -> void:
    var tick := Time.get_ticks_usec()
    frame_ms.append((tick-last_tick)/1000.0)
    last_tick = tick
    elapsed += delta
    if auto_orbit:
        orbit += delta * (TAU/maxf(12, smoke_seconds) if smoke_seconds > 0 else .23)
    camera.position = Vector3(sin(orbit)*cos(elevation)*distance, 1.5+sin(elevation)*distance, cos(orbit)*cos(elevation)*distance)
    camera.look_at(Vector3(0, 1.5, 0))
    if surface and surface.get_blend_shape_count() > 0:
        surface.set_blend_shape_value(0, (.5+.5*sin(elapsed*1.6)) if mutation and not rest_pose else 0)
    label.text = error_text if not error_text.is_empty() else "%d FPS  /  walk %s  /  mutation %s" % [Engine.get_frames_per_second(), "ON" if walking else "PAUSED", "ON" if mutation else "OFF"]
    if smoke_seconds > 0:
        var real_elapsed := (tick-report_start)/1000000.0
        var stage := int(real_elapsed/(smoke_seconds/4))
        if stage > shot_index and not output.is_empty():
            shot_index = stage
            _screenshot(output+"_%d.png" % stage)
        if not record_dir.is_empty() and record_index < int(real_elapsed*12):
            _screenshot(record_dir.path_join("frame_%05d.png" % record_index))
            record_index += 1
        if real_elapsed >= smoke_seconds:
            frame_ms.sort()
            var report := {"seconds": real_elapsed, "frames": frame_ms.size(),
                "mean_frame_ms": frame_ms.reduce(func(a, b): return a+b, 0.0)/maxi(1, frame_ms.size()),
                "p95_frame_ms": frame_ms[int(frame_ms.size()*.95)], "model": mesh_path,
                "error": error_text, "skinned": surface != null, "animation": walk_name}
            if not output.is_empty():
                FileAccess.open(output+".json", FileAccess.WRITE).store_string(JSON.stringify(report,"  "))
            get_tree().quit(0 if error_text.is_empty() else 1)

func _screenshot(path: String) -> void:
    await RenderingServer.frame_post_draw
    if get_viewport() != null:
        get_viewport().get_texture().get_image().save_png(path)
