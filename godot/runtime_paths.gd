extends RefCounted
## Disk assets and the neural worker live next to the exported executable.

static func root() -> String:
    if OS.has_environment("SPOOKY_ROOT"):
        return OS.get_environment("SPOOKY_ROOT").simplify_path()
    if OS.has_feature("editor"):
        return ProjectSettings.globalize_path("res://..").simplify_path()
    return OS.get_executable_path().get_base_dir()

static func resolve(path: String) -> String:
    if path.begins_with("res://../"):
        return root().path_join(path.trim_prefix("res://../"))
    return ProjectSettings.globalize_path(path)

static func python() -> String:
    return root().path_join(".venv/Scripts/python.exe" if OS.get_name() == "Windows" else ".venv/bin/python")
