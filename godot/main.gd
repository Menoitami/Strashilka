extends Node3D

const Client = preload("res://neural_client.gd")
var client = Client.new()
var player: CharacterBody3D
var camera: Camera3D
var monster: Node3D
var billboard: MeshInstance3D
var viewport: SubViewport
var proxy_camera: Camera3D
var proxy_root: Node3D
var material: ShaderMaterial
var status_label: Label
var metrics_label: Label
var mode_label: Label
var yaw := 0.0
var pitch := 0.0
var elapsed := 0.0
var capture_timer := 0.0
var capture_busy := false
var serial := 0
var epoch := 0
var last_view_direction := Vector3.ZERO
var current_image: ImageTexture
var current_id := -1
var awaiting_fresh_frame := true
var queued: Array = []
var transition_elapsed := 1.0
var transition_duration := 0.25
var strength := 0.65
var noise_period := 3.0
var lora_scale := 0.8
var transition_scale := 1.0
var mask_mode := "free"
var mask_selector: OptionButton
var previous_visible := true
var use_flow := true
var animate_monster := true
var rig: Dictionary = {}
var walk_phase := 0.0
var monster_heading := 0.0
var is_stepping := false
var connected_status := "Connecting to local renderer…"
var diagnostic := false
var last_latency := 0.0
var last_render := 0.0
var update_count := 0
var smoke_seconds := 0.0
var smoke_output := ""
var frame_times: Array[float] = []
var last_frame_tick := 0
var measured_frame_sum := 0.0
var measured_frame_count := 0
var flow_transitions := 0
var blend_transitions := 0
var last_display_age := 0.0
var last_capture_ms := 0
var last_result_at := 0.0
var screenshot_done := false
var smoke_scenario := false
var scenario_stage := -1
var record_dir := ""
var record_frames := 0
var record_timer := 0.0
var record_busy := false
var record_finished := false

func _ready() -> void:
    for arg in OS.get_cmdline_user_args():
        if arg == "--scenario":
            smoke_scenario = true
        if arg.begins_with("--record-dir="):
            record_dir = arg.split("=")[1]
            DirAccess.make_dir_recursive_absolute(record_dir)
        if arg.begins_with("--smoke-seconds="):
            smoke_seconds = float(arg.split("=")[1])
        if arg.begins_with("--smoke-output="):
            smoke_output = arg.split("=")[1]
    _build_world()
    _build_proxy()
    _build_ui()
    client.result_received.connect(_on_result)
    client.connection_changed.connect(func(ok: bool):
        connected_status = "Renderer connected" if ok else "Renderer offline — holding last image"
        _invalidate()
    )
    RenderingServer.set_default_clear_color(Color("070a0c"))
    last_frame_tick = Time.get_ticks_usec()

func _box(parent: Node3D, size: Vector3, position_: Vector3, color: Color, collision := false) -> MeshInstance3D:
    var node := MeshInstance3D.new()
    var mesh := BoxMesh.new()
    mesh.size = size
    node.mesh = mesh
    var mat := StandardMaterial3D.new()
    mat.albedo_color = color
    mat.roughness = 0.92
    node.material_override = mat
    node.position = position_
    parent.add_child(node)
    if collision:
        var body := StaticBody3D.new()
        var shape := CollisionShape3D.new()
        var box := BoxShape3D.new()
        box.size = size
        shape.shape = box
        body.add_child(shape)
        node.add_child(body)
    return node

