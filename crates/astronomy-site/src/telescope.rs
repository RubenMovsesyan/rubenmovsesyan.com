//! The telescope standing in the sky: assets/models/telescope.glb drawn in 3D.
//!
//! WebGPU where the browser has it, WebGL2 otherwise; wgpu picks at runtime,
//! and the same WGSL shader runs on both. If neither works the canvas stays
//! empty, and so transparent: the sky simply has no telescope.
//!
//! It is drawn once, again when the canvas changes size, and on every frame
//! while a sideways scroll turns the view (orbit.rs): the camera goes round
//! the telescope; the model and its moonlight stay fixed together. Aiming the
//! telescope itself (its Azimuth and Altitude pivots) isn't animated yet.

use std::cell::RefCell;
use std::rc::Rc;

use glam::{Mat3, Mat4, Vec3, Vec4};
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{HtmlCanvasElement, ResizeObserver};
use wgpu::util::DeviceExt;

/// Compiled in: 64 KB, no request of its own.
const MODEL: &[u8] = include_bytes!("../../../assets/models/telescope.glb");

/// Where the Blender camera stands and looks, in glTF's Y-up axes (Blender's
/// Z-up (x, y, z) is glTF's (x, z, -y)). The frame is fitted to the model from
/// here, so only the direction and distance matter.
const EYE: Vec3 = Vec3::new(2.6, 1.75, 2.4);
const TARGET: Vec3 = Vec3::new(0.0, 0.85, -0.05);

/// The light: 15° off straight up, leaning to the reader's upper left. It is
/// set relative to the view, so it stays on the upper left from any camera.
const LIGHT_TILT_DEG: f32 = 15.0;
/// Moonlight: the light's colour (linear RGB) times its strength. Moonlight
/// is dim and reads as cool blue to night-adapted eyes.
const MOON_COLOR: [f32; 3] = [0.72, 0.82, 1.0];
const MOON_INTENSITY: f32 = 0.55;
/// The night sky's glow on faces turned away from the moon: dark and blue.
const SKY_AMBIENT: [f32; 3] = [0.035, 0.05, 0.09];
/// The cartoon look: each material is limited to this many shades, from the
/// sky's glow alone up to full moonlight, and every pixel takes the palette
/// colour nearest to its true shaded colour. Fewer bands, flatter look.
const TOON_BANDS: usize = 4;
/// Room in the shader for palette colours (materials x TOON_BANDS).
const MAX_PALETTE: usize = 32;
/// Space left around the model inside the canvas, as a fraction of its size.
const MARGIN: f32 = 0.03;
/// The frame is fitted to the model above this height (metres, ground = 0),
/// so the lower tripod runs off the bottom of the canvas and the telescope
/// itself fills more of it. 0 frames the whole model.
const FRAME_ABOVE: f32 = 0.6;

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Vertex {
    position: [f32; 3],
    normal: [f32; 3],
    color: [f32; 3],
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Uniforms {
    view_proj: [[f32; 4]; 4],
    /// xyz: direction toward the light, in world space; w: 1 when the canvas
    /// format isn't sRGB and the shader must encode the colour itself.
    light: [f32; 4],
    /// rgb: the moonlight's colour and strength; w unused (padding).
    light_color: [f32; 4],
    /// rgb: the sky's ambient light; w: how many palette entries are used.
    ambient: [f32; 4],
    /// The limited colours, linear RGB in xyz.
    palette: [[f32; 4]; MAX_PALETTE],
}

const SHADER: &str = r#"
struct Uniforms {
    view_proj: mat4x4<f32>,
    light: vec4<f32>,
    light_color: vec4<f32>,
    ambient: vec4<f32>,
    palette: array<vec4<f32>, 32>,
};
@group(0) @binding(0) var<uniform> u: Uniforms;

struct VertexIn {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) color: vec3<f32>,
};
struct VertexOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) normal: vec3<f32>,
    @location(1) color: vec3<f32>,
};

@vertex
fn vs_main(v: VertexIn) -> VertexOut {
    var out: VertexOut;
    out.clip = u.view_proj * vec4<f32>(v.position, 1.0);
    out.normal = v.normal;
    out.color = v.color;
    return out;
}

fn to_srgb(c: vec3<f32>) -> vec3<f32> {
    let low = c * 12.92;
    let high = 1.055 * pow(c, vec3<f32>(1.0 / 2.4)) - 0.055;
    return select(high, low, c <= vec3<f32>(0.0031308));
}

