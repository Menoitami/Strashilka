extends SceneTree

func _initialize() -> void:
    call_deferred("build")

func build() -> void:
    var variant := "base"
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--variant="):
            variant = arg.trim_prefix("--variant=")
    var viewport := SubViewport.new()
    viewport.size = Vector2i(512, 512)
    viewport.transparent_bg = true
    viewport.own_world_3d = true
    viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
    root.add_child(viewport)
    var world := Node3D.new()
    viewport.add_child(world)
    var environment := WorldEnvironment.new()
    environment.environment = Environment.new()
    environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.environment.ambient_light_color = Color.WHITE
    environment.environment.ambient_light_energy = .7
    world.add_child(environment)
    var anatomy := Node3D.new()
    world.add_child(anatomy)
    var lab = load("res://main.gd").new()
    lab._build_anatomy(anatomy)
    for part in anatomy.find_children("*", "MeshInstance3D", true, false):
        var p: Vector3 = anatomy.to_local(part.global_position)
        if variant == "swollen":
            if absf(p.x) < .4 and p.y > 1.05 and p.y < 2.2:
                part.scale *= Vector3(1.8, 1.04, 1.7)
            elif p.y > 2.35:
                part.scale *= Vector3(1.45, 1., 1.35)
            elif absf(p.x) > .4:
                part.scale *= Vector3(1.4, 1.1, 1.4)
        elif variant == "chitin":
            var carapace := StandardMaterial3D.new()
            carapace.albedo_color = Color(.055, .23, .21) if p.y < 2.35 else Color(.1, .38, .32)
            carapace.roughness = .35
            part.material_override = carapace
            if absf(p.x) < .4 and p.y > 1.1 and p.y < 2.1:
                part.scale *= Vector3(.65, 1., .78)
            elif p.y > 2.35:
                part.scale *= Vector3(.7, 1., 1.3)
            elif absf(p.x) > .4:
                part.scale *= Vector3(.72, 1., .8)
    for side in [-1, 1]:
        lab.rig["Shoulder" + ("L" if side < 0 else "R")].rotation.z = side * .48
    var lamp := DirectionalLight3D.new()
    lamp.rotation_degrees = Vector3(-20, -30, 0)
    world.add_child(lamp)
    var camera := Camera3D.new()
    camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    camera.size = 3.65
    camera.position = Vector3(0, 1.5, 6)
    world.add_child(camera)
    camera.look_at(Vector3(0, 1.5, 0))
    camera.current = true
    await process_frame
    await RenderingServer.frame_post_draw
    var output := ProjectSettings.globalize_path("res://../artifacts/3d")
    DirAccess.make_dir_recursive_absolute(output)
    viewport.get_texture().get_image().save_png(output.path_join("guide.png" if variant == "base" else "guide_"+variant+".png"))
    lab.free()
    print("3D A-pose guide saved")
    quit()
