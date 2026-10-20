extends SceneTree

func _initialize() -> void:
    var room_script = load("res://room_3d.gd")
    var settings: Dictionary = room_script.LIVE_DEFAULTS.duplicate()
    settings["seed"] = 1928
    var output := ""
    var defaults := false
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--output="):
            output = arg.trim_prefix("--output=")
        if arg == "--defaults":
            defaults = true
    if not defaults and FileAccess.file_exists(room_script.SETTINGS_FILE):
        var saved = JSON.parse_string(FileAccess.get_file_as_string(room_script.SETTINGS_FILE))
        if saved is Dictionary and saved.get("live_settings") is Dictionary:
            for key in settings:
                settings[key] = saved.live_settings.get(key, settings[key])
            settings.seed = clampi(int(saved.get("seed", 1928)), 0, 2147483646)
    if output.is_empty():
        quit(1)
        return
    var file := FileAccess.open(output, FileAccess.WRITE)
    if file == null:
        quit(1)
        return
    file.store_string(JSON.stringify(settings))
    file.close()
    quit()