func _build_world() -> void:
    var env_node := WorldEnvironment.new()
    var env := Environment.new()
    env.background_mode = Environment.BG_COLOR
    env.background_color = Color("080e12")
    env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    env.ambient_light_color = Color("6d8491")
    env.ambient_light_energy = 0.48
    env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
    env_node.environment = env
    add_child(env_node)
    _box(self, Vector3(14, 0.2, 18), Vector3(0, -0.1, -1), Color("293237"), true)
    _box(self, Vector3(14, 5, 0.3), Vector3(0, 2.5, -9), Color("28333a"), true)
    _box(self, Vector3(0.3, 5, 18), Vector3(-7, 2.5, -1), Color("293238"), true)
    _box(self, Vector3(0.3, 5, 18), Vector3(7, 2.5, -1), Color("293238"), true)
    _box(self, Vector3(14, 5, 0.3), Vector3(0, 2.5, 8), Color("293238"), true)
    _box(self, Vector3(14, 0.2, 18), Vector3(0, 5.1, -1), Color("171f24"))
    # Pillar between the player and creature for depth/occlusion testing.
    _box(self, Vector3(0.65, 3.7, 0.65), Vector3(1.5, 1.85, 0), Color("4c5557"), true)
    for i in range(9):
        _box(self, Vector3(0.025, 0.005, 18), Vector3(-6+1.5*i, 0.005, -1), Color("111c23"))
    for i in range(12):
        _box(self, Vector3(14, 0.005, 0.025), Vector3(0, 0.006, -8.5+1.5*i), Color("111c23"))
    for x in [-4.5, 4.5]:
        var light := OmniLight3D.new()
        light.position = Vector3(x, 3, -3)
        light.light_color = Color("8ac9c2") if x < 0 else Color("dd735c")
        light.light_energy = 2.5
        light.omni_range = 11
        add_child(light)
        var lamp := _box(self, Vector3(.8, .06, .12), Vector3(x, 3.7, -8.78), Color("a4d8cd"))
        var lamp_mat := lamp.material_override as StandardMaterial3D
        lamp_mat.emission_enabled = true
        lamp_mat.emission = light.light_color
        lamp_mat.emission_energy_multiplier = 2
    player = CharacterBody3D.new()
    player.position = Vector3(0, 0.95, 5)
    var capsule := CollisionShape3D.new()
    var shape := CapsuleShape3D.new()
    shape.radius = .25
    shape.height = 1.8
    capsule.shape = shape
    player.add_child(capsule)
    add_child(player)
    camera = Camera3D.new()
    camera.position.y = .65
    camera.fov = 65
    player.add_child(camera)
    camera.current = true
    camera.cull_mask = 3
    monster = Node3D.new()
    monster.position = Vector3(0, 1.65, -2.5)
    add_child(monster)
    var body := StaticBody3D.new()
    var body_shape := CollisionShape3D.new()
    var monster_capsule := CapsuleShape3D.new()
    monster_capsule.radius = .45
    monster_capsule.height = 3
    body_shape.shape = monster_capsule
    body.add_child(body_shape)
    monster.add_child(body)
    billboard = MeshInstance3D.new()
    var quad := QuadMesh.new()
    quad.size = Vector2(3.8, 3.8)
    billboard.mesh = quad
    billboard.layers = 2
    material = ShaderMaterial.new()
    material.shader = preload("res://shaders/creature.gdshader")
    billboard.material_override = material
    monster.add_child(billboard)

func _limb(parent: Node3D, pos: Vector3, scale_: Vector3) -> void:
    var limb := MeshInstance3D.new()
    var mesh := SphereMesh.new()
    mesh.height = 2
    mesh.radius = 1
    mesh.radial_segments = 16
    mesh.rings = 8
    limb.mesh = mesh
    limb.position = pos
    limb.scale = scale_
    var mat := StandardMaterial3D.new()
    mat.albedo_color = Color("b2a19a")
    mat.roughness = .9
    limb.material_override = mat
    parent.add_child(limb)

func _build_proxy() -> void:
    viewport = SubViewport.new()
    viewport.size = Vector2i(256, 256)
    viewport.transparent_bg = true
    viewport.own_world_3d = true
    viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
    add_child(viewport)
    var world := Node3D.new()
    viewport.add_child(world)
    var env_node := WorldEnvironment.new()
    var env := Environment.new()
    env.background_mode = Environment.BG_COLOR
    env.background_color = Color(0, 0, 0, 0)
    env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    env.ambient_light_color = Color.WHITE
    env.ambient_light_energy = .8
    env_node.environment = env
    world.add_child(env_node)
    proxy_root = Node3D.new()
    world.add_child(proxy_root)
    _build_anatomy(proxy_root)
    var light := DirectionalLight3D.new()
    light.rotation_degrees = Vector3(-30, -20, 0)
    light.light_energy = 1.1
    world.add_child(light)
    proxy_camera = Camera3D.new()
    proxy_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    proxy_camera.size = 3.8
    proxy_camera.position = Vector3(0, 1.65, 6)
    world.add_child(proxy_camera)
    proxy_camera.look_at(Vector3(0, 1.65, 0))
    proxy_camera.current = true

