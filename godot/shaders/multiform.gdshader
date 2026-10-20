shader_type spatial;
render_mode cull_disabled;
uniform sampler2D albedo_0 : source_color, filter_linear_mipmap;
uniform sampler2D albedo_1 : source_color, filter_linear_mipmap;
uniform sampler2D albedo_2 : source_color, filter_linear_mipmap;
uniform sampler2D normal_0 : hint_normal, filter_linear_mipmap;
uniform sampler2D normal_1 : hint_normal, filter_linear_mipmap;
uniform sampler2D normal_2 : hint_normal, filter_linear_mipmap;
uniform bool face_enabled = false;
uniform sampler2D face_albedo_previous : source_color, filter_linear_mipmap;
uniform sampler2D face_albedo_next : source_color, filter_linear_mipmap;
uniform sampler2D face_normal_previous : hint_normal, filter_linear_mipmap;
uniform sampler2D face_normal_next : hint_normal, filter_linear_mipmap;
uniform sampler2D face_mask : filter_linear_mipmap;
uniform float face_mix = 0.0;
uniform vec4 face_shape = vec4(0.0);
uniform vec2 head_bounds = vec2(2.25, 2.9);
uniform bool face_flow_enabled = false;
uniform vec3 face_projection = vec3(0.0, 2.5, .7);
uniform sampler2D face_portrait_previous : source_color, filter_linear;
uniform sampler2D face_portrait_next : source_color, filter_linear;
uniform sampler2D face_flow_forward : filter_linear;
uniform sampler2D face_flow_backward : filter_linear;
uniform bool use_vertex_color = false;
uniform bool use_normal_maps = true;
uniform int module_mode = 0;
uniform float growth = 1.0;
uniform float module_length = 1.0;
uniform vec3 canonical_origin = vec3(0.0);
uniform mat3 canonical_basis = mat3(1.0);
varying vec2 portrait_uv;
uniform vec3 form_weights = vec3(1.0, 0.0, 0.0);
uniform float color_blend : hint_range(0.0, 1.0) = 1.0;
uniform float relief_blend : hint_range(0.0, 1.0) = 1.0;
uniform float relief_strength : hint_range(0.0, 2.0) = 0.7;
uniform float roughness_value : hint_range(0.05, 1.0) = 0.75;
uniform int debug_view = 0;
uniform float flow_amount : hint_range(0.0, 0.18) = 0.0;
uniform float flow_speed : hint_range(0.0, 3.0) = 1.0;
uniform float flow_clock = 0.0;
uniform float monochrome : hint_range(0.0, 1.0) = 0.0;
uniform float contrast_value : hint_range(0.5, 2.5) = 1.0;
uniform float skin_detail : hint_range(0.0, 1.0) = 0.65;
uniform float skin_wetness : hint_range(0.0, 1.0) = 0.35;
varying vec3 skin_position;
float skin_hash(vec3 p) {
    p = fract(p*0.1031);
    p += dot(p, p.yzx+33.33);
    return fract((p.x+p.y)*p.z);
}
float skin_noise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f*f*(3.0-2.0*f);
    return mix(mix(mix(skin_hash(i),skin_hash(i+vec3(1,0,0)),f.x),
        mix(skin_hash(i+vec3(0,1,0)),skin_hash(i+vec3(1,1,0)),f.x),f.y),
        mix(mix(skin_hash(i+vec3(0,0,1)),skin_hash(i+vec3(1,0,1)),f.x),
        mix(skin_hash(i+vec3(0,1,1)),skin_hash(i+vec3(1,1,1)),f.x),f.y),f.z);
}
void vertex() {
    // Supplementary procedural surface motion; new large shapes still come from neural inference.
    vec3 p = VERTEX;
    vec3 canonical = module_mode == 0 ? p : canonical_basis*p+canonical_origin;
    portrait_uv = vec2((canonical.x-face_projection.x)/face_projection.z+.5,
        .5-(canonical.y-face_projection.y)/face_projection.z);
    float height = max(.1, head_bounds.y-head_bounds.x);
    float h = (canonical.y-head_bounds.x)/height;
    float head = smoothstep(0.0,.2,h);
    float jaw = head*(1.0-smoothstep(.3,.62,h));
    float front = smoothstep(-.04,.12,canonical.z);
    if (module_mode == 0 || module_mode == 2) {
        vec3 change = vec3(face_shape.z*.018*head*front,
            -face_shape.x*.035*jaw+face_shape.w*.045*smoothstep(.55,1.0,h),
            face_shape.x*.022*jaw*front);
        // A continuous, bounded field keeps eyelids/nose from folding through each other.
        change.x += face_shape.y*.02*exp(-pow((h-.62)*7.0,2.0))*clamp(canonical.x/.12,-1.0,1.0)*front;
        VERTEX += module_mode == 0 ? change : transpose(canonical_basis)*change;
    }
    if (module_mode != 0) {
        // Distal vertices unfold only when the advancing growth front reaches them.
        float tip = max(.001,growth*module_length);
        float radial = mix(1.0-smoothstep(tip-.08,tip+.08,p.y),1.0,smoothstep(.9,1.0,growth));
        VERTEX.xz *= max(.015,radial)*smoothstep(0.0,.15,growth);
        VERTEX.y -= max(0.0,p.y-tip);
    }
    skin_position = p;
    float t = flow_clock*flow_speed;
    vec3 a = vec3(3.7, 2.2, 2.9);
    vec3 b = vec3(-2.1, 4.8, 1.7);
    float pa = dot(p, a)+t;
    float pb = dot(p, b)-t*1.27;
    float envelope = smoothstep(0.12, 0.6, p.y);
    float wave = (sin(pa)*0.6+sin(pb)*0.4)*flow_amount*envelope*growth;
    vec3 gradient = (cos(pa)*a*0.6+cos(pb)*b*0.4)*flow_amount*envelope;
    VERTEX += NORMAL*wave;
    NORMAL = normalize(NORMAL-gradient+NORMAL*dot(gradient,NORMAL));
}
void fragment() {
    vec3 cw = mix(vec3(1.0, 0.0, 0.0), form_weights, color_blend);
    vec3 nw = mix(vec3(1.0, 0.0, 0.0), form_weights, relief_blend);
    vec3 color = texture(albedo_0, UV).rgb*cw.x + texture(albedo_1, UV).rgb*cw.y + texture(albedo_2, UV).rgb*cw.z;
    if (use_vertex_color) { color = COLOR.rgb; }
    vec3 normal = normalize((texture(normal_0, UV).rgb*2.0-1.0)*nw.x + (texture(normal_1, UV).rgb*2.0-1.0)*nw.y + (texture(normal_2, UV).rgb*2.0-1.0)*nw.z);
    if (!use_normal_maps) { normal = vec3(0,0,1); }
    if (face_enabled) {
        float mask = texture(face_mask, UV).r;
        vec3 portrait = mix(texture(face_albedo_previous, UV).rgb, texture(face_albedo_next, UV).rgb, face_mix);
        if (face_flow_enabled) {
            vec2 uv = clamp(portrait_uv,vec2(.002),vec2(.998));
            vec3 f = texture(face_flow_forward,uv).rgb;
            vec3 b = texture(face_flow_backward,uv).rgb;
            vec2 before = clamp(uv-(f.xy*255.0-128.0)/1024.0*face_mix*f.z,vec2(.002),vec2(.998));
            vec2 after = clamp(uv-(b.xy*255.0-128.0)/1024.0*(1.0-face_mix)*b.z,vec2(.002),vec2(.998));
            vec4 a = texture(face_portrait_previous,before);
            vec4 c = texture(face_portrait_next,after);
            float valid = step(0.0,portrait_uv.x)*step(portrait_uv.x,1.0)*step(0.0,portrait_uv.y)*step(portrait_uv.y,1.0);
            portrait = mix(portrait,mix(a.rgb,c.rgb,face_mix),min(a.a,c.a)*valid);
        }
        vec3 face_normal = normalize(mix(texture(face_normal_previous, UV).rgb*2.0-1.0,
            texture(face_normal_next, UV).rgb*2.0-1.0, face_mix));
        color = mix(color, portrait, mask*color_blend);
        normal = normalize(mix(normal, face_normal, mask*relief_blend));
    }
    color = mix(color, vec3(dot(color, vec3(0.2126, 0.7152, 0.0722))), monochrome);
    color = clamp((color-0.35)*contrast_value+0.35, vec3(0.0), vec3(1.0));
    // Millimetre-scale detail attenuates with screen footprint to prevent glitter.
    float footprint = max(length(dFdx(skin_position)), length(dFdy(skin_position)));
    float detail = skin_detail*(1.0-smoothstep(.0015,.012,footprint));
    float pores = skin_noise(skin_position*370.0);
    float blotches = skin_noise(skin_position*19.0);
    color *= 1.0+(pores-.5)*.06*detail;
    ALBEDO = debug_view == 1 ? vec3(0.65) : color;
    NORMAL_MAP = normal*0.5+0.5;
    NORMAL_MAP_DEPTH = debug_view == 1 ? 0.0 : relief_strength;
    float warm_tissue = clamp((color.r-color.g)*3.0+0.25,0.0,1.0);
    float moisture = skin_wetness*(.25+.75*blotches)*warm_tissue;
    ROUGHNESS = clamp(roughness_value+(pores-.5)*.12*detail-moisture*.42, .28, .98);
    SPECULAR = mix(.28,.48,moisture);
    RIM = .06*skin_detail;
    RIM_TINT = .3;
    if (debug_view == 2) {
        ALBEDO = vec3(0.0);
        EMISSION = normal*0.5+0.5;
    }
}
