shader_type spatial;
render_mode unshaded, blend_mix, depth_draw_never, cull_disabled, shadows_disabled;

uniform sampler2D scene_depth : hint_depth_texture, repeat_disable, filter_nearest;
uniform sampler2D turbulence : repeat_enable, filter_linear_mipmap;
uniform float age = 0.0;
uniform float seed = 0.0;
uniform float density = 0.65;
uniform float radius = 1.0;
uniform float clock = 0.0;

void vertex() {
    // World-space particles, view-facing sampling planes; ordinary depth testing
    // keeps the room's opaque walls and the creature in front when appropriate.
    MODELVIEW_MATRIX = VIEW_MATRIX * mat4(INV_VIEW_MATRIX[0], INV_VIEW_MATRIX[1], INV_VIEW_MATRIX[2], MODEL_MATRIX[3]);
    VERTEX *= radius;
}

void fragment() {
    vec2 xy = UV * 2.0 - 1.0;
    float r2 = dot(xy, xy);
    float thickness = sqrt(max(0.0, 1.0-r2));
    float optical_depth = 0.0;
    float wisps = 0.0;
    // Integrate a turbulent sphere rather than draw a flat smoke disc.
    for (int i = 0; i < 8; i++) {
        float z = mix(-thickness, thickness, (float(i)+0.5)/8.0);
        vec3 p = vec3(xy, z);
        vec2 drift = vec2(seed * .137, seed * .317 - clock * .045);
        float broad = texture(turbulence, p.xy*.32 + p.z*.19 + drift).r;
        float detail = texture(turbulence, p.yz*.83 + p.x*.24 + drift.yx + broad*.22).r;
        float cloud = smoothstep(.29, .72, broad*.72+detail*.28);
        float shell = (1.0-smoothstep(.15, 1.0, dot(p,p)));
        optical_depth += cloud*shell*thickness*.42;
        wisps += detail*.125;
    }
    float envelope = smoothstep(0.0, .16, age)*(1.0-smoothstep(.45, 1.0, age));
    // Depth unprojection follows Godot's advanced_postprocessing documentation.
    float depth = texture(scene_depth, SCREEN_UV).r;
    #if CURRENT_RENDERER == RENDERER_COMPATIBILITY
    vec3 ndc = vec3(SCREEN_UV, depth)*2.0-1.0;
    #else
    vec3 ndc = vec3(SCREEN_UV*2.0-1.0, depth);
    #endif
    vec4 scene_view = INV_PROJECTION_MATRIX * vec4(ndc, 1.0);
    float gap = -scene_view.z/scene_view.w + VERTEX.z;
    float soft_intersection = smoothstep(0.0, .18, gap);
    float near_fade = smoothstep(.25, .8, -VERTEX.z);
    ALPHA = (1.0-exp(-optical_depth*density*2.0))*envelope*soft_intersection*near_fade;
    ALBEDO = mix(vec3(.009,.012,.015), vec3(.055,.063,.067), wisps*.65);
}