// Lambert shading under moonlight: lit in the moon's colour where a surface
// faces it, falling to the sky's dim blue where it faces away. No shadows.
// The shaded colour is then swapped for the nearest of a few fixed colours,
// compared as the eye sees them (sRGB), which gives flat cartoon bands.
@fragment
fn fs_main(f: VertexOut) -> @location(0) vec4<f32> {
    let n = normalize(f.normal);
    let l = normalize(u.light.xyz);
    let light = u.ambient.rgb + u.light_color.rgb * max(dot(n, l), 0.0);
    let shaded = f.color * light;

    let wanted = to_srgb(shaded);
    var color = shaded;
    var nearest = 1e9;
    let count = u32(u.ambient.w);
    for (var i = 0u; i < count; i = i + 1u) {
        let candidate = u.palette[i].rgb;
        let d = distance(to_srgb(candidate), wanted);
        if (d < nearest) {
            nearest = d;
            color = candidate;
        }
    }
    if (u.light.w > 0.5) {
        color = to_srgb(color);
    }
    return vec4<f32>(color, 1.0);
}
"#;

pub fn mount(canvas: HtmlCanvasElement) -> Result<(), JsValue> {
    wasm_bindgen_futures::spawn_local(async move {
        if let Err(e) = start(canvas).await {
            web_sys::console::warn_1(&format!("telescope: not drawn ({e})").into());
        }
    });
    Ok(())
}

/// The model as one mesh: every part placed by its pivots, coloured by its
/// material's base colour.
fn load_model() -> Result<(Vec<Vertex>, Vec<u32>), String> {
    let gltf = gltf::Gltf::from_slice(MODEL).map_err(|e| e.to_string())?;
    let blob = gltf.blob.as_deref().ok_or("model has no binary chunk")?;
    let scene = gltf.default_scene().or_else(|| gltf.scenes().next()).ok_or("model has no scene")?;

    let mut vertices = Vec::new();
    let mut indices = Vec::new();
    let mut stack: Vec<(gltf::Node, Mat4)> = scene.nodes().map(|n| (n, Mat4::IDENTITY)).collect();
    while let Some((node, parent)) = stack.pop() {
        let world = parent * Mat4::from_cols_array_2d(&node.transform().matrix());
        let normal_matrix = Mat3::from_mat4(world).inverse().transpose();
        if let Some(mesh) = node.mesh() {
            for prim in mesh.primitives() {
                let reader = prim.reader(|b| (b.index() == 0).then_some(blob));
                let positions = reader.read_positions().ok_or("primitive without positions")?;
                let normals: Vec<[f32; 3]> = reader.read_normals().ok_or("primitive without normals")?.collect();
                let c = prim.material().pbr_metallic_roughness().base_color_factor();
                let base = vertices.len() as u32;
                for (p, n) in positions.zip(normals) {
                    vertices.push(Vertex {
                        position: world.transform_point3(Vec3::from(p)).to_array(),
                        normal: (normal_matrix * Vec3::from(n)).normalize().to_array(),
                        color: [c[0], c[1], c[2]],
                    });
                }
                match reader.read_indices() {
                    Some(idx) => indices.extend(idx.into_u32().map(|i| base + i)),
                    None => indices.extend(base..vertices.len() as u32),
                }
            }
        }
        stack.extend(node.children().map(|c| (c, world)));
    }
    Ok((vertices, indices))
}

/// A perspective projection with its own left/right/bottom/top at the near
/// plane (an off-axis frustum), mapping depth to 0..1 as WebGPU does; wgpu
/// converts for WebGL.
fn frustum(l: f32, r: f32, b: f32, t: f32, n: f32, f: f32) -> Mat4 {
    Mat4::from_cols(
        Vec4::new(2.0 * n / (r - l), 0.0, 0.0, 0.0),
        Vec4::new(0.0, 2.0 * n / (t - b), 0.0, 0.0),
        Vec4::new((r + l) / (r - l), (t + b) / (t - b), f / (n - f), -1.0),
        Vec4::new(0.0, 0.0, n * f / (n - f), 0.0),
    )
}

/// The camera after turning `angle` radians around the telescope's upright
/// axis (orbit.rs). Positive angles move it to its right.
fn view_at(angle: f32) -> Mat4 {
    let turn = glam::Quat::from_rotation_y(angle);
    glam::camera::rh::view::look_at_mat4(turn * EYE, turn * TARGET, Vec3::Y)
}

/// How many camera angles the frame is fitted over.
const SWEEP: usize = 72;

/// The part of the view the model can occupy from any angle, as x/depth and
/// y/depth (the frame at unit distance), plus its depth range.
struct Frame {
    x0: f32,
    x1: f32,
    y0: f32,
    y1: f32,
    near: f32,
    far: f32,
}