func _label(parent: Node, text_: String, font_size: int, color: Color) -> Label:
    var label := Label.new()
    label.text = text_
    label.add_theme_font_size_override("font_size", font_size)
    label.add_theme_color_override("font_color", color)
    parent.add_child(label)
    return label

func _slider(parent: Node, title: String, min_: float, max_: float, value_: float, step_: float, callback: Callable) -> void:
    var label := _label(parent, "%s  %.2f" % [title, value_], 13, Color("a7b9b5"))
    var slider := HSlider.new()
    slider.min_value = min_
    slider.max_value = max_
    slider.step = step_
    slider.value = value_
    slider.custom_minimum_size = Vector2(245, 18)
    slider.value_changed.connect(func(v: float):
        label.text = "%s  %.2f" % [title, v]
        callback.call(v)
    )
    parent.add_child(slider)
    if smoke_scenario:
        slider.mouse_filter = Control.MOUSE_FILTER_IGNORE
        slider.focus_mode = Control.FOCUS_NONE

func _build_ui() -> void:
    var canvas := CanvasLayer.new()
    add_child(canvas)
    var root := Control.new()
    root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    root.mouse_filter = Control.MOUSE_FILTER_IGNORE
    canvas.add_child(root)
    var left := VBoxContainer.new()
    left.position = Vector2(32, 26)
    root.add_child(left)
    _label(left, "S P O O K Y N E U R O", 25, Color("d5e6de"))
    _label(left, "C R E A T U R E   L A B   /   0 1", 12, Color("7c9e95"))
    status_label = _label(left, connected_status, 14, Color("b1c8bd"))
    metrics_label = _label(left, "Awaiting first creature image", 13, Color("91a9a1"))
    mode_label = _label(left, "", 13, Color("91a9a1"))
    var panel := PanelContainer.new()
    panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
    panel.position = Vector2(-310, 28)
    panel.size = Vector2(280, 365)
    var style := StyleBoxFlat.new()
    style.bg_color = Color(.025, .045, .05, .92)
    style.border_color = Color("3b514c")
    style.set_border_width_all(1)
    style.content_margin_left = 18
    style.content_margin_right = 18
    style.content_margin_top = 15
    style.content_margin_bottom = 15
    panel.add_theme_stylebox_override("panel", style)
    root.add_child(panel)
    var controls := VBoxContainer.new()
    controls.add_theme_constant_override("separation", 6)
    panel.add_child(controls)
    _label(controls, "MORPHOLOGY", 15, Color("c6d9d1"))
    _slider(controls, "Transformation", .5, 1., strength, .05, func(v): strength = v; _invalidate())
    _slider(controls, "Noise period · seconds", .5, 8., noise_period, .25, func(v): noise_period = v)
    _slider(controls, "Horror LoRA weight", 0., 1.5, lora_scale, .05, func(v): lora_scale = v)
    _slider(controls, "Transition duration", .25, 2., transition_scale, .05, func(v): transition_scale = v)
    mask_selector = OptionButton.new()
    mask_selector.add_item("Generated silhouette [M]")
    mask_selector.add_item("Guide silhouette [M]")
    mask_selector.item_selected.connect(func(index: int):
        mask_mode = ["free", "fixed"][index]
        _invalidate()
    )
    controls.add_child(mask_selector)
    var flow_button := CheckButton.new()
    flow_button.text = "Optical flow [I]"
    flow_button.button_pressed = true
    flow_button.toggled.connect(func(v): use_flow = v; material.set_shader_parameter("use_flow", false))
    controls.add_child(flow_button)
    var motion_button := CheckButton.new()
    motion_button.text = "Dread walk / approach [P]"
    motion_button.button_pressed = animate_monster
    motion_button.toggled.connect(func(v): animate_monster = v)
    controls.add_child(motion_button)
    # Keyboard shortcuts use the same controls to keep labels and state synchronized.
    flow_button.set_meta("shortcut_key", KEY_I)
    motion_button.set_meta("shortcut_key", KEY_P)
    var footer := _label(root, "WASD  move    ·    Hold RMB  look    ·    Shift  run    ·    F12  capture    ·    Esc  release cursor", 13, Color("a5bdb3"))
    footer.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
    footer.offset_left = 32
    footer.offset_top = -42
    footer.offset_right = 1000
    footer.offset_bottom = -16
    var reticle := _label(root, "+", 18, Color(.7, .9, .8, .5))
    reticle.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
    reticle.offset_left = -5
    reticle.offset_top = -10
    reticle.offset_right = 8
    reticle.offset_bottom = 12

