extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var folder := ""
    var face_folder := ""
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--packet="):
            folder = arg.trim_prefix("--packet=")
        if arg.begins_with("--face="):
            face_folder = arg.trim_prefix("--face=")
    assert(not folder.is_empty())
    var actor = load("res://skinned_creature.gd").new()
    root.add_child(actor)
    assert(actor.load_model(folder.path_join("creature.glb")) == OK)
    assert(actor.live and actor.live_sequence > 0)
    assert(actor.form_weights.is_equal_approx(Vector3(0, 1, 0)))
    if not face_folder.is_empty():
        actor.transition_seconds = 6
        actor.face_transition_seconds = 1
        assert(actor.load_face(face_folder) == OK)
        actor._pose(.5)
        assert(is_equal_approx(actor.material.get_shader_parameter("face_mix"), .5))
        assert(actor.form_weights.z < .03, "Face must advance faster than the body")
        actor.mutation = false
        actor._pose(4)
        assert(is_equal_approx(actor.face_progress, .5), "Freeze must hold the face as well")
        actor.mutation = true
        var replacement = load("res://skinned_creature.gd").new()
        root.add_child(replacement)
        assert(replacement.load_model(folder.path_join("creature.glb")) == OK)
        replacement.face_transition_seconds = actor.face_transition_seconds
        replacement.inherit_face(actor)
        assert(is_equal_approx(replacement.face_progress, .5))
        assert(replacement.face_maps.albedo_next == actor.face_maps.albedo_next)
        assert(is_equal_approx(replacement.material.get_shader_parameter("face_mix"), .5))
        actor._pose(.5)
        assert(actor.face_transition_finished() and not actor.transition_finished())
        var last_texture = actor.face_maps.albedo_next
        assert(actor.load_face(face_folder) == OK)
        assert(actor.face_maps.albedo_previous == last_texture, "Face endpoints must join exactly")
        assert(is_zero_approx(actor.material.get_shader_parameter("face_mix")))
        actor.clear_face()
        assert(not actor.material.get_shader_parameter("face_enabled"))
        replacement.queue_free()
        actor.live_progress = 0
        actor._pose(0)
        print("INDEPENDENT FACE CHECK PASSED: separate clock, freeze, texture endpoints, state survives body replacement")
    actor.transition_seconds = 2
    actor.hold_seconds = 0
    actor._pose(1)
    assert(actor.form_weights.is_equal_approx(Vector3(0, .5, .5)))
    assert(not actor.transition_finished())
    actor.mutation = false
    var frozen_clock: float = actor.flow_clock
    actor._pose(6)
    assert(is_equal_approx(actor.flow_clock, frozen_clock))
    assert(actor.form_weights.is_equal_approx(Vector3(0, .5, .5)))
    actor.mutation = true
    actor._pose(1)
    assert(actor.transition_finished())
    assert(actor.form_weights.is_equal_approx(Vector3(0, 0, 1)))
    actor._pose(20)
    assert(actor.form_weights.is_equal_approx(Vector3(0, 0, 1)), "Live state must never wrap to a preset")
    actor.walking = true
    actor._pose(.3)
    for i in range(actor.skeleton.get_bone_count()):
        assert(actor.skeleton.get_bone_global_pose(i).is_finite())
    print("LIVE CHECK PASSED: neural packet, continuous A to B, pause, endpoint hold, no cycling, animated skeleton")
    actor.queue_free()
    await process_frame
    quit()
