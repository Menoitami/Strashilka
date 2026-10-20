shader_type spatial;
render_mode unshaded, fog_disabled, cull_disabled, depth_test_disabled, depth_draw_never;
uniform sampler3D field_a : filter_linear, repeat_disable;
uniform sampler3D field_b : filter_linear, repeat_disable;
uniform sampler2D detail_a : filter_linear, repeat_disable;
uniform sampler2D detail_b : filter_linear, repeat_disable;
uniform vec4 projection_a = vec4(0.0);
uniform vec4 projection_b = vec4(0.0);
uniform sampler2D scene_color : hint_screen_texture, filter_linear;
uniform sampler2D scene_depth : hint_depth_texture, filter_nearest;
uniform vec3 field_min = vec3(-2.0,0.0,-2.0);
uniform vec3 field_max = vec3(2.0,4.0,2.0);
uniform vec3 change_focus = vec3(0.0,1.8,0.0);
uniform float progress = 1.0;
uniform float clock = 0.0;
uniform float effects = 0.35;
uniform float change_amount = 0.0;
uniform float iso_level = 10.0;
uniform int steps = 176;
uniform float grid_size = 96.0;
uniform bool field_ready = false;

void vertex() { POSITION = vec4(VERTEX.xy,1.0,1.0); }
vec3 world_at(vec2 uv, float depth, mat4 inverse_projection, mat4 inverse_view) {
    #if CURRENT_RENDERER == RENDERER_COMPATIBILITY
    vec3 ndc = vec3(uv,depth)*2.0-1.0;
    #else
    vec3 ndc = vec3(uv*2.0-1.0,depth);
    #endif
    vec4 p = inverse_view*inverse_projection*vec4(ndc,1.0);
    return p.xyz/p.w;
}
float phase_at(vec3 uv) {
    // Spatially staggered interpolation, identical for every camera. Endpoints remain exact.
    float lag = .08*sin(uv.y*5.0+uv.x*2.0+uv.z*3.0);
    float t = clamp(progress + lag*sin(progress*3.14159265),0.0,1.0);
    return t;
}
vec3 texcoord(vec3 uv) {
    // Grid endpoints describe the box edges, rather than texture edge texel centers.
    return (uv*(grid_size-1.0)+.5)/grid_size;
}
vec4 sample_field(vec3 uv) {
    return mix(texture(field_a,texcoord(uv)),texture(field_b,texcoord(uv)),phase_at(uv));
}
float density_at(vec3 uv) { return exp(sample_field(uv).a*log(129.0))-1.0; }
void fragment() {
    vec3 background = texture(scene_color,SCREEN_UV).rgb;
    vec3 result = background;
    if (field_ready) {
        vec3 origin = INV_VIEW_MATRIX[3].xyz;
        vec3 endpoint = world_at(SCREEN_UV,texture(scene_depth,SCREEN_UV).r,INV_PROJECTION_MATRIX,INV_VIEW_MATRIX);
        vec3 direction = normalize(endpoint-origin);
        float scene_distance = length(endpoint-origin);
        vec3 safe_dir = vec3(direction.x>=0.0?1.0:-1.0,direction.y>=0.0?1.0:-1.0,direction.z>=0.0?1.0:-1.0)*max(abs(direction),vec3(.000001));
        vec3 t0 = (field_min-origin)/safe_dir;
        vec3 t1 = (field_max-origin)/safe_dir;
        vec3 lo = min(t0,t1), hi = max(t0,t1);
        float start = max(max(lo.x,lo.y),max(lo.z,0.0));
        float end = min(min(hi.x,hi.y),min(hi.z,scene_distance));
        vec3 extent = field_max-field_min;
        float pulse = sin(progress*3.14159265)*change_amount;
        // Refract only background behind the region where the neural field changed.
        float along = max(dot(change_focus-origin,direction),0.0);
        float distance_to_focus = length(origin+direction*along-change_focus);
        float lens = exp(-distance_to_focus*distance_to_focus*2.2)*pulse*effects;
        lens *= smoothstep(along-.7,along+.1,scene_distance);
        vec2 offset = vec2(sin(clock*2.2+direction.y*23.0),cos(clock*1.8+direction.x*21.0))*.008*lens;
        vec2 warped_uv = clamp(SCREEN_UV+offset,vec2(.001),vec2(.999));
        vec3 warped_world = world_at(warped_uv,texture(scene_depth,warped_uv).r,INV_PROJECTION_MATRIX,INV_VIEW_MATRIX);
        float safe_warp = smoothstep(along-.7,along+.1,length(warped_world-origin));
        result = texture(scene_color,mix(SCREEN_UV,warped_uv,safe_warp)).rgb;
        if (end>start) {
            float step_size = length(extent)/float(steps);
            float t = start + step_size*.25;
            vec3 accumulated = vec3(0.0);
            float opacity = 0.0;
            for (int i=0;i<512;i++) {
                if (i>=steps || t>end || opacity>.985) { break; }
                vec3 pos = origin+direction*t;
                vec3 uv = clamp((pos-field_min)/extent,vec3(0.0),vec3(1.0));
                vec4 field = sample_field(uv);
                float density = exp(field.a*log(129.0))-1.0;
                float solid = smoothstep(iso_level*.65,iso_level*1.15,density);
                float alpha = (1.0-exp(-max(density-iso_level*.5,0.0)*step_size*5.0))*solid;
                float delta_density = abs(texture(field_a,texcoord(uv)).a-texture(field_b,texcoord(uv)).a);
                // Faint residual neural tissue, confined to changing regions of the same 3D field.
                alpha += (1.0-alpha)*effects*pulse*delta_density*.035;
                if (alpha>.002) {
                    float e = 1.0/grid_size;
                    vec3 normal = -vec3(density_at(uv+vec3(e,0,0))-density_at(uv-vec3(e,0,0)),
                        density_at(uv+vec3(0,e,0))-density_at(uv-vec3(0,e,0)),
                        density_at(uv+vec3(0,0,e))-density_at(uv-vec3(0,0,e)));
                    normal /= max(length(normal),.00001);
                    float lighting = .46+.40*max(dot(normal,normalize(vec3(-.5,.8,.7))),0.0)+.20*max(dot(normal,-direction),0.0);
                    vec4 detail_old = texture(detail_a,vec2(uv.x*projection_a.x+projection_a.y,uv.y*projection_a.z+projection_a.w));
                    vec4 detail_new = texture(detail_b,vec2(uv.x*projection_b.x+projection_b.y,uv.y*projection_b.z+projection_b.w));
                    vec4 detail = mix(detail_old,detail_new,phase_at(uv));
                    // Color lives on the 3D surface; rotating the camera never rotates this projection.
                    float detail_weight = smoothstep(.05,.65,normal.z)*detail.a*.92;
                    vec3 flesh = mix(field.rgb,detail.rgb,detail_weight)*lighting;
                    flesh += vec3(.11,.014,.008)*pulse*effects*delta_density;
                    accumulated += (1.0-opacity)*alpha*flesh;
                    opacity += (1.0-opacity)*alpha;
                }
                t += step_size;
            }
            result = accumulated+(1.0-opacity)*result;
        }
    }
    ALBEDO = result;
}
