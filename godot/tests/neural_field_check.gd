extends SceneTree

func _initialize() -> void:
    call_deferred("check")

func check() -> void:
    var entity = load("res://neural_entity.gd").new()
    var camera := Camera3D.new()
    root.add_child(camera)
    root.add_child(entity)
    entity.build(camera)
    var source := "res://../assets/neural_entity/field_000001"
    source = load("res://runtime_paths.gd").resolve(source)
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--field="): source=arg.trim_prefix("--field=")
    assert(entity.load_field(source),entity.error)
    var old = entity.next_texture
    assert(not entity.load_field("user://not-a-field"))
    assert(entity.next_texture == old,"Invalid packet replaced the current volume")
    var corrupt := "user://neural-field-check-"+str(Time.get_ticks_usec())
    DirAccess.make_dir_recursive_absolute(corrupt)
    var manifest := FileAccess.open(corrupt.path_join("field.json"),FileAccess.WRITE)
    manifest.store_string(FileAccess.get_file_as_string(source.path_join("field.json")))
    manifest.close()
    var truncated := FileAccess.open(corrupt.path_join("field.rgba"),FileAccess.WRITE)
    truncated.store_buffer(PackedByteArray([0,0,0,0]))
    truncated.close()
    assert(not entity.load_field(corrupt),"Accepted a truncated field")
    assert(entity.next_texture == old,"Truncated field replaced the current volume")
    DirAccess.remove_absolute(corrupt.path_join("field.json"))
    DirAccess.remove_absolute(corrupt.path_join("field.rgba"))
    DirAccess.remove_absolute(corrupt)
    assert(entity.load_field(source))
    entity.progress = .25
    entity.frozen = true
    var before: float = entity.clock
    entity.advance(1.0)
    assert(entity.progress==.25 and entity.clock==before,"Pause changed the neural volume")
    entity.frozen = false
    entity.advance(1.0)
    assert(entity.progress>.25)
    entity.duration = 2.0
    entity.progress = .98
    var previous_updates: int = entity.updates
    assert(entity.queue_field(source))
    var displayed = entity.next_texture
    entity.frozen = true
    entity.advance(.1)
    assert(entity.next_texture==displayed and entity.updates==previous_updates)
    entity.frozen = false
    entity.advance(.1)
    assert(entity.updates==previous_updates+1,"Queued field did not start at the boundary")
    assert(is_equal_approx(entity.progress,.03),"Transition discarded frame time or inserted a hold")
    entity.free()
    camera.free()
    print("Neural field load, atomic rejection, freeze and continuation: PASS")
    quit()