func _invalidate() -> void:
    awaiting_fresh_frame = true
    last_result_at = elapsed
    epoch += 1
    queued.clear()
    transition_elapsed = transition_duration
    material.set_shader_parameter("progress", 1.0)

func _unhandled_input(event: InputEvent) -> void:
    if smoke_scenario:
        return
    if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT:
        Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if event.pressed else Input.MOUSE_MODE_VISIBLE
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        yaw -= event.relative.x * .002
        pitch = clampf(pitch - event.relative.y * .002, -1.2, 1.2)
    if event is InputEventKey and event.pressed and not event.echo:
        if event.keycode == KEY_ESCAPE:
            Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
        if event.keycode == KEY_M:
            mask_selector.select((mask_selector.selected + 1) % 2)
            mask_selector.item_selected.emit(mask_selector.selected)
        if event.keycode == KEY_F12:
            _capture_screenshot()
        for button in find_children("*", "CheckButton", true, false):
            if button.get_meta("shortcut_key", 0) == event.keycode:
                button.button_pressed = not button.button_pressed

func _physics_process(delta: float) -> void:
    player.rotation.y = yaw
    camera.rotation.x = pitch
    var axis := Vector2(float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)), float(Input.is_physical_key_pressed(KEY_S)) - float(Input.is_physical_key_pressed(KEY_W)))
    if smoke_scenario:
        axis = Vector2.ZERO
    var direction := (player.basis * Vector3(axis.x, 0, axis.y)).normalized()
    var speed := 5.0 if Input.is_physical_key_pressed(KEY_SHIFT) else 2.5
    player.velocity.x = direction.x * speed
    player.velocity.z = direction.z * speed
    if not player.is_on_floor():
        player.velocity.y -= 9.8 * delta
    else:
        player.velocity.y = 0
    player.move_and_slide()

