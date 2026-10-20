extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var scene = load("res://main.tscn").instantiate()
    root.add_child(scene)
    await process_frame
    scene.set_process(false)
    scene.set_physics_process(false)
    assert(scene.rig.size() == 14, "All articulated joints must exist")
    scene.is_stepping = true
    var min_left := 100.0
    var max_left := -100.0
    for i in range(240):
        scene.elapsed += 1.0 / 60
        scene._animate_rig(1.0 / 60)
        var angle: float = scene.rig["HipL"].rotation.x
        min_left = minf(min_left, angle)
        max_left = maxf(max_left, angle)
        for joint in scene.rig.values():
            assert(joint.global_transform.is_finite())
    assert(max_left - min_left > .5, "Walking must articulate the leg")
    assert(scene.rig["Head"].get_parent() == scene.rig["Chest"])
    assert(scene.rig["AnkleL"].get_parent() == scene.rig["KneeL"])
    # Returning after a long offscreen pause must replace the incompatible image,
    # rather than starting a five-second crossfade from the old camera view.
    scene.awaiting_fresh_frame = false
    scene.current_id = 41
    scene._invalidate()
    scene.last_result_at = -100
    var image := Image.create(8, 8, false, Image.FORMAT_RGBA8)
    image.fill(Color.WHITE)
    scene._on_result({"id": 42, "epoch": scene.epoch, "captured_ms": Time.get_ticks_msec()},
        {"image": image.save_png_to_buffer()})
    assert(scene.current_id == 42)
    assert(not scene.awaiting_fresh_frame)
    assert(scene.queued.is_empty())
    assert(scene.transition_elapsed >= scene.transition_duration)
    assert(scene.last_result_at == scene.elapsed)
    print("SEQUENCE RESET CHECK PASSED: fresh frame replaces stale view immediately")
    print("RIG CHECK PASSED: 14 joints, connected hierarchy, animated gait")
    scene.queue_free()
    await process_frame
    quit()
