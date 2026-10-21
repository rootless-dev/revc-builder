//! The wgpu device, targets, resources and draw submission (design §5).

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

use bytemuck::{Pod, Zeroable};
use wgpu::util::DeviceExt;

use crate::abi::*;
use crate::convert;
use crate::dump::{DumpConfig, FrameStats, write_png};
use crate::pipeline::*;
use crate::shaders;
use crate::state::{GsPass, RenderState};

// --- uniform blocks (layouts match shaders/main.wgsl) -----------------------------------

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct CameraBlock {
    pub proj: [f32; 16],
    pub view: [f32; 16],
    pub fog: [f32; 4],
    pub xform: [f32; 4],
    pub gl_depth: [f32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct ObjectBlock {
    pub world: [f32; 16],
    pub amb_light: [f32; 4],
    pub light_params: [[f32; 4]; MAX_LIGHTS],
    pub light_position: [[f32; 4]; MAX_LIGHTS],
    pub light_direction: [[f32; 4]; MAX_LIGHTS],
    pub light_color: [[f32; 4]; MAX_LIGHTS],
    pub tex_matrix: [f32; 16],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct DrawBlock {
    pub mat_color: [f32; 4],
    pub surf_props: [f32; 4],
    pub alpha_ref: [f32; 4],
    pub fog_color: [f32; 4],
    pub flags: [f32; 4],
    pub fx_params: [f32; 4],
    pub color_clamp: [f32; 4],
    pub env_color: [f32; 4],
    pub params: [[f32; 4]; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct BonesBlock {
    pub m: [[f32; 16]; MAX_BONES],
}

const IDENTITY: [f32; 16] = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.];

/// GL3 compiles three light types into its lit shaders.
const ALL_LIGHTS: f32 = 7.0;

// --- arenas ---------------------------------------------------------------------------------

/// A per-submission buffer filled through a CPU staging copy (design §5.4).
struct Arena {
    buffer: wgpu::Buffer,
    staging: Vec<u8>,
    usage: wgpu::BufferUsages,
    label: &'static str,
}

impl Arena {
    fn new(device: &wgpu::Device, label: &'static str, size: u64, usage: wgpu::BufferUsages) -> Self {
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(label),
            size,
            usage: usage | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Arena {
            buffer,
            staging: Vec::with_capacity(size as usize),
            usage,
            label,
        }
    }

    fn capacity(&self) -> u64 {
        self.buffer.size()
    }

    fn fits(&self, len: u64, align: u64) -> bool {
        (self.staging.len() as u64).next_multiple_of(align) + len <= self.capacity()
    }

    /// Appends `data` (padded to 4 bytes) at an `align`ed offset; the caller checked `fits`.
    fn push(&mut self, data: &[u8], align: u64) -> u64 {
        let offset = (self.staging.len() as u64).next_multiple_of(align);
        self.staging.resize(offset as usize, 0);
        self.staging.extend_from_slice(&convert::pad4(data));
        offset
    }

    fn grow(&mut self, device: &wgpu::Device, at_least: u64) {
        *self = Arena::new(device, self.label, at_least.next_power_of_two() * 2, self.usage);
    }

    fn flush(&mut self, queue: &wgpu::Queue) {
        if !self.staging.is_empty() {
            queue.write_buffer(&self.buffer, 0, &self.staging);
            self.staging.clear();
        }
    }
}

// --- resources ------------------------------------------------------------------------------

struct Texture {
    texture: wgpu::Texture,
    view: wgpu::TextureView,
    format: u32,
    width: u32,
    height: u32,
    levels: u32,
    flags: u32,
    /// Submission epoch of the last command that used this texture.
    used: u64,
}

struct Depth {
    width: u32,
    height: u32,
    texture: Option<(wgpu::Texture, wgpu::TextureView)>,
    used: u64,
}

struct Mesh {
    vertex: wgpu::Buffer,
    index: wgpu::Buffer,
    layout: Layout,
}

/// Handle table: handles are index + 1; 0 is "none".
struct Slab<T> {
    items: Vec<Option<T>>,
    free: Vec<usize>,
}

impl<T> Slab<T> {
    fn new() -> Self {
        Slab {
            items: Vec::new(),
            free: Vec::new(),
        }
    }
    fn insert(&mut self, value: T) -> u32 {
        if let Some(i) = self.free.pop() {
            self.items[i] = Some(value);
            i as u32 + 1
        } else {
            self.items.push(Some(value));
            self.items.len() as u32
        }
    }
    fn get(&self, handle: u32) -> Option<&T> {
        self.items.get((handle as usize).checked_sub(1)?)?.as_ref()
    }
    fn get_mut(&mut self, handle: u32) -> Option<&mut T> {
        self.items.get_mut((handle as usize).checked_sub(1)?)?.as_mut()
    }
    fn remove(&mut self, handle: u32) -> Option<T> {
        let i = (handle as usize).checked_sub(1)?;
        let value = self.items.get_mut(i)?.take();
        if value.is_some() {
            self.free.push(i);
        }
        value
    }
    fn len(&self) -> usize {
        self.items.len() - self.free.len()
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
struct TextureBindKey {
    tex0: u32,
    samp0: SamplerKey,
    tex1: u32,
    samp1: SamplerKey,
}

enum VertexSource {
    Mesh(u32),
    Arena { offset: u64, len: u64 },
    None,
}

enum IndexSource {
    Mesh { first: u32 },
    Arena { offset: u64, len: u64 },
}

struct Im3D {
    offset: u64,
    epoch: u64,
    vertices: Vec<u8>,
    count: u32,
    lit: bool,
}

struct DrawCall {
    vertex_stage: VertexStage,
    fragment_stage: FragmentStage,
    layout: Layout,
    topology: wgpu::PrimitiveTopology,
    vertices: VertexSource,
    indices: Option<IndexSource>,
    count: u32,
}

/// Uniform block offsets in the uniform arena; `None` means "append before the next draw".
#[derive(Default)]
struct UniformOffsets {
    camera: Option<u64>,
    object: Option<u64>,
    draw: Option<u64>,
    bones: Option<u64>,
}

pub struct Renderer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    surface: wgpu::Surface<'static>,
    surface_config: wgpu::SurfaceConfiguration,
    bc_supported: bool,
    border_supported: bool,
    max_anisotropy: f32,
    max_texture_size: u32,
    uniform_align: u64,

    main: (wgpu::Texture, wgpu::TextureView),
    main_size: (u32, u32),

    textures: Slab<Texture>,
    depths: Slab<Depth>,
    meshes: Slab<Mesh>,
    overrides: Vec<wgpu::ShaderModule>,

    main_module: wgpu::ShaderModule,
    texture_layout: wgpu::BindGroupLayout,
    pipeline_layout: wgpu::PipelineLayout,
    pipelines: HashMap<PipelineKey, wgpu::RenderPipeline>,
    samplers: HashMap<SamplerKey, wgpu::Sampler>,
    texture_bind_groups: HashMap<TextureBindKey, wgpu::BindGroup>,
    white: (wgpu::Texture, wgpu::TextureView),
    blit_layout: wgpu::BindGroupLayout,
    blit_pipeline: wgpu::RenderPipeline,
    blit_sampler: wgpu::Sampler,

    pub state: RenderState,
    camera: CameraBlock,
    object: ObjectBlock,
    draw: DrawBlock,
    bones: BonesBlock,
    offsets: UniformOffsets,

    uniforms: Arena,
    vertices: Arena,
    indices: Arena,
    uniform_bind_group: wgpu::BindGroup,

    encoder: Option<wgpu::CommandEncoder>,
    pass: Option<wgpu::RenderPass<'static>>,
    bound_pipeline: Option<PipelineKey>,
    target: RwgpuTarget,
    epoch: u64,

    /// Transformed Im3D vertices: arena offset, the submission epoch it is valid in, a copy
    /// to push again after an arena restart, vertex count and lighting.
    im3d: Option<Im3D>,
    im2d_override: u32,

    dump: DumpConfig,
    stats: FrameStats,
    vsync: bool,
    present_modes: Vec<wgpu::PresentMode>,
    validation_errors: Arc<AtomicU64>,
}

const UNIFORM_ARENA: u64 = 8 << 20;
const VERTEX_ARENA: u64 = 8 << 20;
const INDEX_ARENA: u64 = 2 << 20;

fn block_size<T>() -> u64 {
    std::mem::size_of::<T>() as u64
}

impl Renderer {
    /// # Safety
    /// `desc.handle[0]` must be a valid `NSView*` that outlives the renderer.
    pub unsafe fn new(desc: &RwgpuWindowDesc) -> Result<Self, String> {
        if desc.kind != WINDOW_APPKIT {
            return Err(format!("unsupported window kind {}", desc.kind));
        }
        let view = std::ptr::NonNull::new(desc.handle[0]).ok_or("the window handle is null")?;
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::PRIMARY,
            ..wgpu::InstanceDescriptor::new_without_display_handle()
        });
        let target = wgpu::SurfaceTargetUnsafe::RawHandle {
            raw_display_handle: Some(raw_window_handle::RawDisplayHandle::AppKit(
                raw_window_handle::AppKitDisplayHandle::new(),
            )),
            raw_window_handle: raw_window_handle::RawWindowHandle::AppKit(raw_window_handle::AppKitWindowHandle::new(
                view,
            )),
        };
        let surface = unsafe { instance.create_surface_unsafe(target) }.map_err(|e| e.to_string())?;
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: Some(&surface),
            ..Default::default()
        }))
        .map_err(|e| e.to_string())?;
        let available = adapter.features();
        let wanted = wgpu::Features::TEXTURE_COMPRESSION_BC | wgpu::Features::ADDRESS_MODE_CLAMP_TO_BORDER;
        let features = available & wanted;
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("rwgpu"),
            required_features: features,
            required_limits: adapter.limits(),
            ..Default::default()
        }))
        .map_err(|e| e.to_string())?;
        let info = adapter.get_info();
        eprintln!(
            "rwgpu: {} ({:?}), BC textures: {}",
            info.name,
            info.backend,
            features.contains(wgpu::Features::TEXTURE_COMPRESSION_BC)
        );

        let validation_errors = Arc::new(AtomicU64::new(0));
        let counter = validation_errors.clone();
        device.on_uncaptured_error(Arc::new(move |error: wgpu::Error| {
            let n = counter.fetch_add(1, Ordering::Relaxed);
            if n < 20 {
                eprintln!("rwgpu: wgpu error: {error}");
            }
        }));

        let caps = surface.get_capabilities(&adapter);
        let format = [wgpu::TextureFormat::Bgra8Unorm, wgpu::TextureFormat::Rgba8Unorm]
            .into_iter()
            .find(|f| caps.formats.contains(f))
            .unwrap_or(caps.formats[0].remove_srgb_suffix());
        let width = desc.width.max(1);
        let height = desc.height.max(1);
        let surface_config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            width,
            height,
            present_mode: present_mode(desc.vsync != 0, &caps.present_modes),
            desired_maximum_frame_latency: 2,
            alpha_mode: wgpu::CompositeAlphaMode::Opaque,
            view_formats: vec![],
            color_space: wgpu::SurfaceColorSpace::Auto,
        };
        surface.configure(&device, &surface_config);

        let main_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("rwgpu main"),
            source: wgpu::ShaderSource::Wgsl(shaders::MAIN.into()),
        });
        let uniform_entry = |binding: u32, size: u64| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: true,
                min_binding_size: wgpu::BufferSize::new(size),
            },
            count: None,
        };
        let uniform_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("rwgpu uniforms"),
            entries: &[
                uniform_entry(0, block_size::<CameraBlock>()),
                uniform_entry(1, block_size::<ObjectBlock>()),
                uniform_entry(2, block_size::<DrawBlock>()),
                uniform_entry(3, block_size::<BonesBlock>()),
            ],
        });
        let texture_entry = |binding: u32| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Texture {
                sample_type: wgpu::TextureSampleType::Float { filterable: true },
                view_dimension: wgpu::TextureViewDimension::D2,
                multisampled: false,
            },
            count: None,
        };
        let sampler_entry = |binding: u32| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
            count: None,
        };
        let texture_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("rwgpu textures"),
            entries: &[texture_entry(0), sampler_entry(1), texture_entry(2), sampler_entry(3)],
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("rwgpu"),
            bind_group_layouts: &[Some(&uniform_layout), Some(&texture_layout)],
            immediate_size: 0,
        });

        let white = Self::make_texture(&device, wgpu::TextureFormat::Rgba8Unorm, 1, 1, 1, false, "rwgpu white");
        queue.write_texture(
            white.0.as_image_copy(),
            &[255, 255, 255, 255],
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(4),
                rows_per_image: None,
            },
            wgpu::Extent3d {
                width: 1,
                height: 1,
                depth_or_array_layers: 1,
            },
        );

        let blit_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("rwgpu blit"),
            source: wgpu::ShaderSource::Wgsl(shaders::BLIT.into()),
        });
        let blit_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("rwgpu blit"),
            entries: &[texture_entry(0), sampler_entry(1)],
        });
        let blit_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("rwgpu blit"),
            bind_group_layouts: &[Some(&blit_layout)],
            immediate_size: 0,
        });
        let blit_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("rwgpu blit"),
            layout: Some(&blit_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &blit_module,
                entry_point: Some("vs_blit"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            fragment: Some(wgpu::FragmentState {
                module: &blit_module,
                entry_point: Some("fs_blit"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            multiview_mask: None,
            cache: None,
        });
        let blit_sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("rwgpu blit"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });

        let limits = device.limits();
        let uniform_align = limits.min_uniform_buffer_offset_alignment.max(16) as u64;
        let uniforms = Arena::new(&device, "rwgpu uniforms", UNIFORM_ARENA, wgpu::BufferUsages::UNIFORM);
        let vertices = Arena::new(&device, "rwgpu vertices", VERTEX_ARENA, wgpu::BufferUsages::VERTEX);
        let indices = Arena::new(&device, "rwgpu indices", INDEX_ARENA, wgpu::BufferUsages::INDEX);
        let uniform_bind_group = Self::make_uniform_bind_group(&device, &uniform_layout, &uniforms.buffer);
        let main = Self::make_texture(&device, COLOR_FORMAT, width, height, 1, true, "rwgpu main");

        let dump = DumpConfig::from_env();
        let stats = FrameStats::new(dump.stats_every);
        let mut draw = DrawBlock::zeroed();
        draw.mat_color = [1.0; 4];
        draw.flags = [1.0, 0.0, 0.0, ALL_LIGHTS];
        let mut object = ObjectBlock::zeroed();
        object.world = IDENTITY;
        object.tex_matrix = IDENTITY;
        let mut camera = CameraBlock::zeroed();
        camera.proj = IDENTITY;
        camera.view = IDENTITY;
        Ok(Renderer {
            bc_supported: features.contains(wgpu::Features::TEXTURE_COMPRESSION_BC),
            border_supported: features.contains(wgpu::Features::ADDRESS_MODE_CLAMP_TO_BORDER),
            max_anisotropy: 16.0,
            max_texture_size: limits.max_texture_dimension_2d,
            uniform_align,
            device,
            queue,
            surface,
            surface_config,
            main,
            main_size: (width, height),
            textures: Slab::new(),
            depths: Slab::new(),
            meshes: Slab::new(),
            overrides: Vec::new(),
            main_module,
            texture_layout,
            pipeline_layout,
            pipelines: HashMap::new(),
            samplers: HashMap::new(),
            texture_bind_groups: HashMap::new(),
            white,
            blit_layout,
            blit_pipeline,
            blit_sampler,
            state: RenderState::default(),
            camera,
            object,
            draw,
            bones: BonesBlock {
                m: [IDENTITY; MAX_BONES],
            },
            offsets: UniformOffsets::default(),
            uniforms,
            vertices,
            indices,
            uniform_bind_group,
            encoder: None,
            pass: None,
            bound_pipeline: None,
            target: RwgpuTarget {
                color: 0,
                depth: 0,
                x: 0,
                y: 0,
                w: width as i32,
                h: height as i32,
            },
            epoch: 1,
            im3d: None,
            im2d_override: 0,
            dump,
            stats,
            vsync: desc.vsync != 0,
            present_modes: caps.present_modes.clone(),
            validation_errors,
        })
    }

    fn make_texture(
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        width: u32,
        height: u32,
        levels: u32,
        render_target: bool,
        label: &str,
    ) -> (wgpu::Texture, wgpu::TextureView) {
        let mut usage =
            wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST | wgpu::TextureUsages::COPY_SRC;
        if render_target {
            usage |= wgpu::TextureUsages::RENDER_ATTACHMENT;
        }
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some(label),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: levels,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage,
            view_formats: &[],
        });
        let view = texture.create_view(&Default::default());
        (texture, view)
    }

    fn make_uniform_bind_group(
        device: &wgpu::Device,
        layout: &wgpu::BindGroupLayout,
        buffer: &wgpu::Buffer,
    ) -> wgpu::BindGroup {
        let entry = |binding: u32, size: u64| wgpu::BindGroupEntry {
            binding,
            resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                buffer,
                offset: 0,
                size: wgpu::BufferSize::new(size),
            }),
        };
        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("rwgpu uniforms"),
            layout,
            entries: &[
                entry(0, block_size::<CameraBlock>()),
                entry(1, block_size::<ObjectBlock>()),
                entry(2, block_size::<DrawBlock>()),
                entry(3, block_size::<BonesBlock>()),
            ],
        })
    }

    // --- information ---------------------------------------------------------------------

    pub fn caps(&self) -> RwgpuCaps {
        RwgpuCaps {
            bc_supported: self.bc_supported as u32,
            max_anisotropy: self.max_anisotropy,
            max_texture_size: self.max_texture_size,
            reserved: 0,
        }
    }

    pub fn stats(&self) -> RwgpuStats {
        RwgpuStats {
            frames: self.stats.frames(),
            validation_errors: self.validation_errors.load(Ordering::Relaxed),
            pipelines: self.pipelines.len() as u32,
            textures: self.textures.len() as u32,
            meshes: self.meshes.len() as u32,
            reserved: 0,
        }
    }

    // --- submission -----------------------------------------------------------------------

    fn encoder(&mut self) -> &mut wgpu::CommandEncoder {
        self.encoder.get_or_insert_with(|| {
            self.device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("rwgpu") })
        })
    }

    fn end_pass(&mut self) {
        self.pass = None;
        self.bound_pipeline = None;
    }

    /// Submits everything recorded so far; the arenas then start again (design §5.4).
    fn submit(&mut self) {
        self.end_pass();
        self.uniforms.flush(&self.queue);
        self.vertices.flush(&self.queue);
        self.indices.flush(&self.queue);
        if let Some(encoder) = self.encoder.take() {
            self.queue.submit([encoder.finish()]);
        }
        self.epoch += 1;
        self.offsets = UniformOffsets::default();
    }

    /// Makes room for one draw: four uniform blocks plus `vertex_bytes` and `index_bytes`.
    fn reserve(&mut self, vertex_bytes: u64, index_bytes: u64) {
        let uniform_bytes = (block_size::<CameraBlock>()
            + block_size::<ObjectBlock>()
            + block_size::<DrawBlock>()
            + block_size::<BonesBlock>())
            + 4 * self.uniform_align;
        let fits = self.uniforms.fits(uniform_bytes, self.uniform_align)
            && self.vertices.fits(vertex_bytes, 4)
            && self.indices.fits(index_bytes, 4);
        if fits {
            return;
        }
        self.submit();
        if vertex_bytes > self.vertices.capacity() {
            self.vertices.grow(&self.device, vertex_bytes);
        }
        if index_bytes > self.indices.capacity() {
            self.indices.grow(&self.device, index_bytes);
        }
    }

    // --- targets ------------------------------------------------------------------------------

    fn color_target(&self, color: u32) -> Option<(wgpu::TextureView, u32, u32)> {
        if color == 0 {
            return Some((self.main.1.clone(), self.main_size.0, self.main_size.1));
        }
        let t = self.textures.get(color)?;
        (t.flags & TEXTURE_RENDER_TARGET != 0).then(|| (t.view.clone(), t.width, t.height))
    }

    /// The depth view for a target of `width`×`height`, recreating the texture on a size change.
    fn depth_target(&mut self, depth: u32, width: u32, height: u32) -> Option<wgpu::TextureView> {
        let device = &self.device;
        let epoch = self.epoch;
        let d = self.depths.get_mut(depth)?;
        if d.texture.is_none() || d.width != width || d.height != height {
            let texture = device.create_texture(&wgpu::TextureDescriptor {
                label: Some("rwgpu depth"),
                size: wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: DEPTH_FORMAT,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                view_formats: &[],
            });
            let view = texture.create_view(&Default::default());
            d.texture = Some((texture, view));
            d.width = width;
            d.height = height;
        }
        d.used = epoch;
        d.texture.as_ref().map(|(_, v)| v.clone())
    }

    fn begin_pass(
        &mut self,
        color_load: wgpu::LoadOp<wgpu::Color>,
        depth_load: wgpu::LoadOp<f32>,
        stencil_load: wgpu::LoadOp<u32>,
    ) -> bool {
        self.end_pass();
        let target = self.target;
        let Some((color_view, width, height)) = self.color_target(target.color) else {
            return false;
        };
        let depth_view = if target.depth != 0 {
            self.depth_target(target.depth, width, height)
        } else {
            None
        };
        if let Some(t) = self.textures.get_mut(target.color) {
            t.used = self.epoch;
        }
        let encoder = self.encoder();
        let pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("rwgpu"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &color_view,
                resolve_target: None,
                depth_slice: None,
                ops: wgpu::Operations {
                    load: color_load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: depth_view.as_ref().map(|view| wgpu::RenderPassDepthStencilAttachment {
                view,
                depth_ops: Some(wgpu::Operations {
                    load: depth_load,
                    store: wgpu::StoreOp::Store,
                }),
                stencil_ops: Some(wgpu::Operations {
                    load: stencil_load,
                    store: wgpu::StoreOp::Store,
                }),
            }),
            timestamp_writes: None,
            occlusion_query_set: None,
            multiview_mask: None,
        });
        let mut pass = pass.forget_lifetime();
        let (x, y, w, h) = clamp_viewport(&target, width, height);
        if w > 0.0 && h > 0.0 {
            pass.set_viewport(x, y, w, h, 0.0, 1.0);
        }
        pass.set_stencil_reference(self.state.stencil().reference);
        self.pass = Some(pass);
        true
    }

    fn ensure_pass(&mut self) -> bool {
        if self.pass.is_some() {
            return true;
        }
        self.begin_pass(wgpu::LoadOp::Load, wgpu::LoadOp::Load, wgpu::LoadOp::Load)
    }

    fn target_has_depth(&self) -> bool {
        self.target.depth != 0 && self.depths.get(self.target.depth).is_some()
    }

    fn target_format(&self) -> wgpu::TextureFormat {
        COLOR_FORMAT
    }

    pub fn begin_camera(
        &mut self,
        target: &RwgpuTarget,
        view: &[f32; 16],
        proj: &[f32; 16],
        fog_start: f32,
        fog_end: f32,
        gl_depth: [f32; 2],
    ) {
        self.camera.view = *view;
        self.camera.proj = *proj;
        let range = if fog_start != fog_end {
            1.0 / (fog_start - fog_end)
        } else {
            0.0
        };
        self.camera.fog = [fog_start, fog_end, range, 0.0];
        let (w, h) = (target.w.max(1) as f32, target.h.max(1) as f32);
        self.camera.xform = [2.0 / w, -2.0 / h, -1.0, 1.0];
        self.camera.gl_depth = [gl_depth[0], gl_depth[1], 0.0, 0.0];
        self.offsets.camera = None;
        self.set_target(target);
    }

    pub fn end_camera(&mut self) {}

    fn set_target(&mut self, target: &RwgpuTarget) {
        if *target != self.target {
            self.end_pass();
            self.target = *target;
        }
    }

    pub fn clear(&mut self, target: &RwgpuTarget, rgba: [f32; 4], mode: u32) {
        self.set_target(target);
        let Some((_, width, height)) = self.color_target(target.color) else {
            return;
        };
        let full = target.x <= 0
            && target.y <= 0
            && target.x + target.w >= width as i32
            && target.y + target.h >= height as i32;
        if full {
            let color = if mode & CLEARIMAGE != 0 {
                wgpu::LoadOp::Clear(wgpu::Color {
                    r: rgba[0] as f64,
                    g: rgba[1] as f64,
                    b: rgba[2] as f64,
                    a: rgba[3] as f64,
                })
            } else {
                wgpu::LoadOp::Load
            };
            let depth = if mode & CLEARZ != 0 {
                wgpu::LoadOp::Clear(1.0)
            } else {
                wgpu::LoadOp::Load
            };
            let stencil = if mode & CLEARSTENCIL != 0 {
                wgpu::LoadOp::Clear(0)
            } else {
                wgpu::LoadOp::Load
            };
            self.begin_pass(color, depth, stencil);
            return;
        }
        // A subraster: draw a quad inside the viewport.
        self.reserve(0, 0);
        if !self.ensure_pass() {
            return;
        }
        let saved = self.draw.params[0];
        self.draw.params[0] = rgba;
        self.offsets.draw = None;
        let depth = self.target_has_depth().then(|| DepthKey {
            compare: wgpu::CompareFunction::Always,
            write: mode & CLEARZ != 0,
            stencil: (mode & CLEARSTENCIL != 0).then_some((
                STENCILREPLACE,
                STENCILREPLACE,
                STENCILREPLACE,
                STENCILALWAYS,
                !0,
                !0,
            )),
        });
        let key = PipelineKey {
            vertex: VertexStage::Clear,
            fragment: FragmentStage::Clear,
            layout: Layout::None,
            topology: wgpu::PrimitiveTopology::TriangleList,
            blend: None,
            depth,
            cull: CULLNONE,
            color_write: mode & CLEARIMAGE != 0,
            color_format: self.target_format(),
        };
        if let Some(pass) = self.pass.as_mut() {
            pass.set_stencil_reference(0);
        }
        self.issue(
            &key,
            &DrawCall {
                vertex_stage: VertexStage::Clear,
                fragment_stage: FragmentStage::Clear,
                layout: Layout::None,
                topology: wgpu::PrimitiveTopology::TriangleList,
                vertices: VertexSource::None,
                indices: None,
                count: 3,
            },
        );
        let reference = self.state.stencil().reference;
        if let Some(pass) = self.pass.as_mut() {
            pass.set_stencil_reference(reference);
        }
        self.draw.params[0] = saved;
        self.offsets.draw = None;
    }

    pub fn resize(&mut self, width: u32, height: u32) {
        let (width, height) = (width.max(1), height.max(1));
        if (width, height) == self.main_size {
            return;
        }
        self.submit();
        self.main = Self::make_texture(&self.device, COLOR_FORMAT, width, height, 1, true, "rwgpu main");
        self.main_size = (width, height);
        self.surface_config.width = width;
        self.surface_config.height = height;
        self.surface.configure(&self.device, &self.surface_config);
    }

    pub fn copy_main_to_texture(&mut self, tex: u32, dst_x: i32, dst_y: i32, w: u32, h: u32) {
        let Some(t) = self.textures.get(tex) else { return };
        if t.format != FORMAT_RGBA8 {
            return;
        }
        let (dx, dy) = (dst_x.max(0) as u32, dst_y.max(0) as u32);
        let w = w.min(self.main_size.0).min(t.width.saturating_sub(dx));
        let h = h.min(self.main_size.1).min(t.height.saturating_sub(dy));
        if w == 0 || h == 0 {
            return;
        }
        let dst = t.texture.clone();
        self.end_pass();
        if let Some(t) = self.textures.get_mut(tex) {
            t.used = self.epoch;
        }
        let src = self.main.0.clone();
        self.encoder().copy_texture_to_texture(
            src.as_image_copy(),
            wgpu::TexelCopyTextureInfo {
                texture: &dst,
                mip_level: 0,
                origin: wgpu::Origin3d { x: dx, y: dy, z: 0 },
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
        );
    }

    /// Reads the main target as top-down RGB8 (`rwgpu_read_main`).
    pub fn read_main(&mut self) -> (u32, u32, Vec<u8>) {
        self.submit();
        let (w, h) = self.main_size;
        let rgba = self.read_texture_rgba(&self.main.0.clone(), 0, w, h, FORMAT_RGBA8);
        (w, h, convert::rgba8_to_rgb8(&rgba))
    }

    /// Blocking readback of one level, tightly packed (rows of pixels or of blocks).
    fn read_texture_rgba(
        &mut self,
        texture: &wgpu::Texture,
        level: u32,
        width: u32,
        height: u32,
        format: u32,
    ) -> Vec<u8> {
        let (row_bytes, rows) = convert::level_layout(format, width, height);
        let padded = row_bytes.next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("rwgpu readback"),
            size: (padded * rows) as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let (cw, ch) = if convert::block_bytes(format).is_some() {
            (width.div_ceil(4) * 4, height.div_ceil(4) * 4)
        } else {
            (width, height)
        };
        let mut encoder = self.device.create_command_encoder(&Default::default());
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture,
                mip_level: level,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(padded),
                    rows_per_image: Some(rows),
                },
            },
            wgpu::Extent3d {
                width: cw,
                height: ch,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit([encoder.finish()]);
        map_and_read(&self.device, &buffer, row_bytes, padded, rows)
    }

    // --- textures ---------------------------------------------------------------------------

    pub fn texture_create(&mut self, format: u32, width: u32, height: u32, levels: u32, flags: u32) -> u32 {
        let wgpu_format = match format {
            FORMAT_RGBA8 => wgpu::TextureFormat::Rgba8Unorm,
            FORMAT_BC1 if self.bc_supported => wgpu::TextureFormat::Bc1RgbaUnorm,
            FORMAT_BC2 if self.bc_supported => wgpu::TextureFormat::Bc2RgbaUnorm,
            FORMAT_BC3 if self.bc_supported => wgpu::TextureFormat::Bc3RgbaUnorm,
            _ => return 0,
        };
        if width == 0 || height == 0 || width > self.max_texture_size || height > self.max_texture_size {
            return 0;
        }
        if convert::block_bytes(format).is_some() && (!width.is_multiple_of(4) || !height.is_multiple_of(4)) {
            return 0;
        }
        if format != FORMAT_RGBA8 && flags & TEXTURE_RENDER_TARGET != 0 {
            return 0;
        }
        let levels = levels.clamp(1, convert::full_chain_levels(width, height));
        let render_target = flags & TEXTURE_RENDER_TARGET != 0;
        let (texture, view) = Self::make_texture(
            &self.device,
            wgpu_format,
            width,
            height,
            levels,
            render_target,
            "rwgpu texture",
        );
        self.textures.insert(Texture {
            texture,
            view,
            format,
            width,
            height,
            levels,
            flags,
            used: 0,
        })
    }

    pub fn texture_destroy(&mut self, tex: u32) {
        if self.textures.remove(tex).is_some() {
            self.texture_bind_groups.retain(|k, _| k.tex0 != tex && k.tex1 != tex);
            self.state.forget_texture(tex);
        }
    }

    pub fn texture_upload(&mut self, tex: u32, level: u32, src_format: u32, data: &[u8]) -> bool {
        let Some(t) = self.textures.get(tex) else { return false };
        if level >= t.levels {
            return false;
        }
        let (format, width, height, levels, flags) = (t.format, t.width, t.height, t.levels, t.flags);
        let (w, h) = convert::level_extent(width, height, level);
        let expanded;
        let pixels: &[u8] = match (src_format, format) {
            (SRC_RGB8, FORMAT_RGBA8) => {
                if data.len() < (w * h * 3) as usize {
                    return false;
                }
                expanded = convert::rgb8_to_rgba8(&data[..(w * h * 3) as usize]);
                &expanded
            }
            (SRC_NATIVE, _) => data,
            _ => return false,
        };
        if t.used == self.epoch {
            // Keep the contents earlier commands of this submission see (design §5.4).
            self.submit();
        }
        if !self.write_level(tex, level, w, h, format, pixels) {
            return false;
        }
        if level == 0 && flags & TEXTURE_AUTO_MIPMAP != 0 && format == FORMAT_RGBA8 && levels > 1 {
            let (mut img, mut cw, mut ch) = (pixels[..(w * h * 4) as usize].to_vec(), w, h);
            for l in 1..levels {
                let next = convert::downsample_rgba8(&img, cw, ch);
                (img, cw, ch) = next;
                self.write_level(tex, l, cw, ch, format, &img);
            }
        }
        true
    }

    fn write_level(&mut self, tex: u32, level: u32, w: u32, h: u32, format: u32, pixels: &[u8]) -> bool {
        let Some(t) = self.textures.get(tex) else { return false };
        let (row_bytes, rows) = convert::level_layout(format, w, h);
        if pixels.len() < (row_bytes * rows) as usize {
            return false;
        }
        let (cw, ch) = if convert::block_bytes(format).is_some() {
            (w.div_ceil(4) * 4, h.div_ceil(4) * 4)
        } else {
            (w, h)
        };
        self.queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &t.texture,
                mip_level: level,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &pixels[..(row_bytes * rows) as usize],
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(row_bytes),
                rows_per_image: Some(rows),
            },
            wgpu::Extent3d {
                width: cw,
                height: ch,
                depth_or_array_layers: 1,
            },
        );
        true
    }

    /// Reads a level back, tightly packed in the texture's format.
    pub fn texture_read(&mut self, tex: u32, level: u32) -> Option<Vec<u8>> {
        let t = self.textures.get(tex)?;
        if level >= t.levels {
            return None;
        }
        let (texture, format) = (t.texture.clone(), t.format);
        let (w, h) = convert::level_extent(t.width, t.height, level);
        self.submit();
        Some(self.read_texture_rgba(&texture, level, w, h, format))
    }

    pub fn depth_create(&mut self, width: u32, height: u32) -> u32 {
        self.depths.insert(Depth {
            width,
            height,
            texture: None,
            used: 0,
        })
    }

    pub fn depth_destroy(&mut self, depth: u32) {
        self.depths.remove(depth);
    }

    // --- meshes ---------------------------------------------------------------------------------

    pub fn mesh_create(&mut self, layout: u32, vertices: &[u8], indices: &[u16]) -> u32 {
        let layout = if layout == LAYOUT_SKIN {
            Layout::Skin
        } else {
            Layout::Mesh
        };
        let vertex = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("rwgpu mesh vertices"),
            contents: &convert::pad4(vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        let index = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("rwgpu mesh indices"),
            contents: &convert::pad4(bytemuck::cast_slice(indices)),
            usage: wgpu::BufferUsages::INDEX,
        });
        self.meshes.insert(Mesh { vertex, index, layout })
    }

    pub fn mesh_update_vertices(&mut self, mesh: u32, vertices: &[u8]) {
        let buffer = self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("rwgpu mesh vertices"),
            contents: &convert::pad4(vertices),
            usage: wgpu::BufferUsages::VERTEX,
        });
        if let Some(m) = self.meshes.get_mut(mesh) {
            m.vertex = buffer;
        }
    }

    pub fn mesh_destroy(&mut self, mesh: u32) {
        self.meshes.remove(mesh);
    }

    // --- per object / mesh state ---------------------------------------------------------------

    pub fn set_world_matrix(&mut self, m: &[f32; 16]) {
        self.object.world = *m;
        self.offsets.object = None;
    }

    pub fn set_lights(&mut self, ambient: [f32; 4], lights: &[RwgpuLight]) {
        self.object.amb_light = ambient;
        let n = lights.len().min(MAX_LIGHTS);
        for (i, l) in lights.iter().take(n).enumerate() {
            self.object.light_params[i] = [l.kind, l.radius, l.minus_cos_angle, l.hard_spot];
            self.object.light_position[i] = l.position;
            self.object.light_direction[i] = l.direction;
            self.object.light_color[i] = l.color;
        }
        if n < MAX_LIGHTS {
            self.object.light_params[n] = [0.0; 4];
        }
        self.offsets.object = None;
    }

    pub fn set_material(&mut self, color: [f32; 4], surface_props: [f32; 4]) {
        self.draw.mat_color = color;
        self.draw.surf_props = surface_props;
        self.offsets.draw = None;
    }

    pub fn set_bones(&mut self, matrices: &[[f32; 16]]) {
        for (i, m) in matrices.iter().take(MAX_BONES).enumerate() {
            self.bones.m[i] = *m;
        }
        self.offsets.bones = None;
    }

    pub fn set_matfx_env(
        &mut self,
        tex_matrix: &[f32; 16],
        fx_params: [f32; 4],
        color_clamp: [f32; 4],
        env_color: [f32; 4],
    ) {
        self.object.tex_matrix = *tex_matrix;
        self.draw.fx_params = fx_params;
        self.draw.color_clamp = color_clamp;
        self.draw.env_color = env_color;
        self.offsets.object = None;
        self.offsets.draw = None;
    }

    // --- draws ------------------------------------------------------------------------------

    pub fn draw_mesh(&mut self, mesh: u32, shader: u32, prim: u32, first_index: u32, index_count: u32) {
        let Some(m) = self.meshes.get(mesh) else { return };
        let layout = m.layout;
        let (vertex_stage, fragment_stage) = match shader {
            SHADER_SKIN => (VertexStage::Skin, FragmentStage::Simple),
            SHADER_MATFX_ENV => (VertexStage::MatfxEnv, FragmentStage::MatfxEnv),
            _ => (VertexStage::Default, FragmentStage::Simple),
        };
        let call = DrawCall {
            vertex_stage,
            fragment_stage,
            layout,
            topology: topology(prim),
            vertices: VertexSource::Mesh(mesh),
            indices: Some(IndexSource::Mesh { first: first_index }),
            count: index_count,
        };
        for pass in self.state.mesh_passes() {
            self.draw_with(&call, Some(pass));
        }
    }

    pub fn im2d_draw(
        &mut self,
        prim: u32,
        vertices: &[u8],
        stride: u64,
        num_vertices: u32,
        indices: Option<&[u16]>,
        uv2: bool,
    ) {
        if num_vertices == 0 {
            return;
        }
        let vertex_bytes = &vertices[..(stride * num_vertices as u64) as usize];
        let fan;
        let indices = if prim == PRIMTYPETRIFAN {
            fan = convert::fan_to_list(indices, indices.map_or(num_vertices as usize, |i| i.len()));
            Some(&fan[..])
        } else {
            indices
        };
        let index_bytes: &[u8] = indices.map_or(&[], |i| bytemuck::cast_slice(i));
        self.reserve(vertex_bytes.len() as u64, index_bytes.len() as u64);
        let voff = self.vertices.push(vertex_bytes, 4);
        let ioff = indices.map(|_| self.indices.push(index_bytes, 4));
        let fragment_stage = if self.im2d_override != 0 {
            FragmentStage::Override(self.im2d_override)
        } else {
            FragmentStage::Simple
        };
        let call = DrawCall {
            vertex_stage: if uv2 { VertexStage::Im2DUv2 } else { VertexStage::Im2D },
            fragment_stage,
            layout: if uv2 { Layout::Im2DUv2 } else { Layout::Im2D },
            topology: topology(prim),
            vertices: VertexSource::Arena {
                offset: voff,
                len: vertex_bytes.len() as u64,
            },
            indices: ioff.map(|o| IndexSource::Arena {
                offset: o,
                len: index_bytes.len() as u64,
            }),
            count: indices.map_or(num_vertices, |i| i.len() as u32),
        };
        self.draw_with(&call, None);
    }

    pub fn im2d_shader_create(&mut self, fragment: &str) -> u32 {
        let source = shaders::override_source(fragment);
        let scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        let module = self.device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("rwgpu im2d override"),
            source: wgpu::ShaderSource::Wgsl(source.into()),
        });
        let error = pollster::block_on(scope.pop());
        if let Some(error) = error {
            eprintln!("rwgpu: Im2D shader rejected: {error}");
            return 0;
        }
        self.overrides.push(module);
        self.overrides.len() as u32
    }

    pub fn im2d_set_override(&mut self, shader: u32, params: &[f32; 16]) {
        self.im2d_override = if (shader as usize) <= self.overrides.len() {
            shader
        } else {
            0
        };
        for i in 0..4 {
            self.draw.params[i] = [params[i * 4], params[i * 4 + 1], params[i * 4 + 2], params[i * 4 + 3]];
        }
        self.offsets.draw = None;
    }

    pub fn im3d_transform(&mut self, vertices: &[u8], num_vertices: u32, world: &[f32; 16], lit: bool) {
        self.set_world_matrix(world);
        let bytes = vertices[..(36 * num_vertices as usize)].to_vec();
        self.reserve(bytes.len() as u64, 0);
        let offset = self.vertices.push(&bytes, 4);
        self.im3d = Some(Im3D {
            offset,
            epoch: self.epoch,
            vertices: bytes,
            count: num_vertices,
            lit,
        });
    }

    pub fn im3d_draw(&mut self, prim: u32, indices: Option<&[u16]>) {
        let Some(im3d) = self.im3d.as_ref() else { return };
        let (num_vertices, lit, vertex_len) = (im3d.count, im3d.lit, im3d.vertices.len() as u64);
        let fan;
        let indices = if prim == PRIMTYPETRIFAN {
            fan = convert::fan_to_list(indices, indices.map_or(num_vertices as usize, |i| i.len()));
            Some(&fan[..])
        } else {
            indices
        };
        let index_bytes: &[u8] = indices.map_or(&[], |i| bytemuck::cast_slice(i));
        self.reserve(vertex_len, index_bytes.len() as u64);
        let im3d = self.im3d.as_mut().unwrap();
        if im3d.epoch != self.epoch {
            // The arenas restarted since the transform: push the vertices again.
            im3d.offset = self.vertices.push(&im3d.vertices, 4);
            im3d.epoch = self.epoch;
        }
        let offset = im3d.offset;
        let ioff = indices.map(|_| self.indices.push(index_bytes, 4));
        let call = DrawCall {
            vertex_stage: if lit { VertexStage::Default } else { VertexStage::Im3D },
            fragment_stage: FragmentStage::Simple,
            layout: Layout::Im3D,
            topology: topology(prim),
            vertices: VertexSource::Arena {
                offset,
                len: vertex_len,
            },
            indices: ioff.map(|o| IndexSource::Arena {
                offset: o,
                len: index_bytes.len() as u64,
            }),
            count: indices.map_or(num_vertices, |i| i.len() as u32),
        };
        self.draw_with(&call, None);
    }

    pub fn im3d_end(&mut self) {
        self.im3d = None;
    }

    fn draw_with(&mut self, call: &DrawCall, pass: Option<GsPass>) {
        if call.count == 0 {
            return;
        }
        self.reserve(0, 0);
        if !self.ensure_pass() {
            return;
        }
        let pass = pass.unwrap_or(GsPass {
            alpha_range: self.state.alpha_range(),
            depth: self.state.depth(),
        });
        let stage0 = self.state.sampling(0);
        let stage1 = self.state.sampling(1);
        let flags = [
            if self.state.fog_enabled() { 0.0 } else { 1.0 },
            (stage0.texture != 0 && stage0.flags & RASTER_FORCE_OPAQUE != 0) as u32 as f32,
            (stage1.texture != 0 && stage1.flags & RASTER_FORCE_OPAQUE != 0) as u32 as f32,
            ALL_LIGHTS,
        ];
        let alpha_ref = [pass.alpha_range[0], pass.alpha_range[1], 0.0, 0.0];
        let fog_color = self.state.fog_color();
        if self.draw.flags != flags || self.draw.alpha_ref != alpha_ref || self.draw.fog_color != fog_color {
            self.draw.flags = flags;
            self.draw.alpha_ref = alpha_ref;
            self.draw.fog_color = fog_color;
            self.offsets.draw = None;
        }
        let depth = self
            .target_has_depth()
            .then(|| depth_key(pass.depth, self.state.stencil()));
        let key = PipelineKey {
            vertex: call.vertex_stage,
            fragment: call.fragment_stage,
            layout: call.layout,
            topology: call.topology,
            blend: self.state.blend(),
            depth,
            cull: self.state.cull(),
            color_write: true,
            color_format: self.target_format(),
        };
        let reference = self.state.stencil().reference;
        if let Some(p) = self.pass.as_mut() {
            p.set_stencil_reference(reference);
        }
        self.issue(&key, call);
    }

    fn uniform_offsets(&mut self) -> [u32; 4] {
        let align = self.uniform_align;
        let camera = *self
            .offsets
            .camera
            .get_or_insert_with(|| self.uniforms.push(bytemuck::bytes_of(&self.camera), align));
        let object = *self
            .offsets
            .object
            .get_or_insert_with(|| self.uniforms.push(bytemuck::bytes_of(&self.object), align));
        let draw = *self
            .offsets
            .draw
            .get_or_insert_with(|| self.uniforms.push(bytemuck::bytes_of(&self.draw), align));
        let bones = *self
            .offsets
            .bones
            .get_or_insert_with(|| self.uniforms.push(bytemuck::bytes_of(&self.bones), align));
        [camera as u32, object as u32, draw as u32, bones as u32]
    }

    fn sampler(&mut self, key: SamplerKey) -> wgpu::Sampler {
        let border = self.border_supported;
        self.samplers
            .entry(key)
            .or_insert_with(|| self.device.create_sampler(&sampler_descriptor(key, border)))
            .clone()
    }

    fn texture_bind_group(&mut self) -> wgpu::BindGroup {
        let s0 = self.state.sampling(0);
        let s1 = self.state.sampling(1);
        let resolve = |tex: u32, textures: &Slab<Texture>| if textures.get(tex).is_some() { tex } else { 0 };
        let key = TextureBindKey {
            tex0: resolve(s0.texture, &self.textures),
            samp0: SamplerKey::new(
                s0.state.filter,
                s0.state.address_u,
                s0.state.address_v,
                s0.state.max_anisotropy,
            ),
            tex1: resolve(s1.texture, &self.textures),
            samp1: SamplerKey::new(
                s1.state.filter,
                s1.state.address_u,
                s1.state.address_v,
                s1.state.max_anisotropy,
            ),
        };
        for tex in [key.tex0, key.tex1] {
            if let Some(t) = self.textures.get_mut(tex) {
                t.used = self.epoch;
            }
        }
        if let Some(group) = self.texture_bind_groups.get(&key) {
            return group.clone();
        }
        let samp0 = self.sampler(key.samp0);
        let samp1 = self.sampler(key.samp1);
        let view = |tex: u32| self.textures.get(tex).map_or(&self.white.1, |t| &t.view);
        let group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("rwgpu textures"),
            layout: &self.texture_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(view(key.tex0)),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&samp0),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(view(key.tex1)),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::Sampler(&samp1),
                },
            ],
        });
        self.texture_bind_groups.insert(key, group.clone());
        group
    }

    fn pipeline(&mut self, key: &PipelineKey) -> Option<wgpu::RenderPipeline> {
        if let Some(p) = self.pipelines.get(key) {
            return Some(p.clone());
        }
        let fragment_module = match key.fragment {
            FragmentStage::Override(h) => self.overrides.get(h as usize - 1)?.clone(),
            _ => self.main_module.clone(),
        };
        let fragment_entry = match key.fragment {
            FragmentStage::Simple => "fs_simple",
            FragmentStage::MatfxEnv => "fs_matfx_env",
            FragmentStage::Override(_) => "fs_main",
            FragmentStage::Clear => "fs_clear",
        };
        let buffers: Vec<Option<wgpu::VertexBufferLayout>> = vertex_layout(key.layout).into_iter().map(Some).collect();
        let strip = matches!(
            key.topology,
            wgpu::PrimitiveTopology::TriangleStrip | wgpu::PrimitiveTopology::LineStrip
        );
        let pipeline = self.device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("rwgpu"),
            layout: Some(&self.pipeline_layout),
            vertex: wgpu::VertexState {
                module: &self.main_module,
                entry_point: Some(vertex_entry(key.vertex)),
                compilation_options: Default::default(),
                buffers: &buffers,
            },
            primitive: wgpu::PrimitiveState {
                topology: key.topology,
                strip_index_format: strip.then_some(wgpu::IndexFormat::Uint16),
                front_face: wgpu::FrontFace::Ccw,
                cull_mode: cull_mode(key.cull),
                unclipped_depth: false,
                polygon_mode: wgpu::PolygonMode::Fill,
                conservative: false,
            },
            depth_stencil: key.depth.map(depth_stencil_state),
            multisample: wgpu::MultisampleState::default(),
            fragment: Some(wgpu::FragmentState {
                module: &fragment_module,
                entry_point: Some(fragment_entry),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: key.color_format,
                    blend: blend_state(key.blend),
                    write_mask: if key.color_write {
                        wgpu::ColorWrites::ALL
                    } else {
                        wgpu::ColorWrites::empty()
                    },
                })],
            }),
            multiview_mask: None,
            cache: None,
        });
        self.pipelines.insert(*key, pipeline.clone());
        Some(pipeline)
    }

    /// Records one draw into the open pass.
    fn issue(&mut self, key: &PipelineKey, call: &DrawCall) {
        let Some(pipeline) = self.pipeline(key) else { return };
        let offsets = self.uniform_offsets();
        let textures = self.texture_bind_group();
        let (mesh_vertex, mesh_index) = match (&call.vertices, &call.indices) {
            (VertexSource::Mesh(m), _) => match self.meshes.get(*m) {
                Some(mesh) => (Some(mesh.vertex.clone()), Some(mesh.index.clone())),
                None => return,
            },
            _ => (None, None),
        };
        let bind_pipeline = self.bound_pipeline != Some(*key);
        let Some(pass) = self.pass.as_mut() else { return };
        if bind_pipeline {
            pass.set_pipeline(&pipeline);
        }
        pass.set_bind_group(0, &self.uniform_bind_group, &offsets);
        pass.set_bind_group(1, &textures, &[]);
        match &call.vertices {
            VertexSource::Mesh(_) => pass.set_vertex_buffer(0, mesh_vertex.as_ref().unwrap().slice(..)),
            VertexSource::Arena { offset, len } => {
                pass.set_vertex_buffer(0, self.vertices.buffer.slice(*offset..*offset + *len))
            }
            VertexSource::None => {}
        }
        match &call.indices {
            Some(IndexSource::Mesh { first }) => {
                pass.set_index_buffer(mesh_index.as_ref().unwrap().slice(..), wgpu::IndexFormat::Uint16);
                pass.draw_indexed(*first..*first + call.count, 0, 0..1);
            }
            Some(IndexSource::Arena { offset, len }) => {
                let len = len.next_multiple_of(4);
                pass.set_index_buffer(
                    self.indices.buffer.slice(*offset..*offset + len),
                    wgpu::IndexFormat::Uint16,
                );
                pass.draw_indexed(0..call.count, 0, 0..1);
            }
            None => pass.draw(0..call.count, 0..1),
        }
        self.bound_pipeline = Some(*key);
    }

    // --- presenting ---------------------------------------------------------------------------

    pub fn present(&mut self, vsync: bool) {
        self.end_pass();
        if vsync != self.vsync {
            self.vsync = vsync;
            self.surface_config.present_mode = present_mode(vsync, &self.present_modes);
            self.surface.configure(&self.device, &self.surface_config);
        }
        let frame_number = self.stats.frames() + 1;
        let dump_path = self.dump.path_for(frame_number);
        let readback = dump_path.as_ref().map(|_| {
            let (w, h) = self.main_size;
            let padded = (w * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
            let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("rwgpu frame dump"),
                size: (padded * h) as u64,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            });
            let main = self.main.0.clone();
            self.encoder().copy_texture_to_buffer(
                main.as_image_copy(),
                wgpu::TexelCopyBufferInfo {
                    buffer: &buffer,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(padded),
                        rows_per_image: Some(h),
                    },
                },
                wgpu::Extent3d {
                    width: w,
                    height: h,
                    depth_or_array_layers: 1,
                },
            );
            (buffer, w, h, padded)
        });

        let surface_texture = match self.surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(t) | wgpu::CurrentSurfaceTexture::Suboptimal(t) => Some(t),
            wgpu::CurrentSurfaceTexture::Outdated | wgpu::CurrentSurfaceTexture::Lost => {
                self.surface.configure(&self.device, &self.surface_config);
                None
            }
            _ => None,
        };
        if let Some(st) = surface_texture.as_ref() {
            let view = st.texture.create_view(&Default::default());
            let group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("rwgpu blit"),
                layout: &self.blit_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(&self.main.1),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::Sampler(&self.blit_sampler),
                    },
                ],
            });
            let pipeline = self.blit_pipeline.clone();
            let encoder = self.encoder();
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("rwgpu blit"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    depth_slice: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&pipeline);
            pass.set_bind_group(0, &group, &[]);
            pass.draw(0..3, 0..1);
        }
        self.submit();
        if let Some(st) = surface_texture {
            self.queue.present(st);
        }
        if let (Some(path), Some((buffer, w, h, padded))) = (dump_path, readback) {
            let rgba = map_and_read(&self.device, &buffer, w * 4, padded, h);
            if let Err(e) = write_png(&path, w, h, &convert::rgba8_to_rgb8(&rgba)) {
                eprintln!("rwgpu: frame dump failed: {e}");
            } else {
                eprintln!("rwgpu: wrote {}", path.display());
            }
        }
        if let Some(line) = self.stats.record(Instant::now()) {
            eprintln!("{line}");
        }
    }
}

