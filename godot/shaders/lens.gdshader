shader_type canvas_item;
uniform sampler2D screen : hint_screen_texture, repeat_disable, filter_linear;
uniform float strength = 0.65;
void fragment() {
    vec3 color = texture(screen, SCREEN_UV).rgb;
    vec2 p = SCREEN_UV*2.0-1.0;
    float edge = smoothstep(0.25, 1.65, dot(p, p));
    color *= 1.0-edge*0.24*strength;
    float grain = fract(sin(dot(FRAGCOORD.xy+fract(TIME)*127.0, vec2(12.9898,78.233)))*43758.5453)-0.5;
    color += grain*0.008*strength;
    COLOR = vec4(color, 1.0);
}
