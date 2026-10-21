R"wgsl(
// reVC's contrast.frag in WGSL, for librw's WGPU platform.
// param(0).rgb: multiplier, param(1).rgb: offset.
@fragment
fn fs_main(in: Im2DOut) -> @location(0) vec4f {
    let dst = sample0(in.tex0);
    return vec4f(dst.rgb * param(0).rgb + param(1).rgb, 1.0);
}
)wgsl"
