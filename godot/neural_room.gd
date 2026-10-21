extends "res://main.gd"
## The mesh experiment remains in room_3d.tscn; this scene renders a neural volume.
const Paths = preload("res://runtime_paths.gd")
const SETTINGS = "user://neural_field_settings_v3.json"
const FIELD_DEFAULTS = {"seed":217,"strength":.82,"motion":.5,"resolution":192,"duration":6.0,"effects":.35,"paused":false}
var settings := FIELD_DEFAULTS.duplicate()
var entity = preload("res://neural_entity.gd").new()
var stage = preload("res://realism_stage.gd").new()
var interface: CanvasLayer
var session := ""
var preview_root := ""
var preview_folders: Array[String] = []
var preview_index := 0
var preview_direction := 1
var buffered := 0
var starved_seconds := 0.0
var played_sequences: Array[int] = []
var last_sequence := 0
var last_acknowledged := 0
var poll_clock := 0.0
var started := 0
var orbit_mode := false
var no_fx := false
var error_text := ""
var generation_label: Label
var saving := false
var dust: Array[MeshInstance3D] = []

func _ready() -> void:
    # The inherited TCP image client is not used by spatial field packets.
    client = null
    if "--legacy-mesh" in OS.get_cmdline_user_args() or "--mutation-demo" in OS.get_cmdline_user_args():
        entity.free()
        stage.free()
        get_tree().change_scene_to_file("res://room_3d.tscn")
        return
    if FileAccess.file_exists(SETTINGS):
        var saved = JSON.parse_string(FileAccess.get_file_as_string(SETTINGS))
        if saved is Dictionary:
            for key in FIELD_DEFAULTS:
                if saved.has(key) and (saved[key] is float or saved[key] is int or saved[key] is bool):
                    settings[key] = saved[key]
    settings.paused = false
    for arg in OS.get_cmdline_user_args():
        if arg == "--defaults" or arg.begins_with("--smoke-"):
            settings = FIELD_DEFAULTS.duplicate()
    if "--export-launch-settings" in OS.get_cmdline_user_args():
        for arg in OS.get_cmdline_user_args():
            if arg.begins_with("--output="):
                _write_json(arg.trim_prefix("--output="),settings)
        entity.free()
        stage.free()
        get_tree().quit()
        return
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--prepared-session="):
            session = arg.trim_prefix("--prepared-session=")
        if arg.begins_with("--field-preview="):
            preview_root = arg.trim_prefix("--field-preview=")
        if arg == "--scenario":
            orbit_mode = true
            smoke_scenario = true
        if arg == "--no-mutation-fx":
            no_fx = true
        if arg.begins_with("--smoke-seconds="):
            smoke_seconds = float(arg.trim_prefix("--smoke-seconds="))
        if arg.begins_with("--smoke-output="):
            smoke_output = arg.trim_prefix("--smoke-output=")
        if arg.begins_with("--record-dir="):
            record_dir = arg.trim_prefix("--record-dir=")
            DirAccess.make_dir_recursive_absolute(record_dir)
    _build_world()
    billboard.free()
    billboard = null
    monster.position = Vector3(0,1.5,0)
    add_child(stage)
    stage.build(self)
    stage.lens_strength = 0.0
    stage.lens.set_shader_parameter("strength",0.0)
    add_child(entity)
    entity.build(camera)
    _build_ui()
    _build_dust()
    if "--cinematic" in OS.get_cmdline_user_args():
        interface.hide()
    if session.is_empty():
        if preview_root.is_empty():
            preview_root = Paths.resolve("res://../assets/neural_entity")
        for folder in DirAccess.get_directories_at(preview_root):
            if FileAccess.file_exists(preview_root.path_join(folder).path_join("field.json")):
                preview_folders.append(preview_root.path_join(folder))
        preview_folders.sort()
        if preview_folders.is_empty():
            error_text = "Нет сохранённых нейронных объёмов. Запустите Start SpookyNeuro.cmd."
        else:
            _next_preview()
            _next_preview()
    else:
        _poll()
        _poll()
    started = Time.get_ticks_msec()
    last_frame_tick = Time.get_ticks_usec()

func _write_json(path: String, data: Dictionary) -> bool:
    var file := FileAccess.open(path+".tmp",FileAccess.WRITE)
    if file == null:
        error_text = "Не удалось записать "+path
        return false
    file.store_string(JSON.stringify(data))
    file.close()
    if DirAccess.rename_absolute(path+".tmp",path) != OK:
        error_text = "Не удалось записать "+path
        return false
    return true

func _publish_settings() -> void:
    _write_json(SETTINGS,settings)
    if not session.is_empty():
        _write_json(session.path_join("settings.json"),settings)

