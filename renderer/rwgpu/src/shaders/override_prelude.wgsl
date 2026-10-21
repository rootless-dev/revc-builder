// Prepended to every Im2D override fragment shader (design §4.3). The caller provides
// `fn fs_main(in: Im2DOut) -> @location(0) vec4f`; it may use `param(i)` (the 16 floats of
// rwgpu_im2d_set_override as four vec4f) and `sample0`/`sample1`.

struct Im2DOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) tex0: vec2f,
    @location(2) tex1: vec2f,
    @location(3) fog: f32,
}

struct OverrideDraw {
    mat_color: vec4f,
    surf_props: vec4f,
    alpha_ref: vec4f,
    fog_color: vec4f,
    flags: vec4f,
    fx_params: vec4f,
    color_clamp: vec4f,
    env_color: vec4f,
    params: array<vec4f, 4>,
}

@group(0) @binding(2) var<uniform> override_draw: OverrideDraw;

@group(1) @binding(0) var tex0: texture_2d<f32>;
@group(1) @binding(1) var samp0: sampler;
@group(1) @binding(2) var tex1: texture_2d<f32>;
@group(1) @binding(3) var samp1: sampler;

fn param(i: i32) -> vec4f {
    return override_draw.params[i];
}

// Samples stage 0 / 1 as the built-in shaders do: alpha is 1 for rasters without alpha.
fn sample0(uv: vec2f) -> vec4f {
    let t = textureSample(tex0, samp0, uv);
    return select(t, vec4f(t.rgb, 1.0), override_draw.flags.y != 0.0);
}

fn sample1(uv: vec2f) -> vec4f {
    let t = textureSample(tex1, samp1, uv);
    return select(t, vec4f(t.rgb, 1.0), override_draw.flags.z != 0.0);
}
