//! Turning around the telescope with a sideways scroll or a drag.
//!
//! A horizontal wheel or trackpad scroll while the sky is on screen, or a
//! sideways drag on the sky (a finger on a phone, where there is no sideways
//! scroll; a mouse elsewhere), turns the view: the telescope's camera orbits
//! it (telescope.rs) and the stars slide with parallax (starfield.rs). Both
//! read the one angle kept here. The angle eases toward where the scroll or
//! drag put it, so a burst of input reads as one smooth turn.
//!
//! Positive angle: the camera has moved to its right around the telescope,
//! so the sky slides right.

use std::cell::{Cell, RefCell};

use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{AddEventListenerOptions, Document, Element, PointerEvent, WheelEvent};

/// Radians of turn per pixel of sideways scroll.
const RADIANS_PER_PIXEL: f64 = 0.004;
/// Radians of turn per pixel dragged: more than a scroll, since a phone is
/// narrow; a drag across a phone's width turns it about half way round.
const RADIANS_PER_DRAG_PIXEL: f64 = 0.007;
/// How quickly the view catches up with the scroll (per second; higher is
/// snappier).
const EASE_RATE: f64 = 9.0;

thread_local! {
    static TARGET: Cell<f64> = const { Cell::new(0.0) };
    /// The pointer dragging the sky, and where it was last.
    static DRAG: Cell<Option<(i32, f64)>> = const { Cell::new(None) };
    static CURRENT: Cell<f64> = const { Cell::new(0.0) };
    static RUNNING: Cell<bool> = const { Cell::new(false) };
    static LISTENERS: RefCell<Vec<Box<dyn Fn(f64)>>> = const { RefCell::new(Vec::new()) };
    static LAST_FRAME: Cell<Option<f64>> = const { Cell::new(None) };
    static TICK: RefCell<Option<Closure<dyn FnMut(f64)>>> = const { RefCell::new(None) };
}

/// The view's current turn around the telescope, in radians.
pub fn angle() -> f64 {
    CURRENT.with(Cell::get)
}

/// Whether the view is turning right now; other animations can run at full
/// rate meanwhile and slow down when it settles.
pub fn is_turning() -> bool {
    RUNNING.with(Cell::get)
}

/// Calls `f` with the new angle on every frame the view is turning.
pub fn on_turn(f: impl Fn(f64) + 'static) {
    LISTENERS.with(|l| l.borrow_mut().push(Box::new(f)));
}

pub fn mount(document: &Document) -> Result<(), JsValue> {
    let Some(sky) = document.query_selector(".sky-stage")? else {
        return Ok(());
    };
    mount_drag(&sky)?;
    let on_wheel = Closure::wrap(Box::new(move |e: WheelEvent| {
        let (dx, dy) = (e.delta_x(), e.delta_y());
        // Only sideways scrolls; an up/down scroll still scrolls the page.
        if dx.abs() <= dy.abs() {
            return;
        }
        // Only while the sky is in view: further down, nothing would turn.
        if sky.get_bounding_client_rect().bottom() <= 0.0 {
            return;
        }
        // Keeps the browser from treating the swipe as back/forward.
        e.prevent_default();
        let pixels = match e.delta_mode() {
            WheelEvent::DOM_DELTA_LINE => dx * 16.0,
            WheelEvent::DOM_DELTA_PAGE => dx * 400.0,
            _ => dx,
        };
        TARGET.with(|t| t.set(t.get() + pixels * RADIANS_PER_PIXEL));
        start();
    }) as Box<dyn FnMut(WheelEvent)>);

    // Not passive, so prevent_default is allowed.
    let options = AddEventListenerOptions::new();
    options.set_passive(false);
    crate::window().add_event_listener_with_callback_and_add_event_listener_options(
        "wheel",
        on_wheel.as_ref().unchecked_ref(),
        &options,
    )?;
    on_wheel.forget();
    Ok(())
}

/// A sideways drag on the sky turns the view. The sky has `touch-action:
/// pan-y` (base.css): an up/down swipe still scrolls the page, and the
/// browser hands sideways ones to us.
fn mount_drag(sky: &Element) -> Result<(), JsValue> {
    let listen = |name: &str, f: Box<dyn FnMut(PointerEvent)>| -> Result<(), JsValue> {
        let cb = Closure::wrap(f);
        sky.add_event_listener_with_callback(name, cb.as_ref().unchecked_ref())?;
        cb.forget();
        Ok(())
    };

    let target = sky.clone();
    listen("pointerdown", Box::new(move |e: PointerEvent| {
        // Mouse: the main button only.
        if e.pointer_type() == "mouse" && e.button() != 0 {
            return;
        }
        DRAG.with(|d| d.set(Some((e.pointer_id(), e.client_x() as f64))));
        // Keep receiving its moves even when it leaves the sky.
        let _ = target.set_pointer_capture(e.pointer_id());
        let _ = target.class_list().add_1("is-dragging");
    }))?;

    listen("pointermove", Box::new(move |e: PointerEvent| {
        let Some((id, last)) = DRAG.with(Cell::get) else { return };
        if id != e.pointer_id() {
            return;
        }
        let x = e.client_x() as f64;
        DRAG.with(|d| d.set(Some((id, x))));
        // Opposite to a scroll: dragging right turns the camera left, so
        // the telescope turns the way the finger pulls it.
        TARGET.with(|t| t.set(t.get() - (x - last) * RADIANS_PER_DRAG_PIXEL));
        start();
    }))?;

    // Lifting the finger, or the browser taking the gesture over to scroll.
    for name in ["pointerup", "pointercancel", "lostpointercapture"] {
        let target = sky.clone();
        listen(name, Box::new(move |e: PointerEvent| {
            if DRAG.with(Cell::get).is_some_and(|(id, _)| id == e.pointer_id()) {
                DRAG.with(|d| d.set(None));
                let _ = target.class_list().remove_1("is-dragging");
            }
        }))?;
    }
    Ok(())
}

/// Runs the easing loop until the view has caught up with the scroll. One
/// frame callback lives for the whole page; it stops asking for frames once
/// the turn settles, and a new scroll asks again.
fn start() {
    if RUNNING.with(|r| r.replace(true)) {
        return;
    }
    LAST_FRAME.with(|l| l.set(None));
    TICK.with(|t| {
        let mut t = t.borrow_mut();
        let cb = t.get_or_insert_with(|| Closure::wrap(Box::new(tick) as Box<dyn FnMut(f64)>));
        let _ = crate::window().request_animation_frame(cb.as_ref().unchecked_ref());
    });
}

fn tick(now: f64) {
    let dt = LAST_FRAME
        .with(|l| l.replace(Some(now)))
        .map_or(1.0 / 60.0, |prev| ((now - prev) / 1000.0).min(0.1));
    let target = TARGET.with(Cell::get);
    let current = CURRENT.with(Cell::get);
    let next = if (target - current).abs() < 1e-4 {
        target
    } else {
        current + (target - current) * (1.0 - (-EASE_RATE * dt).exp())
    };
    CURRENT.with(|c| c.set(next));
    LISTENERS.with(|l| l.borrow().iter().for_each(|f| f(next)));
    if next == target {
        RUNNING.with(|r| r.set(false));
    } else {
        TICK.with(|t| {
            if let Some(cb) = t.borrow().as_ref() {
                let _ = crate::window().request_animation_frame(cb.as_ref().unchecked_ref());
            }
        });
    }
}
