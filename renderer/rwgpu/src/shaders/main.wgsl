// rwgpu shaders. Translated from librw's GLSL shaders (src/gl/shaders: header.vert,
// header.frag, default.vert, skin.vert, matfx_env.vert, matfx_env.frag, im2d.vert,
// im3d.vert, simple.frag), Copyright (c) 2014 aap, MIT licence.
//
// Differences from the GLSL (design §5.5): textures are sampled at (u, v) because every
// texture is top-down; one shader handles all light types, with `light_mask` standing in
// for GL3's DIRECTIONALS/POINTLIGHTS/SPOTLIGHTS variants; the skin shader takes fog from
// GL's clip-space z, as GL3 does.

struct Camera {
    proj: mat4x4f,
    view: mat4x4f,
    // start, end, range = 1 / (start - end), unused
    fog: vec4f,
    // Im2D: screen to NDC scale and offset
    xform: vec4f,
    // GL3's projection depth row: z_gl = x * z_view + y
    gl_depth: vec4f,
}

struct Object {
    world: mat4x4f,
    amb_light: vec4f,
    // type, radius, -cos(angle), hard spot
    light_params: array<vec4f, 8>,
    light_position: array<vec4f, 8>,
    light_direction: array<vec4f, 8>,
    light_color: array<vec4f, 8>,
    tex_matrix: mat4x4f,
}

struct Draw {
    mat_color: vec4f,
    // ambient, specular, diffuse, extra
    surf_props: vec4f,
    // discard when alpha < x or alpha >= y
    alpha_ref: vec4f,
    fog_color: vec4f,
    // fog disabled (1/0), tex0 opaque (1/0), tex1 opaque (1/0), light mask
    flags: vec4f,
    // shininess, disable framebuffer alpha
    fx_params: vec4f,
    color_clamp: vec4f,
    env_color: vec4f,
    params: array<vec4f, 4>,
}

struct Bones {
    m: array<mat4x4f, 64>,
}

@group(0) @binding(0) var<uniform> camera: Camera;
@group(0) @binding(1) var<uniform> object: Object;
@group(0) @binding(2) var<uniform> draw: Draw;
@group(0) @binding(3) var<uniform> bones: Bones;

@group(1) @binding(0) var tex0: texture_2d<f32>;
@group(1) @binding(1) var samp0: sampler;
@group(1) @binding(2) var tex1: texture_2d<f32>;
@group(1) @binding(3) var samp1: sampler;

struct VsOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) tex0: vec2f,
    @location(2) tex1: vec2f,
    @location(3) fog: f32,
    @location(4) env_color: vec4f,
}

fn do_dynamic_light(v: vec3f, n: vec3f) -> vec3f {
    let mask = u32(draw.flags.w);
    var color = vec3f(0.0);
    for (var i = 0; i < 8; i++) {
        let kind = object.light_params[i].x;
        if kind == 0.0 {
            break;
        }
        if kind == 1.0 && (mask & 1u) != 0u {
            let l = max(0.0, dot(n, -object.light_direction[i].xyz));
            color += l * object.light_color[i].rgb;
        } else if kind == 2.0 && (mask & 2u) != 0u {
            let dir = v - object.light_position[i].xyz;
            let dist = length(dir);
            let atten = max(0.0, 1.0 - dist / object.light_params[i].y);
            let l = max(0.0, dot(n, -normalize(dir)));
            color += l * object.light_color[i].rgb * atten;
        } else if kind == 3.0 && (mask & 4u) != 0u {
            var dir = v - object.light_position[i].xyz;
            let dist = length(dir);
            let atten = max(0.0, 1.0 - dist / object.light_params[i].y);
            dir /= dist;
            var l = max(0.0, dot(n, -dir));
            let pcos = dot(dir, object.light_direction[i].xyz);
            let ccos = -object.light_params[i].z;
            let falloff = (pcos - ccos) / (1.0 - ccos);
            if falloff < 0.0 {
                l = 0.0;
            }
            l *= max(falloff, object.light_params[i].w);
            // GL3 returns here, dropping the lights before this one.
            return l * object.light_color[i].rgb * atten;
        }
    }
    return color;
}

