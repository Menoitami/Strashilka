extends Node3D
## A shared spatial neural field. Camera motion never selects or regenerates a view.
var material := ShaderMaterial.new()
var previous_texture: ImageTexture3D
var next_texture: ImageTexture3D
var packet: Dictionary = {}
var progress := 1.0
var duration := 4.0
var clock := 0.0
var frozen := false
var effects := .35
var updates := 0
var error := ""
var pending: Dictionary = {}
var next_detail: ImageTexture
var next_projection := Vector4.ZERO

func build(camera: Camera3D) -> void:
    var screen := MeshInstance3D.new()
    var quad := QuadMesh.new()
    quad.size = Vector2(2,2)
    screen.mesh = quad
    screen.extra_cull_margin = 16384
    screen.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
    material.shader = preload("res://shaders/neural_field.gdshader")
    screen.material_override = material
    camera.add_child(screen)

func load_field(directory: String) -> bool:
    if not queue_field(directory):
        return false
    start_pending()
    return true

func queue_field(directory: String) -> bool:
    var path := directory.path_join("field.json")
    if not FileAccess.file_exists(path):
        error = "Missing field manifest: "+path
        return false
    var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
    if not parsed is Dictionary or parsed.get("schema",0) != 2 or parsed.get("representation","") != "neural_density_rgba8":
        error = "Invalid neural field manifest"
        return false
    var size := int(parsed.get("resolution",0))
    if size not in [64,80,96,128,160,192] or not parsed.get("alignment") is Dictionary:
        error = "Invalid field dimensions"
        return false
    var alignment: Dictionary = parsed.alignment
    var origin = alignment.get("origin",[])
    var radius := float(alignment.get("radius",0))
    var scale_ := float(alignment.get("scale",0))
    if not origin is Array or origin.size()!=3 or not is_finite(radius) or not is_finite(scale_) or radius<=0 or scale_<=0 or scale_>20:
        error = "Invalid field placement"
        return false
    for component in origin:
        if not (component is float or component is int) or not is_finite(float(component)):
            error = "Invalid field origin"
            return false
    var focus = parsed.get("focus",[0,1.8,0])
    if not focus is Array or focus.size()!=3:
        error = "Invalid field focus"
        return false
    for component in focus:
        if not (component is float or component is int) or not is_finite(float(component)):
            error = "Invalid field focus"
            return false
    var amount := float(parsed.get("change",0))
    if not is_finite(amount):
        error = "Invalid field change amount"
        return false
    var bytes := FileAccess.get_file_as_bytes(directory.path_join("field.rgba"))
    if bytes.size() != size*size*size*4 or int(parsed.get("bytes",0)) != bytes.size():
        error = "Truncated neural field"
        return false
    var slices: Array[Image] = []
    for z in range(size):
        slices.append(Image.create_from_data(size,size,false,Image.FORMAT_RGBA8,bytes.slice(z*size*size*4,(z+1)*size*size*4)))
    var texture := ImageTexture3D.new()
    if texture.create(Image.FORMAT_RGBA8,size,size,size,false,slices) != OK:
        error = "Cannot upload neural field"
        return false
    var projection := Vector4.ZERO
    var detail_image := Image.create(1,1,false,Image.FORMAT_RGBA8)
    detail_image.fill(Color.TRANSPARENT)
    if parsed.has("front_projection"):
        var values = parsed.front_projection
        if not values is Array or values.size()!=4:
            error = "Invalid detail projection"
            return false
        for value in values:
            if not (value is float or value is int) or not is_finite(float(value)):
                error = "Invalid detail projection"
                return false
        projection = Vector4(values[0],values[1],values[2],values[3])
        if detail_image.load(directory.path_join("concept.png")) != OK:
            error = "Missing neural color detail"
            return false
    pending = {"texture":texture,"packet":parsed,"detail":ImageTexture.create_from_image(detail_image),"projection":projection}
    error = ""
    return true

func start_pending(carry: float = 0.0) -> bool:
    if pending.is_empty():
        return false
    var texture: ImageTexture3D = pending.texture
    var parsed: Dictionary = pending.packet
    var alignment: Dictionary = parsed.alignment
    var origin: Array = alignment.origin
    var radius := float(alignment.radius)
    var scale_ := float(alignment.scale)
    var size := int(parsed.resolution)
    var focus: Array = parsed.get("focus",[0,1.8,0])
    var amount := float(parsed.get("change",0))
    var detail: ImageTexture = pending.detail
    var projection: Vector4 = pending.projection
    pending = {}
    # A complete upload commits atomically. Invalid packets leave the visible field untouched.
    previous_texture = next_texture if next_texture != null else texture
    next_texture = texture
    material.set_shader_parameter("detail_a",next_detail if next_detail!=null else detail)
    material.set_shader_parameter("detail_b",detail)
    material.set_shader_parameter("projection_a",next_projection if next_detail!=null else projection)
    material.set_shader_parameter("projection_b",projection)
    next_detail = detail
    next_projection = projection
    packet = parsed
    var offset := Vector3(float(origin[0]),float(origin[1]),float(origin[2]))
    material.set_shader_parameter("field_min",(Vector3.ONE*-radius-offset)*scale_)
    material.set_shader_parameter("field_max",(Vector3.ONE*radius-offset)*scale_)
    material.set_shader_parameter("field_a",previous_texture)
    material.set_shader_parameter("field_b",next_texture)
    material.set_shader_parameter("grid_size",float(size))
    material.set_shader_parameter("steps",mini(384,size*2))
    material.set_shader_parameter("field_ready",true)
    material.set_shader_parameter("change_focus",Vector3(float(focus[0]),float(focus[1]),float(focus[2])))
    material.set_shader_parameter("change_amount",clampf(amount,0,1))
    progress = clampf(carry/maxf(duration,.25),0,1) if updates>0 else 1.0
    updates += 1
    error = ""
    return true

func advance(delta: float) -> void:
    if not frozen:
        clock += delta
        var next_progress := progress+delta/maxf(duration,.25)
        if next_progress>=1.0 and not pending.is_empty():
            start_pending(maxf(0,next_progress-1.0)*duration)
        else:
            progress = minf(next_progress,1.0)
    material.set_shader_parameter("progress",progress)
    material.set_shader_parameter("clock",clock)
    material.set_shader_parameter("effects",effects)
