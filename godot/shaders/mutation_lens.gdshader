shader_type spatial;
render_mode unshaded, fog_disabled, cull_disabled, depth_draw_never, depth_test_disabled;
uniform sampler2D screen_texture : hint_screen_texture, filter_linear;
uniform sampler2D depth_texture : hint_depth_texture, filter_nearest;
uniform vec3 center_world;
uniform float intensity = 0.0;
uniform float clock = 0.0;
uniform float radius = 1.05;
void vertex() { POSITION = vec4(VERTEX.xy,1.0,1.0); }
float distance_at(vec2 uv, mat4 inverse_projection) {
    float depth = texture(depth_texture,uv).r;
    #if CURRENT_RENDERER == RENDERER_COMPATIBILITY
    vec3 ndc = vec3(uv,depth)*2.0-1.0;
    #else
    vec3 ndc = vec3(uv*2.0-1.0,depth);
    #endif
    vec4 view = inverse_projection*vec4(ndc,1.0);
    return -view.z/view.w;
}
void fragment() {
    vec4 center = VIEW_MATRIX*vec4(center_world,1.0);
    vec4 projected = PROJECTION_MATRIX*center;
    vec2 origin = projected.xy/max(.01,projected.w)*.5+.5;
    vec2 extent = vec2(PROJECTION_MATRIX[0][0],PROJECTION_MATRIX[1][1])*radius/max(.1,-center.z)*.5;
    vec2 local = (SCREEN_UV-origin)/extent;
    float d = length(local);
    float mask = (1.0-smoothstep(.55,1.0,d))*smoothstep(.05,.3,d)*step(.1,-center.z);
    float front = -center.z-radius*.65;
    vec2 pixel = 1.0/vec2(textureSize(depth_texture,0));
    float nearest = distance_at(SCREEN_UV,INV_PROJECTION_MATRIX);
    nearest = min(nearest,distance_at(SCREEN_UV+vec2(pixel.x,0),INV_PROJECTION_MATRIX));
    nearest = min(nearest,distance_at(SCREEN_UV-vec2(pixel.x,0),INV_PROJECTION_MATRIX));
    nearest = min(nearest,distance_at(SCREEN_UV+vec2(0,pixel.y),INV_PROJECTION_MATRIX));
    nearest = min(nearest,distance_at(SCREEN_UV-vec2(0,pixel.y),INV_PROJECTION_MATRIX));
    mask *= smoothstep(front,front+.12,nearest);
    vec2 turbulence = vec2(sin(local.y*13.0+clock*7.0),cos(local.x*11.0-clock*5.0));
    vec2 offset = (turbulence*.013+local*sin(d*18.0-clock*9.0)*.014)*mask*intensity;
    vec2 uv = clamp(SCREEN_UV+offset,vec2(.002),vec2(.998));
    // Never pull a foreground column into the lens from an adjacent sample.
    float safe = smoothstep(front,front+.12,distance_at(uv,INV_PROJECTION_MATRIX));
    uv = mix(SCREEN_UV,uv,safe);
    vec3 color = texture(screen_texture,uv).rgb;
    vec2 fringe = offset*.06*safe;
    color.r = texture(screen_texture,clamp(uv+fringe,vec2(.002),vec2(.998))).r;
    color.b = texture(screen_texture,clamp(uv-fringe,vec2(.002),vec2(.998))).b;
    ALBEDO = color;
    ALPHA = mask*intensity;
}
