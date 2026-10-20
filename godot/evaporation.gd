extends Node3D
## Detached world-space wisps sampled from animated body bones. Persistent across GLB swaps.
var enabled := true
var density := .25
var rise_speed := .35
var clock := 0.0
var particles: Array[Dictionary] = []
var rng := RandomNumberGenerator.new()
var last_pulse := 0.0
const COUNT = 28
const BONES = ["Pelvis", "Chest", "Head", "ShoulderL", "ShoulderR", "ElbowL", "ElbowR", "HipL", "HipR"]

func _ready() -> void:
    top_level = true
    global_transform = Transform3D.IDENTITY
    rng.seed = 49213
    var noise := FastNoiseLite.new()
    noise.seed = 927
    noise.frequency = .018
    noise.fractal_octaves = 4
    var texture := NoiseTexture2D.new()
    texture.width = 256
    texture.height = 256
    texture.seamless = true
    texture.generate_mipmaps = true
    texture.noise = noise
    var quad := QuadMesh.new()
    quad.size = Vector2.ONE
    for i in range(COUNT):
        var mesh := MeshInstance3D.new()
        mesh.mesh = quad
        mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
        mesh.extra_cull_margin = 3
        var material := ShaderMaterial.new()
        material.shader = preload("res://shaders/evaporation.gdshader")
        material.set_shader_parameter("turbulence", texture)
        material.set_shader_parameter("seed", float(i)*3.71)
        mesh.material_override = material
        add_child(mesh)
        particles.append({"node": mesh, "material": material, "age": -float(i)/COUNT*3.8,
            "life": rng.randf_range(2.8, 4.2), "origin": Vector3.ZERO, "drift": Vector3.ZERO, "born": false,
            "radius": rng.randf_range(.65, 1.15)})

func advance(delta: float, actor: Node3D, focus: Vector3 = Vector3.ZERO, pulse: float = 0.0) -> void:
    visible = enabled
    if not enabled:
        # Hidden particles expire; turning it on never shows stale smoke elsewhere.
        for i in range(particles.size()):
            particles[i].born = false
            particles[i].age = -float(i)/COUNT*.8
        return
    clock += delta
    if pulse > .12 and last_pulse <= .12:
        for i in range(0,16,2):
            particles[i].age = 0
            particles[i].born = false
    last_pulse = pulse
    for i in range(particles.size()):
        var particle := particles[i]
        particle.age += delta
        if particle.age < 0:
            particle.node.visible = false
            continue
        if not particle.born or particle.age >= particle.life:
            particle.age = fposmod(particle.age, particle.life) if not particle.born else 0.0
            var origin: Vector3 = actor.global_position+Vector3(0, 1.4, 0)
            if actor.skeleton != null:
                var bone: int = actor.skeleton.find_bone(BONES[i%BONES.size()])
                if bone >= 0:
                    origin = actor.skeleton.global_transform * actor.skeleton.get_bone_global_pose(bone).origin
            if pulse > .1 and i%2 == 0:
                origin = focus
            particle.origin = origin + Vector3(rng.randf_range(-.18,.18), rng.randf_range(-.12,.12), rng.randf_range(-.2,.2))
            particle.drift = Vector3(rng.randf_range(-.16,.16), rng.randf_range(.8,1.2), rng.randf_range(-.12,.12))
            particle.born = true
        var t: float = particle.age
        particle.node.visible = true
        particle.node.position = particle.origin+Vector3(particle.drift.x*t+.1*sin(t*2+i), particle.drift.y*t*rise_speed, particle.drift.z*t+.08*cos(t*1.7+i))
        particle.material.set_shader_parameter("age", t/particle.life)
        particle.material.set_shader_parameter("clock", clock)
        particle.material.set_shader_parameter("radius", particle.radius*(.7+t*.25))
        particle.material.set_shader_parameter("density", density+pulse*.35 if i%2 == 0 else density)
