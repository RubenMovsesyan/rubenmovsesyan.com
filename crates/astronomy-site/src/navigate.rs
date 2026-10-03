//! Moving between the blog's pages without loading a new page.
//!
//! Every page is layout.html with a different notebook page inside (see
//! crates/astronomy-pages), so going from one to another only needs that
//! part, the title and the description swapped. Doing it in place keeps
//! everything else alive -- the starfield, the telescope's GPU renderer,
//! this wasm itself -- instead of downloading and restarting it all.
//!
//! - Hovering, focusing or touching a link to another page fetches that
//!   page and parses it, ready to drop in (its figures and equations are
//!   inline in it, so they come too).
//! - Clicking it swaps the page in at once, and updates the URL and title;
//!   back and forward swap back the same way, scroll position included.
//! - A fetched page not hovered for KEEP_MS is dropped.
//!
//! Anything else -- a modified click, another site, a same-page #fig link,
//! a failed fetch -- is left to the browser, and without wasm every link is
//! an ordinary page load.

use std::cell::RefCell;
use std::collections::HashMap;

use js_sys::{Date, Object, Promise, Reflect};
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use wasm_bindgen_futures::{future_to_promise, spawn_local, JsFuture};
use web_sys::{
    Document, DomParser, Element, Event, MouseEvent, PopStateEvent, Response, ScrollBehavior,
    ScrollRestoration, ScrollToOptions, SupportedType, Url,
};

/// A prefetched page is dropped when no link to it was hovered for this long.
const KEEP_MS: f64 = 30_000.0;
/// How often to look for pages to drop.
const SWEEP_MS: i32 = 5_000;
/// How long scrolling must pause before the position is noted in the history.
const NOTE_SCROLL_MS: i32 = 150;

/// A page fetched ahead of a click: a promise of its parsed Document.
struct Prefetch {
    document: Promise,
    last_hover: f64,
}

/// A page swapped out, kept for back and forward: its notebook page as it
/// was (links already wired), title and description.
struct Shown {
    page: Element,
    title: String,
    description: String,
}

thread_local! {
    static PREFETCHED: RefCell<HashMap<String, Prefetch>> = RefCell::new(HashMap::new());
    static LEFT: RefCell<HashMap<String, Shown>> = RefCell::new(HashMap::new());
    /// The path of the page on screen.
    static CURRENT: RefCell<String> = const { RefCell::new(String::new()) };
    /// The pending note of the scroll position, if scrolling hasn't paused.
    static SCROLL_NOTE: std::cell::Cell<Option<i32>> = const { std::cell::Cell::new(None) };
}