func _process(delta: float) -> void:
    elapsed += delta
    if not record_dir.is_empty() and update_count >= 5 and not record_busy and not record_finished:
        record_timer += delta
        if record_timer >= .1:
            record_timer -= .1
            _record_frame()
    if smoke_scenario:
        _scenario()
    var now_tick := Time.get_ticks_usec()
    var wall_frame_ms := (now_tick - last_frame_tick) / 1000.0
    last_frame_tick = now_tick
    frame_times.append(wall_frame_ms)
    measured_frame_sum += wall_frame_ms
    measured_frame_count += 1
    if frame_times.size() > 36000:
        frame_times.pop_front()
    client.tick()
    is_stepping = false
    if animate_monster:
        var toward := player.global_position - monster.global_position
        toward.y = 0
        var distance := toward.length()
        if distance > 1.45:
            var pace := .32 + .12 * pow(maxf(0, sin(walk_phase)), 2)
            monster.position += toward.normalized() * pace * delta
            is_stepping = true
        if distance > .01:
            monster_heading = lerp_angle(monster_heading, atan2(toward.x, toward.z), minf(1, delta * 1.6))
    _animate_rig(delta)
    billboard.global_basis = camera.global_basis
    var direction := (camera.global_position - monster.global_position).normalized()
    if last_view_direction != Vector3.ZERO and direction.dot(last_view_direction) < .8:
        _invalidate()
        last_view_direction = direction
    if last_view_direction == Vector3.ZERO:
        last_view_direction = direction
    proxy_camera.position = Vector3(0, 1.65, 0) + direction * 6
    proxy_camera.look_at(Vector3(0, 1.65, 0))

    transition_elapsed += delta
    if transition_elapsed >= transition_duration and not queued.is_empty():
        _start_transition(queued.pop_front())
    material.set_shader_parameter("progress", clampf(transition_elapsed / transition_duration, 0, 1))
    capture_timer += delta
    var on_screen := not camera.is_position_behind(monster.global_position)
    if on_screen != previous_visible:
        _invalidate()
        previous_visible = on_screen
    if on_screen and capture_timer >= .2 and client.connected and not client.pending and not capture_busy:
        capture_timer = 0
        _capture_proxy()
    if current_id < 0 and elapsed > .1 and not capture_busy and DisplayServer.get_name() != "headless":
        var initial := viewport.get_texture().get_image()
        if initial != null and not initial.is_empty():
            if current_image == null:
                current_image = ImageTexture.create_from_image(initial)
            else:
                current_image.update(initial)
            material.set_shader_parameter("previous_image", current_image)
            material.set_shader_parameter("current_image", current_image)
    status_label.text = connected_status + ("  ·  MOCK / diagnostic warp" if diagnostic else "")
    metrics_label.text = "%d FPS  ·  %.0f ms round trip  ·  %.0f ms render  ·  %d updates" % [Engine.get_frames_per_second(), last_latency, last_render, update_count]
    mode_label.text = ("Generated silhouette" if mask_mode == "free" else "Guide silhouette") + "  /  " + ("Optical flow" if use_flow else "Crossfade")
    if smoke_seconds > 0 and Time.get_ticks_msec() / 1000.0 >= smoke_seconds:
        _save_smoke()
        get_tree().quit()
    if smoke_seconds > 0 and elapsed >= minf(10, smoke_seconds - 1) and update_count >= 5 and not screenshot_done:
        screenshot_done = true
        _capture_screenshot()

func _capture_proxy() -> void:
    capture_busy = true
    var capture_epoch := epoch
    var capture_phase := elapsed
    var capture_time := Time.get_ticks_msec()
    var selected_mode := mask_mode
    await RenderingServer.frame_post_draw
    var image := viewport.get_texture().get_image()
    capture_busy = false
    if image == null or image.is_empty():
        return
    serial += 1
    last_capture_ms = capture_time
    var meta := {"id": serial, "epoch": capture_epoch, "captured_ms": last_capture_ms, "phase": capture_phase,
        "strength": strength, "noise_period": noise_period, "lora_scale": lora_scale,
        "mask_mode": selected_mode, "interpolation": "flow" if use_flow else "blend"}
    client.send_image(meta, image)

func _on_result(header: Dictionary, blobs: Dictionary) -> void:
    if header.has("error"):
        connected_status = "Renderer error: " + str(header["error"])
        return
    if int(header.get("epoch", -1)) != epoch:
        return
    var image := Image.new()
    if not blobs.has("image") or image.load_png_from_buffer(blobs["image"]) != OK:
        return
    if image.get_width() > 512 or image.get_height() != image.get_width():
        return
    diagnostic = header.get("mock", false)
    last_latency = Time.get_ticks_msec() - int(header.get("captured_ms", last_capture_ms))
    last_render = header.get("render_ms", 0)
    update_count += 1
    connected_status = "Renderer connected"
    if awaiting_fresh_frame:
        # A different view/mask is a new sequence. Never morph from its stale predecessor.
        current_image = ImageTexture.create_from_image(image)
        current_id = int(header["id"])
        material.set_shader_parameter("previous_image", current_image)
        material.set_shader_parameter("current_image", current_image)
        material.set_shader_parameter("image_size", Vector2(image.get_width(), image.get_height()))
        material.set_shader_parameter("progress", 1.0)
        material.set_shader_parameter("use_flow", false)
        transition_elapsed = transition_duration
        last_result_at = elapsed
        last_display_age = last_latency
        awaiting_fresh_frame = false
        queued.clear()
        return
    var interval := clampf(elapsed - last_result_at, .05, 5.0)
    last_result_at = elapsed
    queued.append({"header": header, "blobs": blobs, "image": image, "interval": interval})
    if queued.size() > 2:
        queued.pop_front()

