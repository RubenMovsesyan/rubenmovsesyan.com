//! Figure and equation references (`a.figref`) scroll their target to the
//! middle of the screen rather than the top, so the text around it stays in
//! view.
//!
//! Without wasm the links still work as plain anchors, landing at the top.

use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{Document, Element, Event, ScrollIntoViewOptions, ScrollLogicalPosition};

pub fn mount(document: &Document) -> Result<(), JsValue> {
    let links = document.query_selector_all("a.figref[href^='#']")?;
    for i in 0..links.length() {
        let Some(node) = links.item(i) else { continue };
        let link: Element = node.dyn_into()?;
        let href = link.get_attribute("href").unwrap_or_default();

        let doc = document.clone();
        let onclick = Closure::wrap(Box::new(move |event: Event| {
            let Some(target) = doc.get_element_by_id(&href[1..]) else { return };
            event.prevent_default();
            centre(&target);
            // Keep the URL and the back button behaving like the plain link.
            if let Ok(history) = crate::window().history() {
                let _ = history.push_state_with_url(&JsValue::NULL, "", Some(&href));
            }
        }) as Box<dyn FnMut(Event)>);
        link.add_event_listener_with_callback("click", onclick.as_ref().unchecked_ref())?;
        // Lives as long as the page.
        onclick.forget();
    }

    // A page opened at #eq-1 has already been jumped to the top of it by the
    // browser; move it to the middle to match.
    let hash = crate::window().location().hash().unwrap_or_default();
    if hash.len() > 1 {
        if let Some(target) = document.get_element_by_id(&hash[1..]) {
            centre(&target);
        }
    }
    Ok(())
}

fn centre(target: &Element) {
    // No behavior given, so the stylesheet decides: smooth, or instant under
    // prefers-reduced-motion (base.css).
    let options = ScrollIntoViewOptions::new();
    options.set_block(ScrollLogicalPosition::Center);
    target.scroll_into_view_with_scroll_into_view_options(&options);
}
