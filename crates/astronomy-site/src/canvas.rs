//! Shared canvas plumbing: HiDPI sizing and the paced animation loop.

use std::cell::{Cell, RefCell};
use std::rc::Rc;

use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{CanvasRenderingContext2d, Element, HtmlCanvasElement, IntersectionObserver, IntersectionObserverEntry};

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

/// Drive `draw` without spending the GPU where it shows nothing: at the
/// display's rate while `busy()` says something is moving fast (a turn round
/// the telescope), at `idle_fps` otherwise, and not at all while `element`
/// is off screen; it starts again when it scrolls back into view. (Hidden
/// tabs are paused by the browser.) `t` is seconds since the loop started.
///
/// The closures are leaked deliberately: these loops live for the lifetime of
/// the page, and dropping a `Closure` would invalidate the callback that
/// requestAnimationFrame or the observer still holds.
pub fn animate<F>(element: &Element, idle_fps: f64, busy: fn() -> bool, mut draw: F)
where
    F: FnMut(f64) + 'static,
{
    let held: FrameCallback = Rc::new(RefCell::new(None));
    let visible = Rc::new(Cell::new(true));
    let running = Rc::new(Cell::new(true));
    let mut origin: Option<f64> = None;
    let mut last_draw = f64::NEG_INFINITY;
    let min_gap_ms = 1000.0 / idle_fps;

    let (scheduler, seen, run) = (held.clone(), visible.clone(), running.clone());
    *held.borrow_mut() = Some(Closure::wrap(Box::new(move |now_ms: f64| {
        if !seen.get() {
            // Off screen: stop asking for frames until it's back in view.
            run.set(false);
            return;
        }
        let origin = *origin.get_or_insert(now_ms);
        // A little slack, so a 60 Hz display's frames land on the 20 fps beat.
        if busy() || now_ms - last_draw >= min_gap_ms - 2.0 {
            last_draw = now_ms;
            draw((now_ms - origin) / 1000.0);
        }
        if let Some(cb) = scheduler.borrow().as_ref() {
            request_frame(cb);
        }
    }) as Box<dyn FnMut(f64)>));

    // Pause and resume with the element's visibility.
    let (scheduler, seen, run) = (held.clone(), visible.clone(), running.clone());
    let on_view = Closure::wrap(Box::new(move |entries: js_sys::Array, _: JsValue| {
        let Some(entry) = entries.iter().last().and_then(|e| e.dyn_into::<IntersectionObserverEntry>().ok()) else {
            return;
        };
        seen.set(entry.is_intersecting());
        if entry.is_intersecting() && !run.replace(true) {
            if let Some(cb) = scheduler.borrow().as_ref() {
                request_frame(cb);
            }
        }
    }) as Box<dyn FnMut(js_sys::Array, JsValue)>);
    if let Ok(observer) = IntersectionObserver::new(on_view.as_ref().unchecked_ref()) {
        observer.observe(element);
        std::mem::forget(observer);
    }
    on_view.forget();

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