pub fn mount(document: &Document) -> Result<(), JsValue> {
    let window = crate::window();
    CURRENT.with(|c| *c.borrow_mut() = window.location().pathname().unwrap_or_default());
    // Scroll positions are put back by us, after the swap.
    if let Ok(history) = window.history() {
        let _ = history.set_scroll_restoration(ScrollRestoration::Manual);
    }

    // Prefetch on hover, keyboard focus, or the touch that starts a tap.
    for name in ["pointerover", "focusin", "touchstart"] {
        let cb = Closure::wrap(Box::new(|e: Event| {
            if let Some(url) = e.target().and_then(|t| page_link(&t)) {
                let _ = prefetch(&url.pathname());
            }
        }) as Box<dyn FnMut(Event)>);
        document.add_event_listener_with_callback(name, cb.as_ref().unchecked_ref())?;
        cb.forget();
    }

    let on_click = Closure::wrap(Box::new(|e: MouseEvent| {
        if e.default_prevented() || e.button() != 0 || e.ctrl_key() || e.meta_key() || e.shift_key() || e.alt_key() {
            return;
        }
        let Some(url) = e.target().and_then(|t| page_link(&t)) else { return };
        e.prevent_default();
        spawn_local(go(url, true, None));
    }) as Box<dyn FnMut(MouseEvent)>);
    document.add_event_listener_with_callback("click", on_click.as_ref().unchecked_ref())?;
    on_click.forget();

    let on_pop = Closure::wrap(Box::new(|e: PopStateEvent| {
        let window = crate::window();
        let Ok(href) = window.location().href() else { return };
        let Ok(url) = Url::new(&href) else { return };
        if CURRENT.with(|c| *c.borrow() == url.pathname()) {
            // Only the #hash changed (a figure reference): the page stays.
            return;
        }
        let scroll = Reflect::get(&e.state(), &"scroll".into()).ok().and_then(|v| v.as_f64());
        spawn_local(go(url, false, scroll));
    }) as Box<dyn FnMut(PopStateEvent)>);
    window.add_event_listener_with_callback("popstate", on_pop.as_ref().unchecked_ref())?;
    on_pop.forget();

    // Keep the scroll position in the current history entry, so back and
    // forward can put it back. (By the time the browser says a page is being
    // left by back or forward, its entry can no longer be written.)
    let note = Closure::wrap(Box::new(|| {
        SCROLL_NOTE.with(|n| n.set(None));
        let window = crate::window();
        if let Ok(history) = window.history() {
            let _ = history.replace_state(&scroll_state(window.scroll_y().unwrap_or(0.0)), "");
        }
    }) as Box<dyn FnMut()>);
    let note_fn: js_sys::Function = note.as_ref().unchecked_ref::<js_sys::Function>().clone();
    note.forget();
    let on_scroll = Closure::wrap(Box::new(move || {
        let window = crate::window();
        if let Some(pending) = SCROLL_NOTE.with(|n| n.take()) {
            window.clear_timeout_with_handle(pending);
        }
        if let Ok(handle) = window.set_timeout_with_callback_and_timeout_and_arguments_0(&note_fn, NOTE_SCROLL_MS) {
            SCROLL_NOTE.with(|n| n.set(Some(handle)));
        }
    }) as Box<dyn FnMut()>);
    window.add_event_listener_with_callback("scroll", on_scroll.as_ref().unchecked_ref())?;
    on_scroll.forget();

    let sweep = Closure::wrap(Box::new(|| {
        let now = Date::now();
        PREFETCHED.with(|p| p.borrow_mut().retain(|_, f| now - f.last_hover < KEEP_MS));
    }) as Box<dyn FnMut()>);
    window.set_interval_with_callback_and_timeout_and_arguments_0(sweep.as_ref().unchecked_ref(), SWEEP_MS)?;
    sweep.forget();
    Ok(())
}

/// The URL of a link to another of this site's pages, if `target` is in one.
fn page_link(target: &web_sys::EventTarget) -> Option<Url> {
    let link = target.dyn_ref::<Element>()?.closest("a[href]").ok()??;
    if link.has_attribute("download") || link.get_attribute("target").is_some_and(|t| t != "_self") {
        return None;
    }
    let window = crate::window();
    let url = Url::new_with_base(&link.get_attribute("href")?, &window.location().href().ok()?).ok()?;
    if url.origin() != window.location().origin().ok()? {
        return None;
    }
    // Pages are directories or .html files; anything else is a file.
    let path = url.pathname();
    let last = path.rsplit('/').next().unwrap_or_default();
    if !(last.is_empty() || last.ends_with(".html") || !last.contains('.')) {
        return None;
    }
    // A link within the page on screen (#fig-3) is the browser's.
    if CURRENT.with(|c| *c.borrow() == path) {
        return None;
    }
    Some(url)
}

/// Start fetching and parsing a page, or note that it was wanted again.
fn prefetch(path: &str) -> Promise {
    let now = Date::now();
    PREFETCHED.with(|p| {
        let mut p = p.borrow_mut();
        if let Some(f) = p.get_mut(path) {
            f.last_hover = now;
            return f.document.clone();
        }
        let url = path.to_owned();
        let document = future_to_promise(async move {
            let response: Response = JsFuture::from(crate::window().fetch_with_str(&url)).await?.dyn_into()?;
            if !response.ok() {
                return Err(format!("{url}: {}", response.status()).into());
            }
            let text = JsFuture::from(response.text()?).await?.as_string().unwrap_or_default();
            let doc = DomParser::new()?.parse_from_string(&text, SupportedType::TextHtml)?;
            if doc.query_selector(".page")?.is_none() {
                return Err(format!("{url}: not one of the notebook's pages").into());
            }
            Ok(doc.into())
        });
        // A failed fetch isn't kept: the next hover tries again.
        let failed = path.to_owned();
        let on_fail = Closure::once(move |_: JsValue| {
            PREFETCHED.with(|p| p.borrow_mut().remove(&failed));
        });
        let _ = document.catch(&on_fail);
        on_fail.forget();
        p.insert(path.to_owned(), Prefetch { document: document.clone(), last_hover: now });
        document
    })
}