fn do_fog(w: f32) -> f32 {
    if draw.flags.x != 0.0 {
        return 1.0;
    }
    return clamp((w - camera.fog.y) * camera.fog.z, 0.0, 1.0);
}

fn lit_color(in_color: vec4f, vertex: vec3f, normal: vec3f) -> vec4f {
    var c = in_color;
    c = vec4f(c.rgb + object.amb_light.rgb * draw.surf_props.x, c.a);
    c = vec4f(c.rgb + do_dynamic_light(vertex, normal) * draw.surf_props.z, c.a);
    return clamp(c, vec4f(0.0), vec4f(1.0));
}

fn upper3(m: mat4x4f) -> mat3x3f {
    return mat3x3f(m[0].xyz, m[1].xyz, m[2].xyz);
}

// --- default (also lit Im3D) ---------------------------------------------------------

@vertex
fn vs_default(
    @location(0) pos: vec3f,
    @location(1) normal: vec3f,
    @location(2) color: vec4f,
    @location(3) uv0: vec2f,
) -> VsOut {
    var out: VsOut;
    let vertex = object.world * vec4f(pos, 1.0);
    out.position = camera.proj * camera.view * vertex;
    let n = upper3(object.world) * normal;
    out.tex0 = uv0;
    out.tex1 = vec2f(0.0);
    out.color = lit_color(color, vertex.xyz, n) * draw.mat_color;
    out.fog = do_fog(out.position.w);
    out.env_color = vec4f(0.0);
    return out;
}

// --- skin --------------------------------------------------------------------------

@vertex
fn vs_skin(
    @location(0) pos: vec3f,
    @location(1) normal: vec3f,
    @location(2) color: vec4f,
    @location(3) uv0: vec2f,
    @location(5) weights: vec4f,
    @location(6) indices: vec4u,
) -> VsOut {
    var out: VsOut;
    var skin_vertex = vec3f(0.0);
    var skin_normal = vec3f(0.0);
    for (var i = 0; i < 4; i++) {
        let m = bones.m[indices[i]];
        skin_vertex += (m * vec4f(pos, 1.0)).xyz * weights[i];
        skin_normal += (upper3(m) * normal) * weights[i];
    }
    let vertex = object.world * vec4f(skin_vertex, 1.0);
    let view_pos = camera.view * vertex;
    out.position = camera.proj * view_pos;
    let n = upper3(object.world) * skin_normal;
    out.tex0 = uv0;
    out.tex1 = vec2f(0.0);
    out.color = lit_color(color, vertex.xyz, n) * draw.mat_color;
    // GL3's skin shader fogs by clip-space z of GL's projection.
    out.fog = do_fog(camera.gl_depth.x * view_pos.z + camera.gl_depth.y * view_pos.w);
    out.env_color = vec4f(0.0);
    return out;
}

// --- matfx environment map -----------------------------------------------------------

@vertex
fn vs_matfx_env(
    @location(0) pos: vec3f,
    @location(1) normal: vec3f,
    @location(2) color: vec4f,
    @location(3) uv0: vec2f,
) -> VsOut {
    var out: VsOut;
    let vertex = object.world * vec4f(pos, 1.0);
    out.position = camera.proj * camera.view * vertex;
    let n = upper3(object.world) * normal;
    out.tex0 = uv0;
    out.tex1 = (object.tex_matrix * vec4f(n, 1.0)).xy;
    let c = lit_color(color, vertex.xyz, n);
    out.env_color = max(c, draw.color_clamp) * draw.env_color;
    out.color = c * draw.mat_color;
    out.fog = do_fog(out.position.w);
    return out;
}

// --- Im3D ------------------------------------------------------------------------------