/// Fitted once over a full turn, so the telescope keeps its size and place in
/// the canvas while the camera goes round it.
fn fit_frame(vertices: &[Vertex]) -> Frame {
    let mut f = Frame { x0: f32::MAX, x1: f32::MIN, y0: f32::MAX, y1: f32::MIN, near: f32::MAX, far: 0.0 };
    for i in 0..SWEEP {
        let view = view_at(std::f32::consts::TAU * i as f32 / SWEEP as f32);
        for v in vertices {
            let p = view.transform_point3(Vec3::from(v.position));
            let depth = -p.z;
            // Depth comes from the whole model: the clipped tripod is still drawn.
            f.near = f.near.min(depth);
            f.far = f.far.max(depth);
            if v.position[1] >= FRAME_ABOVE {
                f.x0 = f.x0.min(p.x / depth);
                f.x1 = f.x1.max(p.x / depth);
                f.y0 = f.y0.min(p.y / depth);
                f.y1 = f.y1.max(p.y / depth);
            }
        }
    }
    f
}

/// The projection that shows `frame` in a canvas of this aspect ratio.
fn projection(f: &Frame, aspect: f32) -> Mat4 {
    // Pad, then widen the narrower side so the frame matches the canvas.
    let (mut w, mut h) = ((f.x1 - f.x0) * (1.0 + 2.0 * MARGIN), (f.y1 - f.y0) * (1.0 + 2.0 * MARGIN));
    if w / h < aspect {
        w = h * aspect;
    } else {
        h = w / aspect;
    }
    let (cx, cy) = ((f.x0 + f.x1) / 2.0, (f.y0 + f.y1) / 2.0);
    let n = f.near * 0.5;
    frustum((cx - w / 2.0) * n, (cx + w / 2.0) * n, (cy - h / 2.0) * n, (cy + h / 2.0) * n, n, f.far * 2.0)
}

/// Toward the moon, in world space: 15° off the starting view's up axis,
/// toward its left. Fixed to the model from then on, so as the camera goes
/// round the telescope the light stays where it is relative to the model.
fn light_direction() -> Vec3 {
    let t = LIGHT_TILT_DEG.to_radians();
    let in_view = Vec3::new(-t.sin(), t.cos(), 0.0);
    view_at(0.0).inverse().transform_vector3(in_view).normalize()
}

/// The cartoon palette: every material colour in the model, at TOON_BANDS
/// evenly spaced light levels from the sky's glow alone to full moonlight.
fn toon_palette(vertices: &[Vertex]) -> ([[f32; 4]; MAX_PALETTE], usize) {
    let mut materials: Vec<[f32; 3]> = Vec::new();
    for v in vertices {
        if !materials.contains(&v.color) {
            materials.push(v.color);
        }
    }
    let ambient = Vec3::from(SKY_AMBIENT);
    let moon = Vec3::from(MOON_COLOR) * MOON_INTENSITY;
    let mut palette = [[0.0; 4]; MAX_PALETTE];
    let mut len = 0;
    for base in materials {
        for band in 0..TOON_BANDS {
            if len == MAX_PALETTE {
                web_sys::console::warn_1(&"telescope: palette full; raise MAX_PALETTE".into());
                return (palette, len);
            }
            let k = band as f32 / (TOON_BANDS - 1).max(1) as f32;
            palette[len] = (Vec3::from(base) * (ambient + moon * k)).extend(1.0).to_array();
            len += 1;
        }
    }
    (palette, len)
}

struct Renderer {
    canvas: HtmlCanvasElement,
    surface: wgpu::Surface<'static>,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    pipeline: wgpu::RenderPipeline,
    vertex_buffer: wgpu::Buffer,
    index_buffer: wgpu::Buffer,
    index_count: u32,
    uniform_buffer: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
    frame: Frame,
    light: Vec3,
    palette: [[f32; 4]; MAX_PALETTE],
    palette_len: usize,
    encode_srgb: bool,
    samples: u32,
    depth: Option<wgpu::TextureView>,
    msaa: Option<wgpu::TextureView>,
    /// The angle and size last drawn, so an unchanged frame is skipped.
    drawn: Option<(f64, u32, u32)>,
}

const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth24Plus;