func _build_ui() -> void:
    interface = CanvasLayer.new()
    interface.layer = 10
    add_child(interface)
    var panel := PanelContainer.new()
    panel.position = Vector2(20,20)
    interface.add_child(panel)
    var margin := MarginContainer.new()
    for side in ["left","right","top","bottom"]:
        margin.add_theme_constant_override("margin_"+side,16)
    panel.add_child(margin)
    var stack := VBoxContainer.new()
    margin.add_child(stack)
    _label(stack,"НЕУСТОЙЧИВАЯ СУЩНОСТЬ",20,Color("dfddd3"))
    status_label = _label(stack,"",14,Color("b5bdb4"))
    metrics_label = _label(stack,"",13,Color("8eaaa1"))
    generation_label = _label(stack,"",13,Color("c7a799"))
    _slider(stack,"Сила перерисовки",.5,.95,float(settings.strength),.01,func(v): settings.strength=v; _publish_settings())
    _slider(stack,"Шаг шума",.15,1.0,float(settings.motion),.05,func(v): settings.motion=v; _publish_settings())
    _slider(stack,"Длительность превращения",4.0,16.0,float(settings.duration),.25,func(v): settings.duration=v; _publish_settings())
    _slider(stack,"Искажение пространства",0.0,1.0,float(settings.effects),.05,func(v): settings.effects=v; _publish_settings())
    var orbit_button := CheckButton.new()
    orbit_button.text = "Обход по кругу [O]"
    orbit_button.button_pressed = orbit_mode
    orbit_button.toggled.connect(func(v): orbit_mode=v)
    stack.add_child(orbit_button)
    _label(stack,"WASD / ПКМ — движение и обзор\nM — заморозить • G — пауза генерации\nN — следующий объём в демо • Tab — панель\nF — эффекты • F12 — снимок",13,Color("9faaa6"))

func _build_dust() -> void:
    var mat := StandardMaterial3D.new()
    mat.albedo_color = Color("7c6260")
    var mesh := SphereMesh.new()
    mesh.radius = .009
    mesh.height = .018
    mesh.radial_segments = 6
    mesh.rings = 3
    for i in range(24):
        var mote := MeshInstance3D.new()
        mote.mesh = mesh
        mote.material_override = mat
        mote.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
        add_child(mote)
        dust.append(mote)

func _next_preview() -> void:
    if preview_folders.is_empty() or not entity.pending.is_empty():
        return
    var folder := preview_folders[preview_index]
    var success: bool = entity.load_field(folder) if entity.updates==0 else entity.queue_field(folder)
    if not success:
        error_text = entity.error
        return
    if preview_folders.size()>1:
        # Reverse at the end instead of jumping from the last face back to the first.
        if preview_index==preview_folders.size()-1: preview_direction=-1
        elif preview_index==0: preview_direction=1
        preview_index += preview_direction

func _acknowledge() -> void:
    var shown := int(entity.packet.get("sequence",0))
    if not session.is_empty() and shown>last_sequence:
        last_sequence = shown
        played_sequences.append(shown)
    if not session.is_empty() and shown>last_acknowledged:
        if _write_json(session.path_join("ack.json"),{"sequence":shown}):
            last_acknowledged = shown
            if error_text.begins_with("Не удалось записать "):
                error_text = ""

func _poll() -> void:
    if session.is_empty():
        return
    var path := session.path_join("queue.json")
    if not FileAccess.file_exists(path):
        return
    var queue = JSON.parse_string(FileAccess.get_file_as_string(path))
    if not queue is Dictionary or not queue.get("packets") is Array:
        return
    buffered = 0
    var wanted: Dictionary = {}
    for entry in queue.packets:
        if not entry is Dictionary: continue
        var seq := int(entry.get("sequence",0))
        if seq>last_sequence: buffered+=1
        if seq==last_sequence+1: wanted=entry
    if wanted.is_empty() or not entity.pending.is_empty():
        return
    var folder := str(wanted.get("directory","")).replace("\\","/").simplify_path()
    if folder.get_base_dir() != session.replace("\\","/").simplify_path():
        error_text = "Пакет вне каталога сессии"
        return
    var success: bool = entity.load_field(folder) if entity.updates==0 else entity.queue_field(folder)
    if success:
        error_text = ""
        _acknowledge()
    else:
        error_text = entity.error

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT:
        Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if event.pressed else Input.MOUSE_MODE_VISIBLE
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        orbit_mode = false
        yaw -= event.relative.x*.002
        pitch = clampf(pitch-event.relative.y*.002,-1.2,1.2)
    if event is InputEventKey and event.pressed and not event.echo:
        match event.keycode:
            KEY_ESCAPE: Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
            KEY_M: entity.frozen = not entity.frozen
            KEY_G:
                settings.paused = not settings.paused
                _publish_settings()
            KEY_O: orbit_mode = not orbit_mode
            KEY_N:
                if session.is_empty() and not entity.pending.is_empty(): entity.progress=1.0
            KEY_F: no_fx = not no_fx
            KEY_TAB: interface.visible = not interface.visible
            KEY_F12: _capture_screenshot()

