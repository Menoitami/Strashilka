extends "res://main.gd"

const Creature = preload("res://skinned_creature.gd")
const RuntimePaths = preload("res://runtime_paths.gd")
var actor = Creature.new()
var evaporation = preload("res://evaporation.gd").new()
var evaporation_button: CheckButton
var evaporation_controls := {}
var no_evaporation := false
var stage = preload("res://realism_stage.gd").new()
var mutations = preload("res://mutation_director.gd").new()
var mutation_demo := false
var mutation_demo_clock := 0.0
var mutation_demo_sequence := 1
var no_mutation_fx := false
var stage_controls := {}
var flashlight_button: CheckButton
var approach_button: CheckButton
var view_control: OptionButton
var interface: CanvasLayer
var cinematic := false
var enemy: CharacterBody3D
var mesh_path := "res://../artifacts/3d/generated/creature.glb"
var model_error := ""
var spawn := Vector3.ZERO
var approach_distance := 0.0
var scene_started := 0
var settings_controls := {}
var morph_button: CheckButton
var generation_button: Button
var generation_label: Label
var generation_pid := -1
var generation_directory := ""
var generation_poll := 0.0
var seed_input: SpinBox
var demo := false
var initial_form := -1.0
var live_enabled := false
var force_live := false
var offline := false
var last_sequence := 0
var live_updates := 0
var live_times: Array[float] = []
var last_face_sequence := 0
var face_updates := 0
var face_during_body := 0
var face_times: Array[float] = []
const LIVE_DEFAULTS = {"randomness": .5, "strength": .65, "size": 384, "resolution": 96, "coherence": .9, "feedback": .95, "shape_step": .04, "appearance_step": .8, "body_horror": .2, "texture_strength": .45, "face_strength": .64, "face_amount": .9, "face_size": 512, "texture_steps": 6, "color_stability": 1.0, "face_updates": 3}
var live_settings := LIVE_DEFAULTS.duplicate()
var live_controls := {}
var live_status: Label
var record_after_updates := 0
var prepared_session := ""
var prepared_worker := -1
var prepared_packet: Dictionary = {}

const SETTINGS_FILE = "user://realism_settings_v5.json"
const DEFAULTS = {"mutation_amount": 1.0, "transition_seconds": 1.2, "hold_seconds": 2.0,
    "color_blend": 1.0, "relief_blend": 1.0, "relief_strength": .5, "roughness_value": .73, "walk_speed": .82,
    "flow_amount": .009, "flow_speed": .65, "monochrome": .12, "contrast_value": 1.0, "skin_detail": .65, "skin_wetness": .35, "face_transition_seconds": 1.2,
    "face_geometry": 1.0, "anatomy_amount": 1.0, "effects_amount": .75, "mutation_audio": .35}


