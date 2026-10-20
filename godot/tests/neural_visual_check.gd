extends SceneTree
var output := ""
var source := ""

func _initialize() -> void:
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--field-preview="): source=arg.trim_prefix("--field-preview=")
        if arg.begins_with("--output="): output=arg.trim_prefix("--output=")
    call_deferred("check")

func capture(name_: String) -> void:
    await process_frame
    await RenderingServer.frame_post_draw
    root.get_texture().get_image().save_png(output.path_join(name_+".png"))

func check() -> void:
    DirAccess.make_dir_recursive_absolute(output)
    var room = load("res://neural_room.tscn").instantiate()
    root.add_child(room)
    await process_frame
    room.set_process(false)
    room.set_physics_process(false)
    room.interface.hide()
    room.entity.frozen = true
    room.player.rotation = Vector3.ZERO
    room.camera.rotation = Vector3.ZERO
    var files: Array[String] = []
    for folder in DirAccess.get_directories_at(source):
        if FileAccess.file_exists(source.path_join(folder).path_join("field.json")):
            files.append(source.path_join(folder))
    files.sort()
    assert(files.size()>=2)
    assert(room.entity.load_field(files[0]))
    assert(room.entity.load_field(files[mini(5,files.size()-1)]))
    room.entity.effects = 0
    room.entity.progress = .5
    room.entity.advance(0)
    for i in range(9):
        var angle := i*TAU/8
        room.camera.global_position = Vector3(sin(angle)*4.7,1.65,cos(angle)*4.7)
        room.camera.look_at(Vector3(0,1.5,0))
        await capture("orbit_%02d"%i)
    room.camera.global_position = Vector3(0,1.65,4.7)
    room.camera.look_at(Vector3(0,1.5,0))
    for i in range(5):
        room.entity.progress = i/4.0
        room.entity.advance(0)
        await capture("transition_%02d"%i)
    var box := MeshInstance3D.new()
    var mesh := BoxMesh.new()
    mesh.size = Vector3(.6,1.8,.3)
    box.mesh = mesh
    var mat := StandardMaterial3D.new()
    mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
    mat.albedo_color = Color(0,1,0)
    box.material_override = mat
    box.position = Vector3(.25,1.5,2.0)
    room.add_child(box)
    room.entity.progress = .5
    room.entity.effects = 0
    room.entity.advance(0)
    await capture("occlusion_off")
    room.entity.effects = 1
    room.entity.advance(0)
    await capture("occlusion_on")
    room.free()
    print("Neural volume multiview, transition and occlusion captures: DONE")
    quit()
