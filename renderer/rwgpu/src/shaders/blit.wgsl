// Copies the main colour target to the window surface (design §5.1).

@group(0) @binding(0) var source: texture_2d<f32>;
@group(0) @binding(1) var source_sampler: sampler;

struct BlitOut {
    @builtin(position) position: vec4f,
    @location(0) uv: vec2f,
}

@vertex
fn vs_blit(@builtin(vertex_index) index: u32) -> BlitOut {
    let u = f32((index << 1u) & 2u);
    let v = f32(index & 2u);
    var out: BlitOut;
    out.position = vec4f(u * 2.0 - 1.0, 1.0 - v * 2.0, 0.0, 1.0);
    out.uv = vec2f(u, v);
    return out;
}

@fragment
fn fs_blit(in: BlitOut) -> @location(0) vec4f {
    return vec4f(textureSample(source, source_sampler, in.uv).rgb, 1.0);
}
