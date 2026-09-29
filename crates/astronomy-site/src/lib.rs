//! Shared browser code for the astronomy blog. Every page loads this one
//! bundle -- the contents page and each entry alike -- since they all share
//! layout.html, so anything a page does in the browser lives here.
//!
//! The HTML and CSS own layout, typography and every animation that CSS can
//! express on its own. This crate takes over where they can't: the canvas
//! starfield, scroll-triggered reveals, and centring figure references.
//!
//! Wiring contract: any element in the page that carries `data-orrery="<name>"`
//! is handed to the renderer registered under `<name>` at startup.

use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{Document, HtmlCanvasElement, Window};

mod canvas;
mod figref;
mod reveal;
mod starfield;

/// Entry point. Trunk emits the glue that calls this once the module loads.
#[wasm_bindgen(start)]
pub fn start() -> Result<(), JsValue> {
    console_error_panic_hook::set_once();

    let window = window();
    let document = window.document().expect("document should exist");

    mount_all(&document)?;
    reveal::mount(&document)?;
    figref::mount(&document)?;
    Ok(())
}

/// Find every `[data-orrery]` canvas and hand it to its renderer.
fn mount_all(document: &Document) -> Result<(), JsValue> {
    let nodes = document.query_selector_all("canvas[data-orrery]")?;

    for i in 0..nodes.length() {
        let Some(node) = nodes.item(i) else { continue };
        let canvas: HtmlCanvasElement = node.dyn_into()?;
        let name = canvas.get_attribute("data-orrery").unwrap_or_default();

        match name.as_str() {
            "starfield" => starfield::mount(canvas)?,
            other => web_sys::console::warn_1(
                &format!("astronomy-site: no renderer registered for \"{other}\"").into(),
            ),
        }
    }

    Ok(())
}

pub(crate) fn window() -> Window {
    web_sys::window().expect("no global window")
}
