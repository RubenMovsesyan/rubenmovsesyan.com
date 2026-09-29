//! The night sky above the notebook: a slow parallax drift with per-star
//! twinkle, plus a handful of bright stars carrying a soft halo.

use wasm_bindgen::prelude::*;
use web_sys::HtmlCanvasElement;

use crate::canvas::{animate, Rng, Surface};

const STAR_COUNT: usize = 340;
/// Stars at or above this depth get the three-layer halo treatment.
const BRIGHT_DEPTH: f64 = 0.93;

struct Star {
    /// Position in normalised [0,1) space so a resize never reshuffles stars.
    x: f64,
    y: f64,
    radius: f64,
    /// Farther stars drift slower, which reads as depth.
    depth: f64,
    phase: f64,
    twinkle_hz: f64,
    /// Faint colour cast — stars are not all the same white.
    tint: (u8, u8, u8),
}

/// Blue-white through to warm amber, picked per star.
const TINTS: [(u8, u8, u8); 5] = [
    (212, 238, 255),
    (255, 255, 255),
    (238, 244, 255),
    (255, 248, 224),
    (255, 232, 204),
];

pub fn mount(canvas: HtmlCanvasElement) -> Result<(), JsValue> {
    let mut surface = Surface::new(canvas)?;
    let mut rng = Rng::new(0x5EED_1E55);

    let stars: Vec<Star> = (0..STAR_COUNT)
        .map(|_| {
            let depth = rng.range(0.15, 1.0);
            let tint = TINTS[(rng.next_f64() * TINTS.len() as f64) as usize % TINTS.len()];
            Star {
                x: rng.next_f64(),
                y: rng.next_f64(),
                radius: 0.35 + depth * 1.1,
                depth,
                phase: rng.range(0.0, std::f64::consts::TAU),
                twinkle_hz: rng.range(0.05, 0.35),
                tint,
            }
        })
        .collect();

    animate(move |t| {
        let _ = surface.resize();
        surface.clear();

        let (w, h) = (surface.width, surface.height);
        let ctx = &surface.ctx;

        for star in &stars {
            // Drift right and wrap; depth sets the rate.
            let x = ((star.x + t * 0.0035 * star.depth) % 1.0) * w;
            let y = star.y * h;

            let twinkle = (t * star.twinkle_hz * std::f64::consts::TAU + star.phase).sin();
            let alpha = (0.25 + star.depth * 0.45 + twinkle * 0.18).clamp(0.0, 1.0);
            let (r, g, b) = star.tint;

            // Bright stars get an outer bloom and an inner flare, so the sky
            // has a few anchors rather than a uniform dusting.
            if star.depth >= BRIGHT_DEPTH {
                disc(ctx, x, y, star.radius * 4.5, &rgba(r, g, b, alpha * 0.06));
                disc(ctx, x, y, star.radius * 2.0, &rgba(r, g, b, alpha * 0.22));
            }

            disc(ctx, x, y, star.radius, &rgba(r, g, b, alpha));
        }
    });

    Ok(())
}

fn rgba(r: u8, g: u8, b: u8, a: f64) -> String {
    format!("rgba({r}, {g}, {b}, {a:.3})")
}

fn disc(ctx: &web_sys::CanvasRenderingContext2d, x: f64, y: f64, r: f64, fill: &str) {
    ctx.set_fill_style_str(fill);
    ctx.begin_path();
    let _ = ctx.arc(x, y, r, 0.0, std::f64::consts::TAU);
    ctx.fill();
}
