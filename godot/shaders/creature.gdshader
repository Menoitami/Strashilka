shader_type spatial;
render_mode unshaded, cull_disabled, blend_mix, depth_prepass_alpha;

uniform sampler2D previous_image : source_color, filter_linear, repeat_disable;
uniform sampler2D current_image : source_color, filter_linear, repeat_disable;
uniform sampler2D forward_flow : filter_linear, repeat_disable;
uniform sampler2D backward_flow : filter_linear, repeat_disable;
uniform float progress : hint_range(0.0, 1.0) = 1.0;
uniform bool use_flow = false;
uniform vec2 image_size = vec2(256.0);

vec4 premultiply(vec4 c) { return vec4(c.rgb * c.a, c.a); }
vec4 bounded_sample(sampler2D tex, vec2 uv) {
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) {
        return vec4(0.0);
    }
    return premultiply(texture(tex, uv));
}

void fragment() {
    vec4 a = bounded_sample(previous_image, UV);
    vec4 b = bounded_sample(current_image, UV);
    vec4 result = mix(a, b, progress);
    if (use_flow) {
        vec4 f = texture(forward_flow, UV);
        vec4 r = texture(backward_flow, UV);
        vec4 wa = bounded_sample(previous_image, UV - progress * f.xy / image_size);
        vec4 wb = bounded_sample(current_image, UV - (1.0 - progress) * r.xy / image_size);
        float confidence = min(f.z, r.z);
        result = mix(result, mix(wa, wb, progress), confidence);
    }
    ALBEDO = result.rgb / max(result.a, 0.00001);
    ALPHA = result.a;
    ALPHA_SCISSOR_THRESHOLD = 0.015;
}