@vertex
fn vs_im3d(
    @location(0) pos: vec3f,
    @location(2) color: vec4f,
    @location(3) uv0: vec2f,
) -> VsOut {
    var out: VsOut;
    let vertex = object.world * vec4f(pos, 1.0);
    out.position = camera.proj * camera.view * vertex;
    out.color = color;
    out.tex0 = uv0;
    out.tex1 = vec2f(0.0);
    out.fog = do_fog(out.position.w);
    out.env_color = vec4f(0.0);
    return out;
}

// --- Im2D --------------------------------------------------------------------------------

fn im2d_position(pos: vec4f) -> vec4f {
    let xy = pos.xy * camera.xform.xy + camera.xform.zw;
    return vec4f(xy * pos.w, pos.z * pos.w, pos.w);
}

@vertex
fn vs_im2d(
    @location(0) pos: vec4f,
    @location(2) color: vec4f,
    @location(3) uv0: vec2f,
) -> VsOut {
    var out: VsOut;
    out.position = im2d_position(pos);
    out.fog = do_fog(pos.w);
    out.color = color;
    out.tex0 = uv0;
    out.tex1 = vec2f(0.0);
    out.env_color = vec4f(0.0);
    return out;
}

@vertex
fn vs_im2d_uv2(
    @location(0) pos: vec4f,
    @location(2) color: vec4f,
    @location(3) uv0: vec2f,
    @location(4) uv1: vec2f,
) -> VsOut {
    var out: VsOut;
    out.position = im2d_position(pos);
    out.fog = do_fog(pos.w);
    out.color = color;
    out.tex0 = uv0;
    out.tex1 = uv1;
    out.env_color = vec4f(0.0);
    return out;
}

// --- fragment stages ---------------------------------------------------------------------

fn sample0(uv: vec2f) -> vec4f {
    let t = textureSample(tex0, samp0, uv);
    return select(t, vec4f(t.rgb, 1.0), draw.flags.y != 0.0);
}

fn sample1(uv: vec2f) -> vec4f {
    let t = textureSample(tex1, samp1, uv);
    return select(t, vec4f(t.rgb, 1.0), draw.flags.z != 0.0);
}

fn alpha_test(a: f32) {
    if a < draw.alpha_ref.x || a >= draw.alpha_ref.y {
        discard;
    }
}

@fragment
fn fs_simple(in: VsOut) -> @location(0) vec4f {
    var color = in.color * sample0(in.tex0);
    color = vec4f(mix(draw.fog_color.rgb, color.rgb, in.fog), color.a);
    alpha_test(color.a);
    return color;
}

@fragment
fn fs_matfx_env(in: VsOut) -> @location(0) vec4f {
    var pass1 = in.color * sample0(in.tex0);
    var pass2 = in.env_color * draw.fx_params.x * sample1(in.tex1);
    pass1 = vec4f(mix(draw.fog_color.rgb, pass1.rgb, in.fog), pass1.a);
    pass2 = vec4f(mix(vec3f(0.0), pass2.rgb, in.fog), pass2.a);
    let fba = max(pass1.a, draw.fx_params.y);
    let color = vec4f(pass1.rgb * pass1.a + pass2.rgb * fba, pass1.a);
    alpha_test(color.a);
    return color;
}

// --- clears ----------------------------------------------------------------------------------

struct ClearOut {
    @builtin(position) position: vec4f,
}

@vertex
fn vs_clear(@builtin(vertex_index) index: u32) -> ClearOut {
    // One triangle covering the viewport, at depth 1.
    let x = f32((index << 1u) & 2u) * 2.0 - 1.0;
    let y = f32(index & 2u) * 2.0 - 1.0;
    var out: ClearOut;
    out.position = vec4f(x, y, 1.0, 1.0);
    return out;
}

@fragment
fn fs_clear() -> @location(0) vec4f {
    return draw.params[0];
}
