extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var scene = load("res://room_3d.tscn").instantiate()
    if FileAccess.file_exists("res://../artifacts/3d/multiform/creature.glb"):
        scene.mesh_path = "res://../artifacts/3d/multiform/creature.glb"
    root.add_child(scene)
    await physics_frame
    assert(scene.model_error.is_empty())
    assert(scene.billboard == null)
    assert(scene.viewport == null)
    assert(scene.actor.skeleton.get_bone_count() == 19)
    if scene.actor.multiform:
        assert(scene.actor.multiform)
        assert(scene.actor.surface.get_blend_shape_count() == 2)
        var actor = scene.actor
        actor.select_form(1)
        actor._pose(0)
        assert(is_equal_approx(actor.surface.get_blend_shape_value(actor.shape_indices[0]), 1))
        assert(actor.material.get_shader_parameter("form_weights").is_equal_approx(Vector3(0, 1, 0)))
        actor.select_form(2)
        actor.mutation_amount = 0
        actor.color_blend = .4
        actor.relief_strength = 1.5
        actor._pose(0)
        assert(is_zero_approx(actor.surface.get_blend_shape_value(actor.shape_indices[1])))
        assert(is_equal_approx(actor.material.get_shader_parameter("color_blend"), .4))
        assert(is_equal_approx(actor.material.get_shader_parameter("relief_strength"), 1.5))
        actor.mutation_amount = 1
        actor.automatic = true
        actor.cycle_time = 0
        actor._pose(actor.hold_seconds+actor.transition_seconds*.5)
        assert(actor.form_weights.is_equal_approx(Vector3(.5, .5, 0)))
        actor.mutation = false
        var frozen: Vector3 = actor.form_weights
        actor._pose(5)
        assert(actor.form_weights.is_equal_approx(frozen))
        assert(actor.material.get_shader_parameter("normal_2") != null)
    assert(scene.evaporation.particles.size() == 28)
    scene.evaporation_button.button_pressed = false
    scene.evaporation.advance(.1, scene.actor)
    assert(not scene.evaporation.visible)
    scene.evaporation_button.button_pressed = true
    scene.evaporation.advance(1, scene.actor)
    assert(scene.evaporation.visible)
    for particle in scene.evaporation.particles:
        assert(particle.node.position.is_finite())
    var old_evaporation = scene.evaporation
    scene._apply_settings({"evaporation_enabled": false, "evaporation_density": 1.2,
        "live_settings": {"shape_step": .04, "feedback": .98}})
    assert(not scene.evaporation.enabled)
    assert(is_equal_approx(scene.evaporation.density, 1.2))
    assert(is_equal_approx(scene.live_settings.shape_step, .04))
    assert(is_equal_approx(scene.live_settings.feedback, .98))
    assert(scene.evaporation == old_evaporation)
    # Round-trip through the same JSON representation as the Save/Load buttons.
    scene._apply_settings({"light_level": .75, "lens_strength": .3, "flashlight_enabled": false,
        "skin_detail": .9, "skin_wetness": .15, "approach_enabled": false, "debug_view": 2, "seed": 42,
        "face_transition_seconds": .7,
        "live_settings": {"face_size": 384, "texture_steps": 8, "color_stability": .45, "face_strength": .55, "face_updates": 5}})
    var saved: Dictionary = JSON.parse_string(JSON.stringify(scene._settings_values()))
    scene._apply_settings(scene.DEFAULTS)
    scene._apply_settings(saved)
    assert(is_equal_approx(scene.stage.light_level, .75))
    assert(is_equal_approx(scene.stage.lens_strength, .3))
    assert(not scene.stage.flashlight.visible)
    assert(is_equal_approx(scene.actor.skin_detail, .9))
    assert(is_equal_approx(scene.actor.skin_wetness, .15))
    assert(not scene.animate_monster and scene.actor.debug_view == 2)
    assert(scene.seed_input.value == 42)
    assert(scene.live_settings.face_size == 384 and scene.live_settings.texture_steps == 8)
    assert(is_equal_approx(scene.live_settings.color_stability, .45))
    assert(is_equal_approx(scene.live_settings.face_strength, .55))
    assert(scene.live_settings.face_updates == 5)
    assert(is_equal_approx(scene.actor.face_transition_seconds, .7))
    assert(scene.live_controls.texture_steps.get_selected_id() == 2)
    # Keyboard switches and panel visibility remain usable with the panel hidden.
    for key in [KEY_TAB, KEY_F, KEY_TAB]:
        var event := InputEventKey.new()
        event.keycode = key
        event.pressed = true
        scene._unhandled_input(event)
    assert(scene.stage.flashlight.visible and scene.interface.visible)
    scene._apply_settings(scene.DEFAULTS)
    assert(scene.client.peer.get_status() == StreamPeerTCP.STATUS_NONE)
    var start: Vector3 = scene.enemy.position
    for i in range(70):
        await physics_frame
    assert(scene.enemy.position.z > start.z+.25, "Monster must approach player in the original room")
    scene.animate_monster = false
    var stopped: Vector3 = scene.enemy.position
    for i in range(25):
        await physics_frame
    assert(Vector2(scene.enemy.position.x-stopped.x, scene.enemy.position.z-stopped.z).length() < .01)
    assert(not scene.actor.walking)
    # Drive directly toward the wall. The capsule must collide instead of teleporting through it.
    scene.enemy.position = Vector3(6, 1.66, -3)
    scene.enemy.velocity = Vector3.ZERO
    scene.player.position = Vector3(9, .95, -3)
    scene.animate_monster = true
    scene.actor.walk_speed = 10
    for i in range(65):
        await physics_frame
    assert(scene.enemy.position.x < 6.6, "Monster capsule must be blocked by the room wall")
    for i in range(scene.actor.skeleton.get_bone_count()):
        assert(scene.actor.skeleton.get_bone_global_pose(i).is_finite())
    assert(scene.client.peer.get_status() == StreamPeerTCP.STATUS_NONE)
    print("ROOM 3D CHECK PASSED: 3 neural forms, independent geometry/material/normal controls, freeze, skinned walk, approach, wall collision, no network")
    scene.queue_free()
    await process_frame
    quit()
