extends SceneTree

func _initialize() -> void:
    var path := "res://../artifacts/3d/generated/creature.glb"
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--model="):
            path = arg.trim_prefix("--model=")
    var state := GLTFState.new()
    var document := GLTFDocument.new()
    assert(document.append_from_file(ProjectSettings.globalize_path(path), state) == OK)
    var scene := document.generate_scene(state)
    root.add_child(scene)
    var skeleton: Skeleton3D = scene.find_children("*", "Skeleton3D", true, false)[0]
    var surface: MeshInstance3D = scene.find_children("*", "MeshInstance3D", true, false)[0]
    var player: AnimationPlayer = scene.find_children("*", "AnimationPlayer", true, false)[0]
    assert(skeleton.get_bone_count() == 19)
    assert(surface.skin.get_bind_count() == 19)
    assert(surface.get_blend_shape_count() == 1)
    var arrays := surface.mesh.surface_get_arrays(0)
    assert(arrays[Mesh.ARRAY_VERTEX].size() > 1000)
    assert(arrays[Mesh.ARRAY_BONES].size() == arrays[Mesh.ARRAY_VERTEX].size()*4)
    var mat := surface.get_active_material(0) as StandardMaterial3D
    print("COLOR MATERIAL: vertex_albedo=", mat.vertex_color_use_as_albedo, " albedo=", mat.albedo_color)
    var walk: String = ""
    for animation in player.get_animation_list():
        if str(animation).contains("CreepWalk"):
            walk = animation
    assert(not walk.is_empty())
    player.play(walk)
    player.advance(.2)
    var first := skeleton.get_bone_pose_rotation(skeleton.find_bone("HipL"))
    player.advance(.5)
    var second := skeleton.get_bone_pose_rotation(skeleton.find_bone("HipL"))
    assert(first.angle_to(second) > .01)
    surface.set_blend_shape_value(0, 1)
    assert(surface.get_blend_shape_value(0) == 1)
    print("VOLUME CHECK PASSED: skinned surface, 19 bones, changing walk pose, morph target")
    scene.queue_free()
    quit()
