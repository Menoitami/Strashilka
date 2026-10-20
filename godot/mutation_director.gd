extends Node3D
## One event clock coordinates anatomy, refraction, echoes, smoke, light and sound.
const Module = preload("res://anatomy_module.gd")
const FAMILIES = ["human","many_arms","crawler","choir"]
var modules: Array[Node3D] = []
var family := "human"
var event_time := 10.0
var intensity := 0.0
var clock := 0.0
var focus_bone := "Head"
var focus := Vector3.ZERO
var family_from := Vector3.ONE
var family_target := Vector3.ONE
var completed := 0
var face_history: Array[Dictionary] = []
var face_revision := -1
var distortion: MeshInstance3D
var lens: ShaderMaterial
var light := OmniLight3D.new()
var sound := AudioStreamPlayer3D.new()
var echoes: Array[Dictionary] = []
var debris: Array[MeshInstance3D] = []
var ring := MeshInstance3D.new()
var echo_taken := false
var enabled := true

func build(camera: Camera3D) -> void:
    distortion = MeshInstance3D.new()
    var quad := QuadMesh.new()
    quad.size = Vector2(2,2)
    distortion.mesh = quad
    distortion.extra_cull_margin = 1000
    distortion.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
    lens = ShaderMaterial.new()
    lens.shader = preload("res://shaders/mutation_lens.gdshader")
    lens.render_priority = 90
    distortion.material_override = lens
    camera.add_child(distortion)
    distortion.position.z = -1
    add_child(light)
    light.light_color = Color(.68,.13,.075)
    light.omni_range = 3.2
    light.light_energy = 0
    light.shadow_enabled = false
    add_child(sound)
    sound.stream = _sound()
    sound.max_distance = 14
    sound.unit_size = 3
    var stone := StandardMaterial3D.new()
    stone.albedo_color = Color(.19,.18,.17)
    stone.roughness = .92
    for i in range(12):
        var piece := MeshInstance3D.new()
        var mesh := BoxMesh.new()
        mesh.size = Vector3(.025+.007*(i%3),.025,.06)
        piece.mesh = mesh
        piece.material_override = stone
        piece.visible = false
        add_child(piece)
        debris.append(piece)
    var torus := TorusMesh.new()
    torus.inner_radius = .96
    torus.outer_radius = 1.0
    torus.rings = 48
    torus.ring_segments = 8
    ring.mesh = torus
    var ring_mat := StandardMaterial3D.new()
    ring_mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
    ring_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
    ring_mat.albedo_color = Color(.3,.12,.08,0)
    ring.material_override = ring_mat
    ring.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
    add_child(ring)

static func demo_plan(sequence: int) -> Dictionary:
    var family_ : String = FAMILIES[sequence%4]
    var specs := []
    if family_ in ["many_arms","crawler","choir"]:
        for side in [-1,1]:
            var kind := "head" if family_ == "choir" else "arm"
            var rotation_ := [0,0,-side*60]
            if family_ == "crawler":
                rotation_ = [162,0,-side*16]
            if kind == "head":
                rotation_ = [0,0,-side*30]
            specs.append({"slot":"left" if side == -1 else "right", "kind":kind,
                "bone":"ShoulderL" if side == -1 else "ShoulderR", "rotation":rotation_,
                "scale":1.9 if family_ == "crawler" else 1.0,"phase":sequence+side*.6})
        if family_ != "crawler":
            specs.append({"slot":"spine","kind":"tendril","bone":"Chest","rotation":[-80,0,0],"scale":1.0,"phase":1.7})
    return {"schema":1,"family":family_,"modules":specs,"focus_bone":"ShoulderL",
        "face":[sin(sequence*1.7),cos(sequence*.8),sin(sequence*2.3),cos(sequence*1.4)]}

func submit(plan: Dictionary, actor: Node3D) -> bool:
    if plan.get("schema",0) != 1 or not plan.get("family","") in FAMILIES or not plan.get("modules") is Array:
        return false
    if plan.modules.size() > 5:
        return false
    var face = plan.get("face",[])
    if not face is Array or face.size() != 4:
        return false
    for value in face:
        if not (value is float or value is int) or not is_finite(float(value)):
            return false
    var slots := {}
    for spec in plan.modules:
        if not spec is Dictionary or spec.get("kind","") not in ["arm","head","tendril"]:
            return false
        if actor.skeleton.find_bone(spec.get("bone","")) < 0 or not spec.get("rotation") is Array or spec.rotation.size() != 3:
            return false
        if not spec.has("slot") or slots.has(spec.slot) or not spec.has("phase") or not spec.has("scale"):
            return false
        slots[spec.slot] = true
        for value in spec.rotation+[spec.phase,spec.scale]:
            if not (value is float or value is int) or not is_finite(float(value)):
                return false
        if float(spec.scale) <= 0 or float(spec.scale) > 2:
            return false
    # Build the new set before retiring the visible set.
    var next: Array[Node3D] = []
    for spec in plan.modules:
        var module = Module.new()
        add_child(module)
        module.build(actor,spec)
        module.visible = false
        module.birth_delay = .22
        next.append(module)
    for module in modules:
        module.target = 0
        module.birth_delay = .22
    modules.append_array(next)
    family = plan.family
    family_from = actor.scale
    family_target = Vector3(1.18,.76,1.12) if family == "crawler" else Vector3.ONE
    focus_bone = plan.get("focus_bone","Head")
    actor.set_face_shape(plan.get("face",[0,0,0,0]))
    event_time = 0
    echo_taken = false
    completed += 1
    return true

