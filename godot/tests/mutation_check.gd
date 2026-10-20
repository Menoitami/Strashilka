extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var scene = load("res://room_3d.tscn").instantiate()
    root.add_child(scene)
    await process_frame
    scene.set_process(false)
    scene.set_physics_process(false)
    assert(scene.model_error.is_empty())
    var actor = scene.actor
    var director = scene.mutations
    for family in [1,2,3,0]:
        var plan: Dictionary = director.demo_plan(family)
        assert(director.submit(plan,actor))
        for i in range(24):
            actor._pose(.1)
            director.advance(.1,actor)
        assert(director.modules.size() == plan.modules.size())
        for module in director.modules:
            assert(module.rig.get_bone_count() == 3)
            assert(module.surface.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX].size() > 20)
            assert(module.growth > .99 and module.global_transform.is_finite())
        var frozen: Vector4 = actor.face_shape
        var frozen_clock: float = director.clock
        actor.mutation = false
        actor._pose(2)
        director.advance(2,actor)
        assert(actor.face_shape.is_equal_approx(frozen))
        assert(is_equal_approx(director.clock,frozen_clock))
        actor.mutation = true
        assert(not director.submit({"schema":1,"family":"broken","modules":[]},actor))
        assert(director.family == plan.family)
        await process_frame
    assert(director.completed == 4)
    assert(director.modules.is_empty())
    assert(actor.scale.is_equal_approx(Vector3.ONE))
    assert(director.echoes.is_empty())
    var invalid: Dictionary = director.demo_plan(1)
    invalid.modules[0].scale = "broken"
    assert(not director.submit(invalid,actor))
    assert(director.modules.is_empty())
    # Complete face packets transfer across GLB swaps; partial packets do not replace them.
    var directory := ProjectSettings.globalize_path("user://mutation-check-"+str(Time.get_ticks_usec()))
    DirAccess.make_dir_recursive_absolute(directory)
    var files := ["albedo","normal","mask","portrait_previous","portrait_next","flow_forward","flow_backward"]
    for name_ in files:
        var image := Image.create(32,32,false,Image.FORMAT_RGBA8)
        image.fill(Color(.5,.5,1,1))
        image.save_png(directory.path_join(name_+".png"))
    FileAccess.open(directory.path_join("face.json"),FileAccess.WRITE).store_string(JSON.stringify({
        "portrait_view":[0,2.75,.55],"face_traits":[.2,-.2,.1,.3]}))
    assert(actor.load_face(directory) == OK)
    actor._pose(.3)
    var replacement = scene.Creature.new()
    scene.enemy.add_child(replacement)
    assert(replacement.load_model(scene.mesh_path) == OK)
    replacement.inherit_face(actor)
    assert(replacement.face_maps == actor.face_maps)
    assert(is_equal_approx(replacement.face_progress,actor.face_progress))
    assert(replacement.material.get_shader_parameter("face_flow_enabled"))
    replacement.queue_free()
    actor._pose(2)
    var saved: Dictionary = actor.face_maps.duplicate()
    DirAccess.remove_absolute(directory.path_join("flow_backward.png"))
    assert(actor.load_face(directory) == ERR_FILE_NOT_FOUND)
    assert(actor.face_maps == saved)
    for name_ in files:
        DirAccess.remove_absolute(directory.path_join(name_+".png"))
    DirAccess.remove_absolute(directory.path_join("face.json"))
    DirAccess.remove_absolute(directory)
    print("MUTATION CHECK PASSED: four families, rigged modules, retirement, freeze, invalid packet rejection")
    scene.queue_free()
    await process_frame
    quit()