func _ready() -> void:
    if "--export-launch-settings" in OS.get_cmdline_user_args():
        var exporter = load("res://tools/export_launch_settings.gd")
        var result: int = exporter.export_settings(OS.get_cmdline_user_args())
        for unused in [actor, evaporation, stage, mutations]:
            unused.free()
        get_tree().quit(result)
        return
    if mesh_path == "res://../artifacts/3d/generated/creature.glb" and FileAccess.file_exists(RuntimePaths.resolve("res://../assets/creature/realistic/creature.glb")):
        mesh_path = "res://../assets/creature/realistic/creature.glb"
    for arg in OS.get_cmdline_user_args():
        if arg == "--mutation-demo":
            mutation_demo = true
            offline = true
        if arg == "--no-mutation-fx":
            no_mutation_fx = true
        if arg.begins_with("--mutation-family="):
            mutation_demo_sequence = clampi(int(arg.trim_prefix("--mutation-family=")),0,3)
        if arg == "--cinematic":
            cinematic = true
        if arg.begins_with("--prepared-session="):
            prepared_session = arg.trim_prefix("--prepared-session=")
        if arg.begins_with("--prepared-worker="):
            prepared_worker = int(arg.trim_prefix("--prepared-worker="))
        if arg == "--live":
            force_live = true
        if arg == "--no-evaporation":
            no_evaporation = true
        if arg == "--offline":
            offline = true
        if arg.begins_with("--record-after-updates="):
            record_after_updates = int(arg.trim_prefix("--record-after-updates="))
        if arg == "--morph-demo":
            demo = true
            smoke_scenario = true
        if arg.begins_with("--form="):
            initial_form = float(arg.trim_prefix("--form="))
        if arg == "--scenario":
            smoke_scenario = true
        if arg.begins_with("--smoke-seconds="):
            smoke_seconds = float(arg.trim_prefix("--smoke-seconds="))
        if arg.begins_with("--smoke-output="):
            smoke_output = arg.trim_prefix("--smoke-output=")
        if arg.begins_with("--output="):
            smoke_output = arg.trim_prefix("--output=")
        if arg.begins_with("--model="):
            mesh_path = arg.trim_prefix("--model=")
        if arg.begins_with("--record-dir="):
            record_dir = arg.trim_prefix("--record-dir=")
            DirAccess.make_dir_recursive_absolute(record_dir)
    if not prepared_session.is_empty():
        var loaded_packet = JSON.parse_string(FileAccess.get_file_as_string(prepared_session.path_join("latest.json")))
        if not loaded_packet is Dictionary or prepared_worker <= 0 or FileAccess.file_exists(prepared_session.path_join("worker_exited")):
            push_error("Prepared neural worker or packet is missing")
            get_tree().quit(1)
            return
        prepared_packet = loaded_packet
        mesh_path = prepared_packet.directory.path_join("creature.glb")
    _build_world()
    add_child(stage)
    stage.build(self)
    # Reuse the same room, player and collider layout, replacing the image plane.
    var initial_position := monster.position
    monster.free()
    billboard = null
    enemy = CharacterBody3D.new()
    enemy.name = "NeuralMonster"
    enemy.position = initial_position
    add_child(enemy)
    monster = enemy
    var shape := CollisionShape3D.new()
    var capsule := CapsuleShape3D.new()
    capsule.height = 3
    capsule.radius = .43
    shape.shape = capsule
    shape.position.y = -.15
    enemy.add_child(shape)
    actor.position.y = -1.65
    enemy.add_child(actor)
    var loaded: Error = actor.load_model(mesh_path)
    if loaded != OK:
        model_error = "Cannot load 3D monster — run scripts/run_3d.sh --generate"
        push_error(model_error)
        if not prepared_session.is_empty():
            get_tree().quit(1)
            return
    add_child(evaporation)
    add_child(mutations)
    mutations.build(camera)
    spawn = enemy.position
    for light in find_children("*", "OmniLight3D", true, false):
        light.shadow_enabled = true
    actor.automatic = false
    actor.hold_seconds = 0
    for property in DEFAULTS:
        actor.set(property, DEFAULTS[property])
    _build_ui()
    if not smoke_scenario:
        _load_settings()
    if no_evaporation:
        evaporation_button.button_pressed = false
    if no_mutation_fx:
        actor.effects_amount = 0
        actor.mutation_audio = 0
    if initial_form >= 0:
        actor.select_form(initial_form)
    if demo:
        animate_monster = false
        player.position = Vector3(0, .95, 2.3)
        settings_controls["transition_seconds"].value = DEFAULTS.transition_seconds
        settings_controls["hold_seconds"].value = 0
        for button in find_children("*", "CheckButton", true, false):
            if button.get_meta("shortcut_key", 0) == KEY_P:
                button.set_pressed_no_signal(false)
    last_frame_tick = Time.get_ticks_usec()
    scene_started = last_frame_tick
    if not actor.mutation_plan.is_empty():
        mutations.submit(actor.mutation_plan,actor)
    elif mutation_demo:
        _demo_mutation()
    if not prepared_packet.is_empty():
        generation_directory = prepared_session
        generation_pid = prepared_worker
        live_enabled = true
        last_sequence = int(prepared_packet.sequence)
        live_updates = 1
        live_times.append(float(prepared_packet.seconds))
        # First visible frame is the completed neural target, not its base endpoint.
        actor.live_progress = actor.transition_seconds+actor.hold_seconds
        var saved_mutation: bool = actor.mutation
        actor.mutation = true
        actor._pose(0)
        actor.mutation = saved_mutation
        generation_button.text = "Остановить поток ИИ [G]"
        live_status.text = "Нейрорендер готов · первая форма загружена"
        generation_label.text = "Работающий поток подхвачен без перезагрузки моделей."
        _write_live_settings()
        FileAccess.open(generation_directory.path_join("ack.json"), FileAccess.WRITE).store_string(JSON.stringify({"sequence": last_sequence}))
        print("READY FIRST FRAME: sequence=", last_sequence, " weights=", actor.form_weights, " worker=", generation_pid)
    elif not offline and (force_live or (not smoke_scenario and smoke_seconds == 0 and DisplayServer.get_name() != "headless")):
        call_deferred("_start_generation")