func _start_transition(result: Dictionary) -> void:
    var header: Dictionary = result["header"]
    var blobs: Dictionary = result["blobs"]
    var texture := ImageTexture.create_from_image(result["image"])
    material.set_shader_parameter("previous_image", current_image if current_image != null else texture)
    material.set_shader_parameter("current_image", texture)
    material.set_shader_parameter("image_size", Vector2(texture.get_width(), texture.get_height()))
    var valid_flow: bool = use_flow and header.get("previous_id") == current_id and blobs.has("forward") and blobs.has("backward")
    if valid_flow:
        var n := texture.get_width()
        valid_flow = blobs["forward"].size() == n*n*16 and blobs["backward"].size() == n*n*16
        if valid_flow:
            for name_ in ["forward", "backward"]:
                var flow_image := Image.create_from_data(n, n, false, Image.FORMAT_RGBAF, blobs[name_])
                material.set_shader_parameter(name_ + "_flow", ImageTexture.create_from_image(flow_image))
    material.set_shader_parameter("use_flow", valid_flow)
    if valid_flow:
        flow_transitions += 1
    else:
        blend_transitions += 1
    current_image = texture
    current_id = int(header["id"])
    transition_elapsed = 0
    transition_duration = clampf(float(result["interval"]) * transition_scale, .05, 5.0)
    last_display_age = Time.get_ticks_msec() - int(header.get("captured_ms", Time.get_ticks_msec())) + transition_duration * 1000

func _capture_screenshot() -> void:
    await RenderingServer.frame_post_draw
    var image := get_viewport().get_texture().get_image()
    var path := smoke_output + ".png" if not smoke_output.is_empty() else "user://creature_lab.png"
    image.save_png(path)
    viewport.get_texture().get_image().save_png(path.get_basename() + "_proxy.png")
    print("Saved screenshot: ", path)

func _save_smoke() -> void:
    if smoke_output.is_empty():
        return
    var sorted_times := frame_times.duplicate()
    sorted_times.sort()
    var mean := measured_frame_sum / maxf(1, measured_frame_count)
    var report := {"elapsed": Time.get_ticks_msec() / 1000.0, "simulation_elapsed": elapsed, "updates": update_count, "mock": diagnostic,
        "mean_frame_ms": mean, "frame_count": measured_frame_count, "wall_fps": 1000.0 / maxf(.001, mean),
        "flow_transitions": flow_transitions, "blend_transitions": blend_transitions, "last_display_age_ms": last_display_age,
        "p95_frame_ms": sorted_times[int(sorted_times.size()*.95)],
        "last_roundtrip_ms": last_latency, "last_render_ms": last_render}
    var file := FileAccess.open(smoke_output + ".json", FileAccess.WRITE)
    file.store_string(JSON.stringify(report, "  "))

func _scenario() -> void:
    # Repeatable camera and mode changes for the integration soak test.
    var stage := int(Time.get_ticks_msec() / 20000) % 6
    if stage != scenario_stage:
        scenario_stage = stage
        mask_mode = "fixed" if stage == 2 else "free"
        use_flow = stage != 2
        animate_monster = stage >= 2
        mask_selector.select(["free", "fixed"].find(mask_mode))
        _invalidate()
    if stage == 1 or stage == 4:
        player.position.x = sin(elapsed * .3) * 2.6
        yaw = -atan2(-player.position.x, 7.5)
    elif stage == 5:
        yaw = PI if fmod(elapsed, 10) < 5 else 0.0
    else:
        player.position.x = 0
        yaw = 0