/// Show the page at `url`. `push` adds it to the history (a click); `scroll`
/// is where to put the page (back/forward), otherwise its top or its #hash.
async fn go(url: Url, push: bool, scroll: Option<f64>) {
    let path = url.pathname();
    if let Err(e) = swap(&url, push, scroll).await {
        // Whatever went wrong, the browser can still just load the page.
        web_sys::console::warn_1(&format!("navigate: loading {path} normally ({e:?})").into());
        let _ = crate::window().location().assign(&url.href());
    }
}

async fn swap(url: &Url, push: bool, scroll: Option<f64>) -> Result<(), JsValue> {
    let window = crate::window();
    let document = window.document().ok_or("no document")?;
    let path = url.pathname();

    // A page left earlier comes back as it was; otherwise the prefetch (or
    // a fetch now, if it wasn't hovered) supplies it.
    let (incoming, fresh) = match LEFT.with(|l| l.borrow_mut().remove(&path)) {
        Some(shown) => (shown, false),
        None => {
            let fetched: Document = JsFuture::from(prefetch(&path)).await?.dyn_into()?;
            let page = fetched.query_selector(".page")?.ok_or("no .page")?;
            let page: Element = document.import_node_with_deep(&page, true)?.dyn_into()?;
            let description = fetched
                .query_selector("meta[name=description]")?
                .and_then(|m| m.get_attribute("content"))
                .unwrap_or_default();
            (Shown { page, title: fetched.title(), description }, true)
        }
    };

    let current = document.query_selector(".page")?.ok_or("no .page on screen")?;
    let description = document.query_selector("meta[name=description]")?;
    if push {
        // Remember where this page was scrolled to, for coming back.
        if let Ok(history) = window.history() {
            let _ = history.replace_state(&scroll_state(window.scroll_y().unwrap_or(0.0)), "");
            history.push_state_with_url(&scroll_state(0.0), "", Some(&url.href()))?;
        }
    }
    let leaving = CURRENT.with(|c| std::mem::replace(&mut *c.borrow_mut(), path.clone()));
    LEFT.with(|l| {
        l.borrow_mut().insert(leaving, Shown {
            page: current.clone(),
            title: document.title(),
            description: description.as_ref().and_then(|m| m.get_attribute("content")).unwrap_or_default(),
        })
    });

    current.replace_with_with_node_1(&incoming.page)?;
    document.set_title(&incoming.title);
    if let Some(meta) = description {
        meta.set_attribute("content", &incoming.description)?;
    }
    if fresh {
        crate::figref::attach_in(&incoming.page)?;
    }

    // Where to look: back where it was, at its #figure, or its top. Instant,
    // as a page load would be, not the page's smooth scrolling.
    let hash = url.hash();
    let target = (hash.len() > 1).then(|| document.get_element_by_id(&hash[1..])).flatten();
    match (scroll, target) {
        (Some(y), _) => scroll_to(y),
        (None, Some(t)) => crate::figref::centre(&t),
        (None, None) => scroll_to(0.0),
    }
    Ok(())
}

fn scroll_state(y: f64) -> JsValue {
    let state = Object::new();
    let _ = Reflect::set(&state, &"scroll".into(), &y.into());
    state.into()
}

fn scroll_to(y: f64) {
    let options = ScrollToOptions::new();
    options.set_top(y);
    options.set_behavior(ScrollBehavior::Instant);
    crate::window().scroll_to_with_scroll_to_options(&options);
}
