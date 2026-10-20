shader_type spatial;
render_mode diffuse_burley;

uniform vec3 base_color : source_color = vec3(0.36, 0.35, 0.32);
uniform float floor_surface = 0.0;
uniform float dampness = 0.35;
varying vec3 world_position;
varying vec3 world_normal;

float hash(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}
float noise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f*f*(3.0-2.0*f);
    return mix(mix(mix(hash(i), hash(i+vec3(1,0,0)), f.x),
        mix(hash(i+vec3(0,1,0)), hash(i+vec3(1,1,0)), f.x), f.y),
        mix(mix(hash(i+vec3(0,0,1)), hash(i+vec3(1,0,1)), f.x),
        mix(hash(i+vec3(0,1,1)), hash(i+vec3(1,1,1)), f.x), f.y), f.z);
}
void vertex() {
    world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    world_normal = normalize(mat3(MODEL_MATRIX) * NORMAL);
}
void fragment() {
    vec3 p = world_position;
    float broad = noise(p*0.62);
    float patches = noise(p*2.8+vec3(7.2));
    float grit = noise(p*92.0);
    float wet = smoothstep(0.48, 0.77, broad*0.65+patches*0.35)*dampness;
    float low_stain = (1.0-smoothstep(0.1, 1.4, p.y))*0.35*(1.0-floor_surface);
    vec3 col = base_color*(0.76+0.3*broad+0.12*patches);
    col *= 1.0-wet*0.35-low_stain;
    col += (grit-0.5)*0.035;
    // Real-scale expansion joints, not the former high-contrast test grid.
    vec2 plane = abs(world_normal.y) > 0.5 ? p.xz : (abs(world_normal.x) > 0.5 ? p.zy : p.xy);
    vec2 joint = abs(fract((plane+0.01)/2.4)-0.5)*2.4;
    float line = 1.0-smoothstep(0.003, 0.012, min(joint.x, joint.y));
    col *= 1.0-line*0.24;
    ALBEDO = col;
    ROUGHNESS = mix(0.92, 0.40, wet);
    SPECULAR = 0.32;
    float height = (patches*0.5+grit*0.5)*0.0014;
    vec3 sx = dFdx(VERTEX), sy = dFdy(VERTEX);
    vec3 r1 = cross(sy, NORMAL), r2 = cross(NORMAL, sx);
    float det = dot(sx, r1);
    NORMAL = normalize(abs(det)*NORMAL-sign(det)*(dFdx(height)*r1+dFdy(height)*r2));
}