func _build_anatomy(root: Node3D) -> void:
    # Overlapping volumes form a connected anatomical guide, including dark
    # sockets and mouth, a nose, hands, feet and asymmetry for img2img structure.
    _limb(root, Vector3(0, 1.75, 0), Vector3(.43, .55, .24))
    _limb(root, Vector3(0, 1.25, 0), Vector3(.29, .42, .21))
    _limb(root, Vector3(0, 1.0, 0), Vector3(.34, .24, .23))
    _limb(root, Vector3(0, 2.24, 0), Vector3(.16, .27, .17))
    _limb(root, Vector3(0, 2.65, 0), Vector3(.28, .36, .25))
    _limb(root, Vector3(0, 2.44, .04), Vector3(.22, .17, .22))
    _limb(root, Vector3(0, 2.63, .25), Vector3(.07, .1, .09))
    for side in [-1, 1]:
        _limb(root, Vector3(side*.43, 1.98, 0), Vector3(.23, .24, .23))
        _bone(root, Vector3(side*.48, 1.97, 0), Vector3(side*.65, 1.42, .02), .15)
        _limb(root, Vector3(side*.65, 1.42, .02), Vector3(.14, .15, .14))
        _bone(root, Vector3(side*.65, 1.42, .02), Vector3(side*.69, .89, .1), .105)
        _limb(root, Vector3(side*.7, .79, .1), Vector3(.12, .19, .085))
        for finger in range(4):
            _limb(root, Vector3(side*(.63 + finger*.045), .61, .11), Vector3(.025, .16, .03))
        _limb(root, Vector3(side*.58, .8, .13), Vector3(.04, .12, .04))
        _bone(root, Vector3(side*.22, 1.02, 0), Vector3(side*.25, .56, .015), .17)
        _limb(root, Vector3(side*.25, .56, .015), Vector3(.14, .17, .14))
        _bone(root, Vector3(side*.25, .56, .015), Vector3(side*.26, .11, .02), .105)
        _limb(root, Vector3(side*.26, .08, .12), Vector3(.13, .09, .23))
        var socket_start := root.get_child_count()
        _limb(root, Vector3(side*.115, 2.7, .225), Vector3(.083, .063, .045))
        var socket := root.get_child(socket_start) as MeshInstance3D
        (socket.material_override as StandardMaterial3D).albedo_color = Color("1b1115")
        _limb(root, Vector3(side*.115, 2.7, .265), Vector3(.027, .026, .015))
    var mouth_start := root.get_child_count()
    _limb(root, Vector3(0, 2.47, .235), Vector3(.12, .045, .035))
    (root.get_child(mouth_start).material_override as StandardMaterial3D).albedo_color = Color("32151a")
    # Raised ribs provide local surface cues without cutting the silhouette.
    for rib in range(4):
        _limb(root, Vector3(0, 1.65+rib*.105, .2), Vector3(.32-rib*.012, .035, .055))
    _articulate(root)

func _bone(root: Node3D, from: Vector3, to: Vector3, radius: float) -> void:
    var at := root.get_child_count()
    _limb(root, (from+to)*.5, Vector3(radius, from.distance_to(to)*.5+radius*.45, radius))
    var bone := root.get_child(at) as Node3D
    var direction := (to-from).normalized()
    var rotation_axis := Vector3.UP.cross(direction)
    if rotation_axis.length_squared() > .0001:
        bone.quaternion = Quaternion(rotation_axis.normalized(), Vector3.UP.angle_to(direction))

func _joint(root: Node3D, parent: Node3D, joint_name: String, origin: Vector3) -> Node3D:
    var joint := Node3D.new()
    joint.name = joint_name
    parent.add_child(joint)
    joint.global_position = root.to_global(origin)
    rig[joint_name] = joint
    return joint