func busy() -> bool:
    return event_time < 3.3

func advance(delta: float, actor: Node3D) -> void:
    var step := delta if actor.mutation else 0.0
    clock += step
    event_time += step
    intensity = smoothstep(0,.22,event_time)*(1-smoothstep(1.0,1.3,event_time))
    var strength: float = actor.effects_amount if enabled else 0.0
    var bone: int = actor.skeleton.find_bone(focus_bone)
    if bone < 0:
        bone = actor.skeleton.find_bone("Head")
    focus = (actor.skeleton.global_transform*actor.skeleton.get_bone_global_pose(bone)).origin
    actor.scale = family_from.lerp(family_target,smoothstep(.22,1.02,event_time)).lerp(Vector3.ONE,1-actor.anatomy_amount)
    if actor.face_revision != face_revision and not actor.face_maps.is_empty():
        face_revision = actor.face_revision
        face_history.push_front(actor.face_maps.duplicate())
        if face_history.size() > 3:
            face_history.pop_back()
    for i in range(modules.size()-1,-1,-1):
        var module = modules[i]
        module.advance(step,actor,actor.anatomy_amount)
        module.sync_material(actor,face_history[mini(i%3,face_history.size()-1)] if not face_history.is_empty() else {})
        if module.target == 0 and module.growth <= 0 and module.birth_delay <= 0:
            module.queue_free()
            modules.remove_at(i)
    if event_time >= .22 and not echo_taken:
        echo_taken = true
        if strength > 0:
            _take_echo(actor)
        if actor.mutation_audio > 0 and enabled and DisplayServer.get_name() != "headless":
            sound.global_position = focus
            sound.volume_db = linear_to_db(maxf(.001,actor.mutation_audio*.3))
            sound.play()
    sound.stream_paused = not actor.mutation
    if not enabled or actor.mutation_audio <= 0:
        sound.stop()
    for i in range(echoes.size()-1,-1,-1):
        var echo: Dictionary = echoes[i]
        echo.age += step
        var mat: ShaderMaterial = echo.node.material_override
        mat.set_shader_parameter("opacity",maxf(0,1-echo.age/.18)*.16*strength)
        echo.node.position.x += step*.2
        if echo.age >= .18:
            echo.root.queue_free()
            echoes.remove_at(i)
    lens.set_shader_parameter("center_world",focus)
    lens.set_shader_parameter("intensity",intensity*strength)
    lens.set_shader_parameter("clock",clock)
    distortion.visible = strength > 0 and intensity > .001
    light.global_position = focus+Vector3(0,.3,.2)
    light.light_energy = intensity*strength*.75
    var floor_center := Vector3(actor.global_position.x,.025,actor.global_position.z)
    ring.global_position = floor_center
    ring.scale = Vector3.ONE*maxf(.01,event_time*1.8)
    ring.visible = event_time < 1.3 and strength > 0
    ring.material_override.albedo_color.a = intensity*strength*.16
    for i in range(debris.size()):
        var angle := i*TAU/debris.size()
        var radius := .7+float(i%4)*.18
        debris[i].visible = strength > 0 and intensity > .01
        debris[i].global_position = floor_center+Vector3(cos(angle)*radius,intensity*(.12+.08*(i%3)),sin(angle)*radius)
        debris[i].rotation = Vector3(clock+i,clock*.7,i)*intensity

func _take_echo(actor: Node3D) -> void:
    # Snapshot the old pose without a GPU readback; the mesh and skin are shared,
    # the skeleton is copied and survives destruction of the previous body actor.
    var root_ := Node3D.new()
    add_child(root_)
    root_.global_transform = actor.skeleton.global_transform
    var rig: Skeleton3D = actor.skeleton.duplicate(0)
    for child in rig.get_children():
        child.free()
    root_.add_child(rig)
    rig.transform = Transform3D.IDENTITY
    var mesh := MeshInstance3D.new()
    rig.add_child(mesh)
    mesh.mesh = actor.surface.mesh
    mesh.skin = actor.surface.skin
    mesh.skeleton = mesh.get_path_to(rig)
    mesh.transform = actor.skeleton.global_transform.affine_inverse()*actor.surface.global_transform
    for i in range(actor.surface.get_blend_shape_count()):
        mesh.set_blend_shape_value(i,actor.surface.get_blend_shape_value(i))
    var mat := ShaderMaterial.new()
    mat.shader = preload("res://shaders/mutation_echo.gdshader")
    mesh.material_override = mat
    mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
    echoes.append({"node":mesh,"root":root_,"age":0.0})

func _sound() -> AudioStreamWAV:
    var bytes := PackedByteArray()
    var rate := 22050
    bytes.resize(rate*2)
    for i in range(rate):
        var t := float(i)/rate
        var envelope := sin(PI*t)*exp(-t*2)
        var voice := sin(TAU*73*t+sin(TAU*3*t)*2)*.45
        voice += sin(TAU*111*t+sin(TAU*7*t))*.25+sin(TAU*147*t)*.12
        bytes.encode_s16(i*2,int(voice*envelope*12000))
    var stream := AudioStreamWAV.new()
    stream.format = AudioStreamWAV.FORMAT_16_BITS
    stream.mix_rate = rate
    stream.data = bytes
    return stream

func _exit_tree() -> void:
    sound.stop()
    if is_instance_valid(distortion):
        distortion.queue_free()
