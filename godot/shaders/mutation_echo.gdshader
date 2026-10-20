shader_type spatial;
render_mode unshaded, depth_draw_never, cull_disabled;
uniform float opacity = .12;
void fragment() {
    float edge = pow(1.0-abs(dot(normalize(NORMAL),normalize(VIEW))),2.0);
    ALBEDO = vec3(.23,.08,.07);
    ALPHA = opacity*(.15+.85*edge);
}