func _build_ui() -> void:
    var canvas := CanvasLayer.new()
    interface = canvas
    interface.visible = not cinematic
    add_child(canvas)
    var root := Control.new()
    root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    root.mouse_filter = Control.MOUSE_FILTER_IGNORE
    canvas.add_child(root)
    var info := VBoxContainer.new()
    info.position = Vector2(30, 24)
    root.add_child(info)
    _label(info, "S P O O K Y N E U R O", 25, Color("d5e6de"))
    _label(info, "CREATURE ROOM  /  NEURAL 3D", 13, Color("9ab8ae"))
    status_label = _label(info, "Skinned 3D monster · 19 bones", 14, Color("b1c8bd"))
    metrics_label = _label(info, "", 13, Color("91a9a1"))
    var panel := PanelContainer.new()
    panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
    panel.position = Vector2(-326, 20)
    panel.custom_minimum_size = Vector2(306, 0)
    root.add_child(panel)
    var margin := MarginContainer.new()
    for side in ["left", "right", "top", "bottom"]:
        margin.add_theme_constant_override("margin_"+side, 12)
    panel.add_child(margin)
    var scroll := ScrollContainer.new()
    scroll.custom_minimum_size = Vector2(282, minf(590, get_viewport().get_visible_rect().size.y-90))
    scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
    margin.add_child(scroll)
    var controls := VBoxContainer.new()
    controls.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    scroll.add_child(controls)
    _label(controls, "ЛАБОРАТОРИЯ ФОРМ", 16, Color("c6d9d1"))
    var dream_button := Button.new()
    dream_button.text = "Пресет: реалистичная плоть"
    dream_button.pressed.connect(func():
        _apply_settings(DEFAULTS)
        settings_controls["transition_seconds"].value = DEFAULTS.transition_seconds
        settings_controls["hold_seconds"].value = 0
    )
    controls.add_child(dream_button)
    flashlight_button = _toggle(controls, "Фонарь [F]", true, func(v): stage.flashlight.visible = v, KEY_F)
    for spec in [["Свет помещения", "light_level", .25, 2], ["Виньетка / зерно", "lens_strength", 0, 1]]:
        var property: String = spec[1]
        _slider(controls, spec[0], spec[2], spec[3], stage.get(property), .05, func(v): stage.set(property, v))
        stage_controls[property] = controls.get_child(controls.get_child_count()-1)
    _label(controls, "Tab — скрыть панель", 12, Color("a7b9b5"))
    live_status = _label(controls, "LIVE: новые случайные 3D-формы", 13, Color("89c7b2"))
    live_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    live_status.custom_minimum_size.x = 260
    generation_button = Button.new()
    generation_button.text = "Запустить поток ИИ [G]"
    generation_button.pressed.connect(_start_generation)
    controls.add_child(generation_button)
    morph_button = _toggle(controls, "Время превращения [M]", true, func(v): actor.mutation = v, KEY_M)
    _setting(controls, "Изменение анатомии", "anatomy_amount", 0, 1, .05)
    _setting(controls, "Объём лица", "face_geometry", 0, 1, .05)
    _setting(controls, "Искажение пространства", "effects_amount", 0, 1, .05)
    _setting(controls, "Звук мутации", "mutation_audio", 0, 1, .05)
    var mutation_button := Button.new()
    mutation_button.text = "Демонстрация мутации [N]"
    mutation_button.pressed.connect(_demo_mutation)
    controls.add_child(mutation_button)
    evaporation_button = _toggle(controls, "Тёмное испарение [V]", true, func(v): evaporation.enabled = v, KEY_V)
    for spec in [["Плотность испарения", "density", 0, 2, .05], ["Подъём испарения", "rise_speed", .1, 1.5, .05]]:
        var property: String = spec[1]
        _slider(controls, spec[0], spec[2], spec[3], evaporation.get(property), spec[4], func(v): evaporation.set(property, v))
        evaporation_controls[property] = controls.get_child(controls.get_child_count()-1)
    _setting(controls, "Амплитуда геометрии", "mutation_amount", 0, 1, .01)
    _setting(controls, "Течение поверхности, м", "flow_amount", 0, .18, .005)
    _setting(controls, "Скорость течения", "flow_speed", 0, 3, .05)
    _setting(controls, "Переход, сек", "transition_seconds", .2, 15, .1)
    _setting(controls, "Переход лица, сек", "face_transition_seconds", .2, 6, .1)
    _setting(controls, "Удержание формы, сек", "hold_seconds", 0, 10, .1)
    _setting(controls, "Смена текстуры", "color_blend", 0, 1, .01)
    _setting(controls, "Смена карты нормалей", "relief_blend", 0, 1, .01)
    _setting(controls, "Сила рельефа", "relief_strength", 0, 2, .05)
    _setting(controls, "Шероховатость", "roughness_value", .05, 1, .05)
    _setting(controls, "Микрофактура кожи", "skin_detail", 0, 1, .05)
    _setting(controls, "Влажность кожи", "skin_wetness", 0, 1, .05)
    _setting(controls, "Монохромность материала", "monochrome", 0, 1, .05)
    _setting(controls, "Контраст фактуры", "contrast_value", .5, 2.5, .05)
    var view := OptionButton.new()
    view_control = view
    for label in ["Материал: полный", "Диагностика: серая геометрия", "Диагностика: карта нормалей"]:
        view.add_item(label)
    view.item_selected.connect(func(v): actor.debug_view = v)
    controls.add_child(view)
    _setting(controls, "Скорость походки", "walk_speed", .1, 2, .05)
    approach_button = _toggle(controls, "Приближаться к игроку [P]", true, func(v): animate_monster = v, KEY_P)
    var buttons := HBoxContainer.new()
    controls.add_child(buttons)
    for label in ["Сохранить", "Загрузить", "Сброс"]:
        var button := Button.new()
        button.text = label
        button.pressed.connect(func():
            if label == "Сохранить":
                _save_settings()
            elif label == "Загрузить":
                _load_settings()
            else:
                _apply_settings(DEFAULTS)
        )
        buttons.add_child(button)
    _label(controls, "ПАРАМЕТРЫ ЖИВОЙ ГЕНЕРАЦИИ", 13, Color("c6d9d1"))
    _slider(controls, "Лиц на одну форму", 1, 6, live_settings.face_updates, 1, func(v):
        live_settings.face_updates = int(v)
        _write_live_settings()
    )
    live_controls.face_updates = controls.get_child(controls.get_child_count()-1)
    for specification in [["Разброс случайных пропорций", "randomness", 0, 1, .05], ["Сила диффузии", "strength", .5, 1, .05], ["Связность шума", "coherence", 0, .95, .05], ["Память предыдущего образа", "feedback", 0, .99, .01], ["Макс. шаг формы, м", "shape_step", 0, .25, .005], ["Обновление текстуры тела", "appearance_step", 0, 1, .01], ["Диффузия текстуры тела", "texture_strength", .3, 1, .01], ["Диффузия лица", "face_strength", .3, 1, .01], ["Обновление лица", "face_amount", 0, 1, .05], ["Стабильность цвета", "color_stability", 0, 1, .05], ["Body horror LoRA", "body_horror", 0, 1.2, .05]]:
        var property: String = specification[1]
        _slider(controls, specification[0], specification[2], specification[3], live_settings[property], specification[4], func(v):
            live_settings[property] = v
            _write_live_settings()
        )
        live_controls[property] = controls.get_child(controls.get_child_count()-1)
    _label(controls, "Размер концепта / поле 3D", 12, Color("a7b9b5"))
    for property in ["size", "resolution", "face_size", "texture_steps"]:
        var select := OptionButton.new()
        var options: Array = {"size": [256,384,512], "resolution": [64,96,128], "face_size": [384,512], "texture_steps": [4,6,8]}[property]
        _label(controls, {"size":"Концепт", "resolution":"Поле 3D", "face_size":"Детализация лица", "texture_steps":"Шаги текстуры"}[property], 12, Color("a7b9b5"))
        for value in options:
            select.add_item(str(value))
        select.select(options.find(LIVE_DEFAULTS[property]))
        select.item_selected.connect(func(index):
            live_settings[property] = options[index]
            _write_live_settings()
        )
        live_controls[property] = select
        controls.add_child(select)
    _label(controls, "Seed следующего запуска потока", 12, Color("a7b9b5"))
    seed_input = SpinBox.new()
    seed_input.min_value = 0
    seed_input.max_value = 2147483646
    seed_input.value = 1928
    controls.add_child(seed_input)
    generation_label = _label(controls, "Новый шум и новый объём каждый раз.
Настройки ИИ действуют со следующего запроса.", 12, Color("a7b9b5"))
    generation_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    generation_label.custom_minimum_size.x = 260
    var hint := _label(root, "WASD · ПКМ осмотр · M форма · G поток ИИ · V испарение · F фонарь · Tab панель · F12 снимок", 13, Color("a5bdb3"))
    hint.position = Vector2(30, get_viewport().get_visible_rect().size.y-35)
    if smoke_scenario:
        for control in root.find_children("*", "Control", true, false):
            control.mouse_filter = Control.MOUSE_FILTER_IGNORE
            control.focus_mode = Control.FOCUS_NONE

func _toggle(parent: Node, title: String, initial: bool, callback: Callable, shortcut: int = 0) -> CheckButton:
    var button := CheckButton.new()
    button.text = title
    button.button_pressed = initial
    button.set_meta("shortcut_key", shortcut)
    button.toggled.connect(callback)
    parent.add_child(button)
    return button

func _setting(parent: Node, title: String, property: String, low: float, high: float, step: float) -> void:
    _slider(parent, title, low, high, actor.get(property), step, func(v): actor.set(property, v))
    settings_controls[property] = parent.get_child(parent.get_child_count()-1)

func _select_form(value: float) -> void:
    actor.select_form(value)
    morph_button.set_pressed_no_signal(true)

func _apply_settings(values: Dictionary) -> void:
    for property in DEFAULTS:
        var value = values.get(property, DEFAULTS[property])
        if value is float or value is int:
            settings_controls[property].value = value
    actor.automatic = false
    actor.mutation = bool(values.get("mutation", true))
    actor.manual_form = clampf(float(values.get("manual_form", 0)), 0, 2)
    morph_button.set_pressed_no_signal(actor.mutation)
    actor.cycle_time = 0
    evaporation_button.button_pressed = bool(values.get("evaporation_enabled", true))
    for property in evaporation_controls:
        evaporation_controls[property].value = values.get("evaporation_"+property, .25 if property == "density" else .35)
    flashlight_button.button_pressed = bool(values.get("flashlight_enabled", true))
    approach_button.button_pressed = bool(values.get("approach_enabled", true))
    actor.debug_view = clampi(int(values.get("debug_view", 0)), 0, 2)
    view_control.select(actor.debug_view)
    seed_input.value = values.get("seed", 1928)
    for property in stage_controls:
        stage_controls[property].value = values.get(property, 1.0 if property == "light_level" else .65)
    var saved = values.get("live_settings", {})
    if saved is Dictionary:
        for property in ["randomness", "strength", "coherence", "feedback", "shape_step", "appearance_step", "body_horror", "texture_strength", "face_strength", "face_amount", "color_stability", "face_updates"]:
            var defaults := LIVE_DEFAULTS
            live_controls[property].value = saved.get(property, defaults[property])
        for property in ["size", "resolution", "face_size", "texture_steps"]:
            var options: Array = {"size": [256,384,512], "resolution": [64,96,128], "face_size": [384,512], "texture_steps": [4,6,8]}[property]
            var index: int = options.find(int(saved.get(property, LIVE_DEFAULTS[property])))
            index = maxi(0, index)
            live_controls[property].select(index)
            live_settings[property] = options[index]
        _write_live_settings()

func _settings_values() -> Dictionary:
    var values := {}
    for property in DEFAULTS:
        values[property] = actor.get(property)
    values["evaporation_enabled"] = evaporation.enabled
    for property in evaporation_controls:
        values["evaporation_"+property] = evaporation.get(property)
    for property in stage_controls:
        values[property] = stage.get(property)
    values["flashlight_enabled"] = stage.flashlight.visible
    values["approach_enabled"] = animate_monster
    values["debug_view"] = actor.debug_view
    values["seed"] = int(seed_input.value)
    values.merge({"mutation": actor.mutation, "manual_form": actor.manual_form, "live_settings": live_settings.duplicate()})
    return values

func _save_settings() -> void:
    FileAccess.open(SETTINGS_FILE, FileAccess.WRITE).store_string(JSON.stringify(_settings_values(), "  "))
    generation_label.text = "Настройки сохранены."

func _load_settings() -> void:
    if FileAccess.file_exists(SETTINGS_FILE):
        var values = JSON.parse_string(FileAccess.get_file_as_string(SETTINGS_FILE))
        if values is Dictionary:
            _apply_settings(values)

func _write_live_settings() -> void:
    if generation_directory.is_empty():
        return
    var temporary := generation_directory.path_join("settings.tmp")
    FileAccess.open(temporary, FileAccess.WRITE).store_string(JSON.stringify(live_settings))
    DirAccess.rename_absolute(temporary, generation_directory.path_join("settings.json"))

func _stop_generation() -> void:
    live_enabled = false
    if not generation_directory.is_empty():
        FileAccess.open(generation_directory.path_join("stop"), FileAccess.WRITE).store_string("stop")
    generation_button.text = "Остановка после текущего запроса…"
    generation_button.disabled = true

func _exit_tree() -> void:
    if generation_pid > 0 and not generation_directory.is_empty():
        FileAccess.open(generation_directory.path_join("stop"), FileAccess.WRITE).store_string("stop")

func _start_generation() -> void:
    if generation_pid > 0:
        _stop_generation()
        return
    var root_path := RuntimePaths.root()
    if not FileAccess.file_exists(RuntimePaths.python()):
        generation_label.text = "Python не установлен. Запустите Start SpookyNeuro.cmd для установки."
        return
    generation_directory = root_path.path_join("artifacts/3d/live/"+str(int(Time.get_unix_time_from_system()))+"_"+str(Time.get_ticks_msec()))
    DirAccess.make_dir_recursive_absolute(generation_directory)
    _write_live_settings()
    # Start from a known endpoint. A restarted stream has a fresh random seed sequence.
    if actor.multiform:
        actor.live = false
        actor.clear_face()
        actor.select_form(0)
    last_sequence = 0
    last_face_sequence = 0
    OS.set_environment("PYTHONUTF8", "1")
    generation_pid = OS.create_process(RuntimePaths.python(), [root_path.path_join("scripts/live_3d.py"), "--output", generation_directory, "--seed", str(int(seed_input.value)), "--parent", str(OS.get_process_id())])
    live_enabled = generation_pid > 0
    generation_button.text = "Остановить поток ИИ [G]" if live_enabled else "Запустить поток ИИ [G]"
    generation_label.text = "Загрузка моделей…" if live_enabled else "Не удалось запустить Python."
    seed_input.value += 1

func _worker_is_running() -> bool:
    if generation_pid == prepared_worker and generation_directory == prepared_session:
        # Godot's Unix PID API only tracks its own children. The Python launcher
        # supervises the adopted worker and publishes its exit instead.
        if FileAccess.file_exists(generation_directory.path_join("worker_exited")):
            return false
        var status_path := generation_directory.path_join("status.json")
        if FileAccess.file_exists(status_path):
            var state = JSON.parse_string(FileAccess.get_file_as_string(status_path))
            if state is Dictionary and state.get("stage", "") in ["Поток остановлен", "Ошибка потока"]:
                return false
        return true
    return OS.is_process_running(generation_pid)

func _poll_generation(delta: float) -> void:
    if generation_pid <= 0:
        return
    generation_poll += delta
    if generation_poll < .15:
        return
    generation_poll = 0
    var status_path := generation_directory.path_join("status.json")
    if FileAccess.file_exists(status_path):
        var state = JSON.parse_string(FileAccess.get_file_as_string(status_path))
        if state is Dictionary:
            generation_label.text = str(state.get("stage", ""))
            if state.get("error") != null:
                generation_label.text += ": "+str(state.error)
            live_status.text = generation_label.text+" · форм %d / лиц %d" % [live_updates, face_updates]
    if not _worker_is_running():
        generation_pid = -1
        live_enabled = false
        generation_button.disabled = false
        generation_button.text = "Запустить поток ИИ [G]"
        return
    if not live_enabled or not actor.mutation:
        return
    _poll_face()
    if not actor.transition_finished() or mutations.busy():
        return
    var latest_path := generation_directory.path_join("latest.json")
    if not FileAccess.file_exists(latest_path):
        return
    var packet = JSON.parse_string(FileAccess.get_file_as_string(latest_path))
    if not packet is Dictionary or int(packet.get("sequence", 0)) <= last_sequence:
        return
    var replacement = Creature.new()
    enemy.add_child(replacement)
    var path: String = packet.directory.path_join("creature.glb")
    var result: Error = replacement.load_model(path)
    if result != OK:
        replacement.queue_free()
        generation_label.text = "Не удалось загрузить новую поверхность: "+str(result)
        _stop_generation()
        return
    for property in DEFAULTS:
        replacement.set(property, actor.get(property))
    replacement.position = actor.position
    replacement.scale = actor.scale
    replacement.debug_view = actor.debug_view
    replacement.time = actor.time
    replacement.flow_clock = actor.flow_clock
    replacement.motion_mix = actor.motion_mix
    replacement.walking = actor.walking
    replacement.inherit_face(actor)
    replacement.animation.seek(actor.animation.current_animation_position, true)
    replacement._pose(0)
    actor.queue_free()
    actor = replacement
    if not actor.mutation_plan.is_empty():
        mutations.submit(actor.mutation_plan,actor)
    mesh_path = path
    last_sequence = int(packet.sequence)
    live_updates += 1
    live_times.append(float(packet.seconds))
    FileAccess.open(generation_directory.path_join("ack.json"), FileAccess.WRITE).store_string(JSON.stringify({"sequence": last_sequence}))
    print("LIVE 3D received #", last_sequence, " seed=", packet.seed, " inference=", packet.seconds, " change_m=", packet.mean_change_m)

func _poll_face() -> void:
    if not actor.live or not actor.face_transition_finished():
        return
    var path := generation_directory.path_join("latest_face.json")
    if not FileAccess.file_exists(path):
        return
    var packet = JSON.parse_string(FileAccess.get_file_as_string(path))
    if not packet is Dictionary or int(packet.get("sequence", 0)) <= last_face_sequence:
        return
    var result: Error = actor.load_face(packet.directory)
    if result != OK:
        generation_label.text = "Не удалось загрузить лицо: "+str(result)
        _stop_generation()
        return
    last_face_sequence = int(packet.sequence)
    face_updates += 1
    if packet.get("extra", false):
        face_times.append(float(packet.seconds))
    if not actor.transition_finished():
        face_during_body += 1
    FileAccess.open(generation_directory.path_join("face_ack.json"), FileAccess.WRITE).store_string(JSON.stringify({"sequence": last_face_sequence}))
    print("LIVE FACE received #", last_face_sequence, " body=", packet.body_sequence, " seconds=", packet.seconds, " body_morph=", not actor.transition_finished())

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_TAB:
        interface.visible = not interface.visible
    if smoke_scenario:
        return
    if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT:
        Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if event.pressed else Input.MOUSE_MODE_VISIBLE
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        yaw -= event.relative.x*.002
        pitch = clampf(pitch-event.relative.y*.002, -1.2, 1.2)
    if event is InputEventKey and event.pressed and not event.echo:
        if event.keycode == KEY_ESCAPE:
            Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
        if event.keycode == KEY_G:
            _start_generation()
        if event.keycode == KEY_N:
            _demo_mutation()
        if event.keycode == KEY_F12:
            _capture_screenshot()
        for button in find_children("*", "CheckButton", true, false):
            if button.get_meta("shortcut_key", 0) == event.keycode:
                button.button_pressed = not button.button_pressed

func _physics_process(delta: float) -> void:
    if player == null or enemy == null:
        return
    super._physics_process(delta)
    if enemy == null or not model_error.is_empty():
        return
    var toward := player.global_position-enemy.global_position
    toward.y = 0
    var direction := toward.normalized() if animate_monster and toward.length() > 1.75 else Vector3.ZERO
    var previous := enemy.position
    enemy.velocity.x = direction.x*.38*actor.walk_speed
    enemy.velocity.z = direction.z*.38*actor.walk_speed
    enemy.velocity.y = 0 if enemy.is_on_floor() else enemy.velocity.y-9.8*delta
    enemy.move_and_slide()
    var moved := Vector2(enemy.position.x-previous.x, enemy.position.z-previous.z).length()
    approach_distance += moved
    is_stepping = moved > .0001
    actor.walking = is_stepping
    if toward.length() > .01:
        enemy.rotation.y = lerp_angle(enemy.rotation.y, atan2(toward.x, toward.z), minf(1, delta*1.8))

func _process(delta: float) -> void:
    if enemy == null or status_label == null:
        return
    elapsed += delta
    stage.advance(delta)
    if smoke_scenario:
        _scenario()
    actor._pose(delta)
    _poll_generation(delta)
    if mutation_demo and actor.mutation:
        mutation_demo_clock += delta
        if mutation_demo_clock >= 6:
            mutation_demo_clock = 0
            _demo_mutation()
    mutations.advance(delta,actor)
    evaporation.advance(delta if actor.mutation else 0.0, actor, mutations.focus, mutations.intensity*actor.effects_amount)
    var collider: CollisionShape3D = enemy.get_child(0)
    collider.shape.height = 3.0*actor.scale.y
    collider.shape.radius = .43*actor.scale.x
    collider.position.y = -1.65+collider.shape.height*.5
    var tick := Time.get_ticks_usec()
    var frame_ms := (tick-last_frame_tick)/1000.0
    last_frame_tick = tick
    frame_times.append(frame_ms)
    measured_frame_sum += frame_ms
    measured_frame_count += 1
    status_label.text = model_error if not model_error.is_empty() else actor.appearance_text()
    if model_error.is_empty() and not actor.live:
        status_label.text = "Подготовка новых случайных 3D-форм…" if live_enabled else "ИИ остановлен · G для запуска"
    metrics_label.text = "%d FPS  ·  %.1f m away  ·  %s" % [Engine.get_frames_per_second(), player.position.distance_to(enemy.position), "approaching" if is_stepping else "idle"]
    if not record_dir.is_empty() and elapsed > 1 and live_updates >= record_after_updates and not record_busy and not record_finished:
        record_timer += delta
        if record_timer >= .1:
            record_timer -= .1
            _record_frame()
    var real_elapsed := (tick-scene_started)/1000000.0
    if smoke_seconds > 0 and real_elapsed > minf(4, smoke_seconds*.5) and (not force_live or live_updates >= 3) and not screenshot_done:
        screenshot_done = true
        _capture_screenshot()
    if smoke_seconds > 0 and real_elapsed >= smoke_seconds:
        _save_smoke()
        get_tree().quit(0 if model_error.is_empty() else 1)

func _scenario() -> void:
    # Walk around the creature while it tracks the player's real world position.
    player.position.x = sin(elapsed*.25)*(1.3 if demo else 2.8)
    var toward := enemy.global_position-player.global_position
    yaw = atan2(-toward.x, -toward.z)

func _demo_mutation() -> void:
    if mutations.busy():
        return
    mutations.submit(mutations.demo_plan(mutation_demo_sequence),actor)
    mutation_demo_sequence += 1

func _capture_screenshot() -> void:
    await RenderingServer.frame_post_draw
    var path := smoke_output+".png" if not smoke_output.is_empty() else "user://creature_room_3d.png"
    get_viewport().get_texture().get_image().save_png(path)
    print("Saved 3D room: ", path)

func _save_smoke() -> void:
    if smoke_output.is_empty():
        return
    var sorted_times := frame_times.duplicate()
    sorted_times.sort()
    var mean := measured_frame_sum/maxi(1, measured_frame_count)
    var report := {"mode": "3d_room", "frames": measured_frame_count,
        "mean_frame_ms": mean, "fps": 1000/maxf(.001, mean),
        "p95_frame_ms": sorted_times[int(sorted_times.size()*.95)], "error": model_error,
        "travelled_m": approach_distance, "model": mesh_path, "skinned": actor.surface != null,
        "forms": [actor.form_weights.x, actor.form_weights.y, actor.form_weights.z],
        "evaporation_enabled": evaporation.enabled, "live_updates": live_updates, "live_generation_seconds": live_times, "worker_directory": generation_directory,
        "face_updates": face_updates, "face_during_body": face_during_body, "face_seconds": face_times,
        "mutation_family": mutations.family, "mutation_events": mutations.completed, "anatomy_modules": mutations.modules.size(),
        "multiform": actor.multiform, "client_connected": client.connected, "end_position": [enemy.position.x, enemy.position.y, enemy.position.z]}
    FileAccess.open(smoke_output+".json", FileAccess.WRITE).store_string(JSON.stringify(report, "  "))
