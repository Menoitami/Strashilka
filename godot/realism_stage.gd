extends Node3D
## Uses the room's original collision shell; all changes here are visual.

var flashlight: SpotLight3D
var key_light: SpotLight3D
var lens: ShaderMaterial
var clock := 0.0
var light_level := 1.0
var lens_strength := .65

func concrete(color: Color, floor_: bool = false) -> ShaderMaterial:
    var mat := ShaderMaterial.new()
    mat.shader = preload("res://shaders/concrete.gdshader")
    mat.set_shader_parameter("base_color", color)
    mat.set_shader_parameter("floor_surface", 1.0 if floor_ else 0.0)
    mat.set_shader_parameter("dampness", .5 if floor_ else .28)
    return mat

func metal(color: Color, roughness: float = .72) -> StandardMaterial3D:
    var mat := StandardMaterial3D.new()
    mat.albedo_color = color
    mat.metallic = .65
    mat.roughness = roughness
    return mat

func box(size: Vector3, at: Vector3, mat: Material) -> MeshInstance3D:
    var node := MeshInstance3D.new()
    var mesh := BoxMesh.new()
    mesh.size = size
    node.mesh = mesh
    node.material_override = mat
    node.position = at
    add_child(node)
    return node

func pipe(at: Vector3, length: float, radius: float, mat: Material) -> void:
    var node := MeshInstance3D.new()
    var mesh := CylinderMesh.new()
    mesh.height = length
    mesh.top_radius = radius
    mesh.bottom_radius = radius
    mesh.radial_segments = 16
    node.mesh = mesh
    node.material_override = mat
    node.position = at
    node.rotation.x = PI/2
    add_child(node)
    for z in [-7.5, -4.5, -1.5, 1.5, 4.5, 7.0]:
        box(Vector3(radius*2.5,.08,.08), Vector3(at.x, at.y, z), mat)

func build(room: Node3D) -> void:
    var wall_mat := concrete(Color("696b61"))
    var floor_mat := concrete(Color("52514a"), true)
    var ceiling_mat := concrete(Color("434640"))
    var rust := metal(Color("534139"))
    var dark_metal := metal(Color("343d3b"))
    for child in room.get_children():
        if child is MeshInstance3D and child.mesh is BoxMesh:
            var size: Vector3 = child.mesh.size
            # Interior shell receives shadows; casting its thin back faces causes
            # large self-shadow stripes in the Compatibility shadow atlas.
            if size.x > 10 or size.z > 10:
                child.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
            if size.y < .01 or size.y < .1:
                child.queue_free()
            elif size.y < .3:
                child.material_override = floor_mat if child.position.y < 1 else ceiling_mat
            else:
                child.material_override = wall_mat
        elif child is OmniLight3D:
            child.queue_free()
        elif child is WorldEnvironment:
            var env: Environment = child.environment
            env.background_color = Color("080b0b")
            env.ambient_light_color = Color("9ca8ad")
            env.ambient_light_energy = .15
            env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
            env.fog_enabled = true
            env.fog_density = .009
            env.fog_light_color = Color("323a38")
            env.fog_light_energy = .35
    # Door recess, lintel, seams and handle give the room a human scale.
    box(Vector3(2.05,3.25,.15), Vector3(0,1.625,-8.78), dark_metal)
    for x in [-1.12, 1.12]:
        box(Vector3(.16,3.45,.24), Vector3(x,1.72,-8.67), wall_mat)
    box(Vector3(2.4,.16,.24), Vector3(0,3.4,-8.67), wall_mat)
    box(Vector3(.018,3.1,.015), Vector3(0,1.65,-8.69), metal(Color("0e1210")))
    box(Vector3(.06,.28,.08), Vector3(.72,1.45,-8.65), rust)
    for x in [-6.7, 6.7]:
        pipe(Vector3(x,4.25,-1), 17.5, .075, rust)
        pipe(Vector3(x,4.0,-1), 17.5, .045, dark_metal)
    for z in [-7.0, -2.0, 3.0]:
        box(Vector3(14,.16,.2), Vector3(0,4.88,z), dark_metal)
    # Main visible fixture and its downward pool of light.
    box(Vector3(1.65,.14,.3), Vector3(-1.4,4.72,-1.5), dark_metal)
    var tube := StandardMaterial3D.new()
    tube.albedo_color = Color("d5d7bb")
    tube.emission_enabled = true
    tube.emission = Color("d5d7bb")
    tube.emission_energy_multiplier = 2.5
    box(Vector3(1.45,.025,.15), Vector3(-1.4,4.63,-1.5), tube)
    key_light = SpotLight3D.new()
    key_light.position = Vector3(-1.4,4.55,-1.5)
    key_light.light_color = Color("e2dfca")
    key_light.light_energy = 2.0
    key_light.spot_range = 13
    key_light.spot_angle = 62
    key_light.spot_angle_attenuation = .8
    key_light.shadow_enabled = true
    key_light.shadow_bias = .03
    key_light.shadow_normal_bias = 1.0
    add_child(key_light)
    key_light.look_at(Vector3(0,1.2,-2.8))
    var bounce := OmniLight3D.new()
    bounce.position = Vector3(3.8,2.0,-6.3)
    bounce.light_color = Color("9baca7")
    bounce.light_energy = .45
    bounce.omni_range = 8
    bounce.shadow_enabled = false
    add_child(bounce)
    flashlight = SpotLight3D.new()
    flashlight.position = Vector3(.18,-.12,.08)
    flashlight.light_color = Color("e3e6db")
    flashlight.light_energy = .85
    flashlight.spot_range = 18
    flashlight.spot_angle = 32
    flashlight.spot_angle_attenuation = 2
    flashlight.shadow_enabled = true
    flashlight.shadow_bias = .03
    flashlight.shadow_normal_bias = 1.0
    room.camera.add_child(flashlight)
    room.camera.fov = 58
    # Screen effect sits below the laboratory controls.
    var canvas := CanvasLayer.new()
    canvas.layer = 0
    add_child(canvas)
    var screen := ColorRect.new()
    screen.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
    screen.mouse_filter = Control.MOUSE_FILTER_IGNORE
    lens = ShaderMaterial.new()
    lens.shader = preload("res://shaders/lens.gdshader")
    screen.material = lens
    canvas.add_child(screen)
    room.get_viewport().msaa_3d = Viewport.MSAA_4X

func advance(delta: float) -> void:
    clock += delta
    # A tired ballast varies subtly; no full-screen strobe.
    key_light.light_energy = 2.0*light_level*(.985+.01*sin(clock*1.7)+.005*sin(clock*11.3))
    lens.set_shader_parameter("strength", lens_strength)