fn present_mode(vsync: bool, available: &[wgpu::PresentMode]) -> wgpu::PresentMode {
    if vsync {
        wgpu::PresentMode::Fifo
    } else if available.contains(&wgpu::PresentMode::Immediate) {
        wgpu::PresentMode::Immediate
    } else {
        wgpu::PresentMode::AutoNoVsync
    }
}

/// The viewport of `target` clamped to a `width`×`height` attachment.
fn clamp_viewport(target: &RwgpuTarget, width: u32, height: u32) -> (f32, f32, f32, f32) {
    let x0 = target.x.clamp(0, width as i32);
    let y0 = target.y.clamp(0, height as i32);
    let x1 = (target.x + target.w).clamp(0, width as i32);
    let y1 = (target.y + target.h).clamp(0, height as i32);
    (x0 as f32, y0 as f32, (x1 - x0) as f32, (y1 - y0) as f32)
}

fn map_and_read(device: &wgpu::Device, buffer: &wgpu::Buffer, row_bytes: u32, padded: u32, rows: u32) -> Vec<u8> {
    let slice = buffer.slice(..);
    slice.map_async(wgpu::MapMode::Read, |_| {});
    let _ = device.poll(wgpu::PollType::Wait {
        submission_index: None,
        timeout: None,
    });
    let data = slice.get_mapped_range().expect("rwgpu: readback buffer is mapped");
    let mut out = Vec::with_capacity((row_bytes * rows) as usize);
    for r in 0..rows as usize {
        let start = r * padded as usize;
        out.extend_from_slice(&data[start..start + row_bytes as usize]);
    }
    drop(data);
    buffer.unmap();
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uniform_blocks_match_the_wgsl_layouts() {
        assert_eq!(block_size::<CameraBlock>(), 176);
        assert_eq!(block_size::<ObjectBlock>(), 656);
        assert_eq!(block_size::<DrawBlock>(), 192);
        assert_eq!(block_size::<BonesBlock>(), 4096);
        let module = crate::shaders::validate(crate::shaders::MAIN).unwrap();
        let size_of = |name: &str| {
            let (_, ty) = module
                .types
                .iter()
                .find(|(_, t)| t.name.as_deref() == Some(name))
                .unwrap();
            ty.inner.size(module.to_ctx()) as u64
        };
        assert_eq!(size_of("Camera"), block_size::<CameraBlock>());
        assert_eq!(size_of("Object"), block_size::<ObjectBlock>());
        assert_eq!(size_of("Draw"), block_size::<DrawBlock>());
        assert_eq!(size_of("Bones"), block_size::<BonesBlock>());
    }

    #[test]
    fn viewports_are_clamped_to_the_attachment() {
        let t = RwgpuTarget {
            color: 0,
            depth: 0,
            x: -10,
            y: 5,
            w: 100,
            h: 100,
        };
        assert_eq!(clamp_viewport(&t, 50, 50), (0.0, 5.0, 50.0, 45.0));
    }

    #[test]
    fn slab_reuses_freed_handles() {
        let mut s = Slab::new();
        let a = s.insert(1);
        let b = s.insert(2);
        assert_eq!((a, b), (1, 2));
        assert_eq!(s.remove(a), Some(1));
        assert_eq!(s.get(a), None);
        assert_eq!(s.insert(3), 1);
        assert_eq!(s.get(0), None);
        assert_eq!(s.len(), 2);
    }

    #[test]
    fn present_mode_follows_vsync() {
        use wgpu::PresentMode as P;
        assert_eq!(present_mode(true, &[P::Fifo, P::Immediate]), P::Fifo);
        assert_eq!(present_mode(false, &[P::Fifo, P::Immediate]), P::Immediate);
        assert_eq!(present_mode(false, &[P::Fifo]), P::AutoNoVsync);
    }
}
