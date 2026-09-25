//! Scroll-triggered reveals.
//!
//! The transition itself is CSS; this only toggles `is-visible` at the right
//! moment. The `js-reveal` class on <html> tells the stylesheet that something
//! is here to do the toggling, so the figures stay visible if wasm never runs.

use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{
    Document, Element, IntersectionObserver, IntersectionObserverEntry, IntersectionObserverInit,
};

pub fn mount(document: &Document) -> Result<(), JsValue> {
    if let Some(root) = document.document_element() {
        root.class_list().add_1("js-reveal")?;
    }

    let callback = Closure::wrap(Box::new(move |entries: js_sys::Array, _obs: JsValue| {
        for entry in entries.iter() {
            let Ok(entry) = entry.dyn_into::<IntersectionObserverEntry>() else {
                continue;
            };
            if entry.is_intersecting() {
                let _ = entry.target().class_list().add_1("is-visible");
            }
        }
    }) as Box<dyn FnMut(js_sys::Array, JsValue)>);

    let options = IntersectionObserverInit::new();
    // Fire a little before the element's top edge reaches the viewport bottom.
    options.set_root_margin("0px 0px -12% 0px");
    let observer =
        IntersectionObserver::new_with_options(callback.as_ref().unchecked_ref(), &options)?;

    let nodes = document.query_selector_all("[data-reveal]")?;
    for i in 0..nodes.length() {
        if let Some(node) = nodes.item(i) {
            if let Ok(el) = node.dyn_into::<Element>() {
                observer.observe(&el);
            }
        }
    }

    // The observer and its callback must outlive this function.
    callback.forget();
    std::mem::forget(observer);
    Ok(())
}
