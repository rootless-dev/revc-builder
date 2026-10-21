R"wgsl(
// reVC's screenDroplet.frag in WGSL, for librw's WGPU platform.
// Stage 0: the droplet mask; stage 1: the copy of the screen.
@fragment
fn fs_main(in: Im2DOut) -> @location(0) vec4f {
    var color = in.color * sample0(in.tex0);
    color *= sample1(in.tex1);
    return color;
}
)wgsl"
