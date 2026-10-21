R"wgsl(
// reVC's colourfilterVC.frag in WGSL, for librw's WGPU platform.
// param(0): blur colour (rgb scaled by the intensity, a = 30/255).
@fragment
fn fs_main(in: Im2DOut) -> @location(0) vec4f {
    let blur = param(0);
    let a = blur.a;
    let doublec = clamp(blur * 2.0, vec4f(0.0), vec4f(1.0));
    let dst = sample0(in.tex0);
    var prev = dst;
    for (var i = 0; i < 5; i++) {
        var tmp = dst * (1.0 - a) + prev * doublec * a;
        tmp += prev * blur;
        tmp += prev * blur;
        prev = clamp(tmp, vec4f(0.0), vec4f(1.0));
    }
    return vec4f(prev.rgb, 1.0);
}
)wgsl"
