//! Shared canvas plumbing: HiDPI sizing and the animation loop.

use std::cell::RefCell;
use std::rc::Rc;

use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{CanvasRenderingContext2d, HtmlCanvasElement};

/// A canvas plus its 2d context, kept sized to its CSS box in device pixels.
pub struct Surface {
    pub canvas: HtmlCanvasElement,
    pub ctx: CanvasRenderingContext2d,
    /// Logical (CSS pixel) size. Drawing code should use these, not the
    /// backing-store size.
    pub width: f64,
    pub height: f64,
}

impl Surface {
    pub fn new(canvas: HtmlCanvasElement) -> Result<Self, JsValue> {
        let ctx = canvas
            .get_context("2d")?
            .ok_or_else(|| JsValue::from_str("2d context unavailable"))?
            .dyn_into::<CanvasRenderingContext2d>()?;

        let mut surface = Surface {
            canvas,
            ctx,
            width: 0.0,
            height: 0.0,
        };
        surface.resize()?;
        Ok(surface)
    }

    /// Match the backing store to the element's CSS box at the current device
    /// pixel ratio, then scale the context so drawing happens in CSS pixels.
    pub fn resize(&mut self) -> Result<bool, JsValue> {
        let dpr = crate::window().device_pixel_ratio().max(1.0);
        let rect = self.canvas.get_bounding_client_rect();
        let (w, h) = (rect.width(), rect.height());

        if w <= 0.0 || h <= 0.0 {
            return Ok(false);
        }

        let (bw, bh) = ((w * dpr).round() as u32, (h * dpr).round() as u32);
        if self.canvas.width() == bw && self.canvas.height() == bh {
            return Ok(false);
        }

        self.canvas.set_width(bw);
        self.canvas.set_height(bh);
        self.width = w;
        self.height = h;
        self.ctx.set_transform(dpr, 0.0, 0.0, dpr, 0.0, 0.0)?;
        Ok(true)
    }

    pub fn clear(&self) {
        self.ctx.clear_rect(0.0, 0.0, self.width, self.height);
    }
}

/// The self-referencing handle an animation loop keeps on its own callback.
type FrameCallback = Rc<RefCell<Option<Closure<dyn FnMut(f64)>>>>;

/// Drive `draw` once per frame. `t` is seconds since the loop started.
///
/// The closure is leaked deliberately: these loops live for the lifetime of
/// the page, and dropping the `Closure` would invalidate the callback that
/// requestAnimationFrame still holds.
pub fn animate<F>(mut draw: F)
where
    F: FnMut(f64) + 'static,
{
    let held: FrameCallback = Rc::new(RefCell::new(None));
    let scheduler = held.clone();
    let mut origin: Option<f64> = None;

    *held.borrow_mut() = Some(Closure::wrap(Box::new(move |now_ms: f64| {
        let origin = *origin.get_or_insert(now_ms);
        draw((now_ms - origin) / 1000.0);

        if let Some(cb) = scheduler.borrow().as_ref() {
            request_frame(cb);
        }
    }) as Box<dyn FnMut(f64)>));

    if let Some(cb) = held.borrow().as_ref() {
        request_frame(cb);
    }
    std::mem::forget(held);
}

fn request_frame(cb: &Closure<dyn FnMut(f64)>) {
    let _ = crate::window().request_animation_frame(cb.as_ref().unchecked_ref());
}

/// Deterministic PRNG so a given figure looks the same on every reload.
pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed | 1)
    }

    /// xorshift64*, mapped to [0, 1).
    pub fn next_f64(&mut self) -> f64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        let v = x.wrapping_mul(0x2545_F491_4F6C_DD1D) >> 11;
        v as f64 / (1u64 << 53) as f64
    }

    pub fn range(&mut self, lo: f64, hi: f64) -> f64 {
        lo + self.next_f64() * (hi - lo)
    }
}