func _physics_process(delta: float) -> void:
    if player == null:
        return
    if orbit_mode:
        var angle := elapsed*TAU/30.0
        player.position = Vector3(sin(angle)*4.7,.95,cos(angle)*4.7)
        player.rotation.y = angle
        camera.rotation.x = -.015
        yaw = angle
        return
    super._physics_process(delta)

func _process(delta: float) -> void:
    if started==0 or saving:
        return
    elapsed = (Time.get_ticks_msec()-started)/1000.0
    var tick := Time.get_ticks_usec()
    var ms := (tick-last_frame_tick)/1000.0
    last_frame_tick = tick
    frame_times.append(ms)
    if frame_times.size()>36000:
        frame_times.pop_front()
    entity.duration = clampf(float(settings.duration),4,16)
    if not session.is_empty() and buffered<=1:
        entity.duration = maxf(entity.duration,float(entity.packet.get("seconds",0))*1.25)
    entity.effects = 0.0 if no_fx else clampf(float(settings.effects),0,1)
    if not session.is_empty() and entity.updates>1 and entity.progress>=1.0 and entity.pending.is_empty() and not entity.frozen:
        starved_seconds += delta
    entity.advance(delta)
    _acknowledge()
    stage.advance(delta)
    poll_clock += delta
    if poll_clock>.10:
        poll_clock = 0
        if not session.is_empty():
            _poll()
        elif entity.pending.is_empty() and not entity.frozen:
            _next_preview()
    status_label.text = "Живая нейрогенерация" if not session.is_empty() else "Демо: сохранённые нейронные объёмы"
    if entity.frozen: status_label.text += " · заморожено"
    metrics_label.text = "%d FPS · %d объёмов · превращение %d%%" % [Engine.get_frames_per_second(),entity.updates,entity.progress*100]
    if not session.is_empty(): metrics_label.text += " · буфер %d"%buffered
    generation_label.text = error_text
    if not session.is_empty() and FileAccess.file_exists(session.path_join("status.json")):
        var state = JSON.parse_string(FileAccess.get_file_as_string(session.path_join("status.json")))
        if state is Dictionary:
            generation_label.text = str(state.get("stage",""))
            if state.has("error"): generation_label.text += ": "+str(state.error)
    var focus = entity.packet.get("focus",[0,1.8,0])
    var target := Vector3(float(focus[0]),float(focus[1]),float(focus[2]))
    var pulse: float = sin(entity.progress*PI)*float(entity.packet.get("change",0))*entity.effects
    for i in range(dust.size()):
        dust[i].visible = pulse>.015
        var phase := fposmod(entity.clock*.3+float(i)/dust.size(),1.0)
        var angle: float = i*2.4+entity.clock*.4
        dust[i].position = target+Vector3(cos(angle),sin(angle*1.3)*.7,sin(angle))*(1-phase)*(.3+pulse)
    if not record_dir.is_empty() and not record_busy:
        record_timer += delta
        if record_timer>=.1:
            record_timer = 0
            _record_volume_frame()
    if smoke_seconds>0 and elapsed>=smoke_seconds:
        saving = true
        _finish_smoke()

func _record_volume_frame() -> void:
    record_busy = true
    await RenderingServer.frame_post_draw
    get_viewport().get_texture().get_image().save_png(record_dir.path_join("%05d.png"%record_frames))
    record_frames += 1
    record_busy = false

func _capture_screenshot() -> void:
    await RenderingServer.frame_post_draw
    var path := "user://neural_entity.png"
    get_viewport().get_texture().get_image().save_png(path)
    print("Saved screenshot: ",ProjectSettings.globalize_path(path))

func _finish_smoke() -> void:
    await RenderingServer.frame_post_draw
    var image := get_viewport().get_texture().get_image()
    if not smoke_output.is_empty():
        image.save_png(smoke_output+".png")
        frame_times.sort()
        var sum := 0.0
        for ms in frame_times: sum+=ms
        _write_json(smoke_output+".json",{"error":error_text,"updates":entity.updates,
            "live_updates":last_sequence,"seconds":elapsed,"fps":1000*frame_times.size()/maxf(sum,1),
            "p95_ms":frame_times[int((frame_times.size()-1)*.95)],"effects":entity.effects,
            "starved_seconds":starved_seconds,"played_sequences":played_sequences,
            "representation":"neural_density_rgba8","orbit_degrees":elapsed*12 if orbit_mode else 0})
    get_tree().quit(0 if error_text.is_empty() else 1)

func _exit_tree() -> void:
    if not session.is_empty():
        var file := FileAccess.open(session.path_join("stop"),FileAccess.WRITE)
        if file: file.store_string("stop")