async fn start(canvas: HtmlCanvasElement) -> Result<(), String> {
    let (vertices, indices) = load_model()?;

    let mut desc = wgpu::InstanceDescriptor::new_without_display_handle();
    desc.backends = wgpu::Backends::BROWSER_WEBGPU | wgpu::Backends::GL;
    // Falls back to WebGL when the browser has navigator.gpu but no adapter.
    let instance = wgpu::util::new_instance_with_webgpu_detection(desc).await;
    let surface = instance
        .create_surface(wgpu::SurfaceTarget::Canvas(canvas.clone()))
        .map_err(|e| format!("no surface: {e}"))?;
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions {
            compatible_surface: Some(&surface),
            ..Default::default()
        })
        .await
        .map_err(|e| format!("no adapter: {e}"))?;
    let backend = adapter.get_info().backend;
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor {
            label: Some("telescope"),
            required_limits: wgpu::Limits::downlevel_webgl2_defaults().using_resolution(adapter.limits()),
            ..Default::default()
        })
        .await
        .map_err(|e| format!("no device: {e}"))?;

    let caps = surface.get_capabilities(&adapter);
    let format = *caps.formats.first().ok_or("surface has no formats")?;
    // Premultiplied, so the transparent background shows the sky behind.
    let alpha_mode = [wgpu::CompositeAlphaMode::PreMultiplied, wgpu::CompositeAlphaMode::PostMultiplied]
        .into_iter()
        .find(|m| caps.alpha_modes.contains(m))
        .unwrap_or(caps.alpha_modes[0]);
    let samples = if adapter.get_texture_format_features(format).flags.sample_count_supported(4) { 4 } else { 1 };
    let config = wgpu::SurfaceConfiguration {
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        format,
        width: 1,
        height: 1,
        present_mode: wgpu::PresentMode::Fifo,
        desired_maximum_frame_latency: 2,
        alpha_mode,
        view_formats: vec![],
        // Auto keeps the canvas's ordinary sRGB behaviour.
        color_space: wgpu::SurfaceColorSpace::Auto,
    };

    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("telescope"),
        source: wgpu::ShaderSource::Wgsl(SHADER.into()),
    });
    let uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("telescope uniforms"),
        size: std::mem::size_of::<Uniforms>() as u64,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("telescope"),
        entries: &[wgpu::BindGroupLayoutEntry {
            binding: 0,
            visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        }],
    });
    let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("telescope"),
        layout: &layout,
        entries: &[wgpu::BindGroupEntry { binding: 0, resource: uniform_buffer.as_entire_binding() }],
    });
    let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("telescope"),
        bind_group_layouts: &[Some(&layout)],
        ..Default::default()
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("telescope"),
        layout: Some(&pipeline_layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: Some("vs_main"),
            buffers: &[Some(wgpu::VertexBufferLayout {
                array_stride: std::mem::size_of::<Vertex>() as u64,
                step_mode: wgpu::VertexStepMode::Vertex,
                attributes: &wgpu::vertex_attr_array![0 => Float32x3, 1 => Float32x3, 2 => Float32x3],
            })],
            compilation_options: Default::default(),
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: Some("fs_main"),
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend: None,
                write_mask: wgpu::ColorWrites::ALL,
            })],
            compilation_options: Default::default(),
        }),
        primitive: wgpu::PrimitiveState {
            // Blender's export winds front faces counter-clockwise.
            cull_mode: Some(wgpu::Face::Back),
            ..Default::default()
        },
        depth_stencil: Some(wgpu::DepthStencilState {
            format: DEPTH_FORMAT,
            depth_write_enabled: Some(true),
            depth_compare: Some(wgpu::CompareFunction::Less),
            stencil: Default::default(),
            bias: Default::default(),
        }),
        multisample: wgpu::MultisampleState { count: samples, ..Default::default() },
        multiview_mask: None,
        cache: None,
    });
    let vertex_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("telescope vertices"),
        contents: bytemuck::cast_slice(&vertices),
        usage: wgpu::BufferUsages::VERTEX,
    });
    let index_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("telescope indices"),
        contents: bytemuck::cast_slice(&indices),
        usage: wgpu::BufferUsages::INDEX,
    });

    let name = match backend {
        wgpu::Backend::BrowserWebGpu => "webgpu",
        wgpu::Backend::Gl => "webgl",
        _ => "other",
    };
    // For checking from the page which path a browser took.
    let _ = canvas.set_attribute("data-backend", name);

    let (palette, palette_len) = toon_palette(&vertices);
    let renderer = Rc::new(RefCell::new(Renderer {
        canvas: canvas.clone(),
        surface,
        device,
        queue,
        config,
        pipeline,
        vertex_buffer,
        index_buffer,
        index_count: indices.len() as u32,
        uniform_buffer,
        bind_group,
        frame: fit_frame(&vertices),
        light: light_direction(),
        palette,
        palette_len,
        encode_srgb: !format.is_srgb(),
        samples,
        depth: None,
        msaa: None,
        drawn: None,
    }));
    renderer.borrow_mut().draw();

    // Redraw at the new size whenever the canvas is resized.
    let r = renderer.clone();
    let on_resize = Closure::wrap(Box::new(move |_: js_sys::Array, _: JsValue| {
        r.borrow_mut().draw();
    }) as Box<dyn FnMut(js_sys::Array, JsValue)>);
    let observer = ResizeObserver::new(on_resize.as_ref().unchecked_ref()).map_err(|_| "no ResizeObserver")?;
    observer.observe(&canvas);
    on_resize.forget();
    std::mem::forget(observer);

    // And on every frame of a turn around it.
    let r = renderer.clone();
    crate::orbit::on_turn(move |_| r.borrow_mut().draw());
    Ok(())
}

