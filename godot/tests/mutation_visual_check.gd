extends SceneTree
var scene
var output := "res://../artifacts/mutations"

func _initialize() -> void:
    call_deferred("_run")

func _advance(seconds: float) -> void:
    for i in range(int(seconds*60)):
        scene.actor._pose(1.0/60)
        scene.mutations.advance(1.0/60,scene.actor)
        scene.evaporation.advance(1.0/60,scene.actor,scene.mutations.focus,scene.mutations.intensity*.75)
        await process_frame

func _capture(name_: String) -> void:
    await RenderingServer.frame_post_draw
    root.get_texture().get_image().save_png(output.path_join(name_+".png"))

func _run() -> void:
    output = ProjectSettings.globalize_path(output)
    DirAccess.make_dir_recursive_absolute(output)
    scene = load("res://room_3d.tscn").instantiate()
    scene.smoke_scenario = true
    root.add_child(scene)
    scene.set_process(false)
    scene.set_physics_process(false)
    scene.interface.visible = false
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--face="):
            assert(scene.actor.load_face(arg.trim_prefix("--face=")) == OK)
    scene.player.position = Vector3(0,.95,1.5)
    scene.enemy.position = Vector3(0,1.66,-2.2)
    scene.enemy.rotation = Vector3.ZERO
    scene.camera.look_at(Vector3(0,1.45,-2.2))
    await _advance(.5)
    await _capture("00-human")
    for family in [1,2,3,0]:
        assert(scene.mutations.submit(scene.mutations.demo_plan(family),scene.actor))
        await _advance(.55)
        await _capture(str(family)+"-transition")
        await _advance(1.4)
        await _capture(str(family)+"-grown")
    scene.player.position = Vector3(3,.95,-1)
    scene.camera.look_at(Vector3(0,1.5,-2.2))
    scene.mutations.submit(scene.mutations.demo_plan(3),scene.actor)
    await _advance(2)
    await _capture("choir-side")
    scene.player.position = Vector3(0,2.0,-.9)
    scene.camera.look_at(Vector3(0,2.75,-2.2))
    scene.actor.face_geometry = 0
    scene.actor._pose(0)
    await _capture("face-geometry-off")
    scene.actor.face_geometry = 1
    scene.actor._pose(0)
    await _capture("face-geometry-on")
    # Keep all scene state and lighting fixed; only the lens toggles.
    scene.player.position = Vector3(0,.95,1.5)
    scene.camera.look_at(Vector3(0,1.45,-2.2))
    scene.stage.lens.set_shader_parameter("strength",0.0)
    scene.evaporation.visible = false
    scene.mutations.light.light_energy = 0
    var occluder := MeshInstance3D.new()
    var box := BoxMesh.new()
    box.size = Vector3(.4,2.8,.2)
    occluder.mesh = box
    var mat := StandardMaterial3D.new()
    mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
    mat.albedo_color = Color(.1,.5,.2)
    occluder.material_override = mat
    scene.add_child(occluder)
    occluder.position = Vector3(-.2,1.4,-.7)
    scene.mutations.lens.set_shader_parameter("center_world",Vector3(0,1.7,-2.2))
    scene.mutations.lens.set_shader_parameter("intensity",1.0)
    scene.mutations.distortion.visible = false
    await _capture("occlusion-off")
    scene.mutations.distortion.visible = true
    await _capture("occlusion-on")
    print("MUTATION VISUAL CHECK SAVED: ",ProjectSettings.globalize_path(output))
    scene.queue_free()
    await process_frame
    quit()