func _articulate(root: Node3D) -> void:
    var parts := root.get_children()
    var chest := _joint(root, root, "Chest", Vector3(0, 1.08, 0))
    var head := _joint(root, chest, "Head", Vector3(0, 2.24, 0))
    for side in [-1, 1]:
        var suffix := "L" if side < 0 else "R"
        var shoulder := _joint(root, chest, "Shoulder" + suffix, Vector3(side*.43, 1.98, 0))
        var elbow := _joint(root, shoulder, "Elbow" + suffix, Vector3(side*.65, 1.42, .02))
        _joint(root, elbow, "Wrist" + suffix, Vector3(side*.69, .89, .1))
        var hip := _joint(root, root, "Hip" + suffix, Vector3(side*.22, 1.06, 0))
        var knee := _joint(root, hip, "Knee" + suffix, Vector3(side*.25, .56, .015))
        _joint(root, knee, "Ankle" + suffix, Vector3(side*.26, .11, .02))
    for part in parts:
        if not part is MeshInstance3D:
            continue
        var p: Vector3 = part.position
        var suffix := "L" if p.x < 0 else "R"
        var target: Node3D = root
        if p.y > 2.34:
            target = head
        elif absf(p.x) > .4 and p.y > .42:
            var name_ := "Shoulder" if p.y > 1.5 else ("Elbow" if p.y > .95 else "Wrist")
            target = rig[name_ + suffix]
        elif p.y < 1.05 and absf(p.x) >= .12 and absf(p.x) < .4:
            var name_ := "Hip" if p.y > .6 else ("Knee" if p.y > .15 else "Ankle")
            target = rig[name_ + suffix]
        elif p.y >= 1.2:
            target = chest
        if target != root:
            part.reparent(target, true)

func _animate_rig(delta: float) -> void:
    if rig.is_empty():
        return
    var walking := 1.0 if is_stepping else .12
    walk_phase += delta * (3.1 if is_stepping else 1.3)
    var beat := walk_phase
    proxy_root.position.y = .025 * sin(beat * 2) * walking
    proxy_root.rotation = Vector3(0, monster_heading, .025 * sin(beat) * walking)
    proxy_root.scale.y = 1 + .007 * sin(elapsed * 2.4)
    rig["Chest"].rotation = Vector3(.19 + .055 * sin(beat * 2), .07 * sin(beat), .07 * sin(beat+.5) * walking)
    # Short impulses at irregular intervals give the head a brief, unnatural snap.
    var pulse := pow(maxf(0, sin(elapsed * 1.71)), 24)
    rig["Head"].rotation = Vector3(-.17 + .06 * sin(elapsed * .8), .1 * sin(elapsed * .9) + pulse * .28, .12 + pulse * .13)
    for side in [-1, 1]:
        var suffix := "L" if side < 0 else "R"
        var phase: float = beat + (PI if side < 0 else 0)
        var stride := sin(phase)
        var asymmetry := .7 if side < 0 else 1.0
        rig["Hip"+suffix].rotation.x = -.43 * stride * walking * asymmetry
        rig["Knee"+suffix].rotation.x = -.08 - .56 * maxf(0, -stride) * walking * asymmetry
        rig["Ankle"+suffix].rotation.x = .08 + .13 * maxf(0, stride) * walking
        rig["Shoulder"+suffix].rotation = Vector3(.25 * stride * walking, side * -.09, side * .045)
        rig["Elbow"+suffix].rotation.x = -.13 - .16 * maxf(0, stride) * walking
        rig["Wrist"+suffix].rotation = Vector3(.18, .06 * sin(phase * 1.4), side * .08)

func _record_frame() -> void:
    record_busy = true
    await RenderingServer.frame_post_draw
    var image := get_viewport().get_texture().get_image()
    image.save_png(record_dir.path_join("frame_%05d.png" % record_frames))
    record_frames += 1
    record_busy = false
    if record_frames >= 120:
        record_finished = true
        print("Recorded 120 game frames in ", record_dir)
        _save_smoke()
        get_tree().quit()