impl Renderer {
    fn draw(&mut self) {
        // The canvas's drawing buffer follows its CSS size at device resolution.
        let dpr = crate::window().device_pixel_ratio();
        let max = self.device.limits().max_texture_dimension_2d;
        let width = ((self.canvas.client_width() as f64 * dpr).round() as u32).clamp(1, max);
        let height = ((self.canvas.client_height() as f64 * dpr).round() as u32).clamp(1, max);
        if self.canvas.client_width() == 0 || self.canvas.client_height() == 0 {
            return;
        }
        if (width, height) != (self.config.width, self.config.height) || self.depth.is_none() {
            self.canvas.set_width(width);
            self.canvas.set_height(height);
            self.config.width = width;
            self.config.height = height;
            self.surface.configure(&self.device, &self.config);
            // The depth and multisample buffers match the canvas; made once
            // per size, since a turn redraws every frame.
            let size = wgpu::Extent3d { width, height, depth_or_array_layers: 1 };
            let texture = |format, label| {
                self.device
                    .create_texture(&wgpu::TextureDescriptor {
                        label: Some(label),
                        size,
                        mip_level_count: 1,
                        sample_count: self.samples,
                        dimension: wgpu::TextureDimension::D2,
                        format,
                        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                        view_formats: &[],
                    })
                    .create_view(&Default::default())
            };
            self.depth = Some(texture(DEPTH_FORMAT, "telescope depth"));
            self.msaa = (self.samples > 1).then(|| texture(self.config.format, "telescope msaa"));
        }

        // Nothing moved and the size is the same: the canvas already shows
        // this, so the GPU has nothing to do.
        let angle = crate::orbit::angle();
        if self.drawn == Some((angle, width, height)) {
            return;
        }
        let view = view_at(angle as f32);
        let proj = projection(&self.frame, width as f32 / height as f32);
        let uniforms = Uniforms {
            view_proj: (proj * view).to_cols_array_2d(),
            light: self.light.extend(if self.encode_srgb { 1.0 } else { 0.0 }).to_array(),
            light_color: (Vec3::from(MOON_COLOR) * MOON_INTENSITY).extend(0.0).to_array(),
            ambient: Vec3::from(SKY_AMBIENT).extend(self.palette_len as f32).to_array(),
            palette: self.palette,
        };
        self.queue.write_buffer(&self.uniform_buffer, 0, bytemuck::bytes_of(&uniforms));

        let frame = match self.surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(f) | wgpu::CurrentSurfaceTexture::Suboptimal(f) => f,
            _ => return,
        };
        let target = frame.texture.create_view(&Default::default());
        let (Some(depth), msaa) = (self.depth.as_ref(), self.msaa.as_ref()) else { return };

        let mut encoder = self.device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("telescope"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: msaa.unwrap_or(&target),
                    resolve_target: msaa.map(|_| &target),
                    depth_slice: None,
                    ops: wgpu::Operations {
                        // Transparent: the sky shows around the telescope.
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: depth,
                    depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(1.0), store: wgpu::StoreOp::Discard }),
                    stencil_ops: None,
                }),
                ..Default::default()
            });
            pass.set_pipeline(&self.pipeline);
            pass.set_bind_group(0, &self.bind_group, &[]);
            pass.set_vertex_buffer(0, self.vertex_buffer.slice(..));
            pass.set_index_buffer(self.index_buffer.slice(..), wgpu::IndexFormat::Uint32);
            pass.draw_indexed(0..self.index_count, 0, 0..1);
        }
        self.queue.submit([encoder.finish()]);
        self.queue.present(frame);
        self.drawn = Some((angle, width, height));
    }
}
