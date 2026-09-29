//! Builds the astronomy blog's pages.
//!
//! Trunk builds one HTML file per run, so it builds only the shared shell,
//! layout.html, into its staging directory as `_layout.html`. This runs next
//! as trunk's post_build hook and writes every real page from it:
//!
//! - `pages/index.html`             -> `/index.html`, the table of contents
//! - `pages/entries/<slug>.html`    -> `/entries/<slug>/index.html`
//!
//! Each page file opens with a comment holding `key: value` fields (title,
//! description; entries add number and date). Entries are wrapped in the
//! shared entry header here, so every entry is laid out the same way, and are
//! listed on the contents page at its `<!-- entries -->` marker.
//!
//! Because every page is the one built layout with its content swapped in,
//! they share its processed stylesheets, the wasm bundle, and in `trunk serve`
//! the live-reload script.

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const LAYOUT: &str = "_layout.html";
const CONTENT_MARKER: &str = "<!-- page:content -->";
const ENTRIES_MARKER: &str = "<!-- entries -->";

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("astronomy-pages: {e}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let staging = PathBuf::from(env_var("TRUNK_STAGING_DIR")?);
    let source = PathBuf::from(env_var("TRUNK_SOURCE_DIR")?);
    let pages = source.join("pages");

    let layout_path = staging.join(LAYOUT);
    let layout = read(&layout_path)?;
    if !layout.contains(CONTENT_MARKER) {
        return Err(format!("layout.html has no {CONTENT_MARKER} marker"));
    }

    let mut entries = Vec::new();
    for path in html_files(&pages.join("entries"))? {
        entries.push(Entry::load(&path, &source)?);
    }
    entries.sort_by_key(|e| e.number);
    for pair in entries.windows(2) {
        if pair[0].number == pair[1].number {
            return Err(format!(
                "entries {} and {} both have number {}",
                pair[0].slug, pair[1].slug, pair[0].number
            ));
        }
    }

    // The contents page.
    let index = Page::load(&pages.join("index.html"), &source)?;
    if !index.body.contains(ENTRIES_MARKER) {
        return Err(format!("pages/index.html has no {ENTRIES_MARKER} marker"));
    }
    let body = index.body.replace(ENTRIES_MARKER, &contents_list(&entries));
    write(&staging.join("index.html"), &fill(&layout, &index.title, &index.description, &body))?;

    for entry in &entries {
        let title = format!("{} · Astronomical Observations", entry.page.title);
        let html = fill(&layout, &title, &entry.page.description, &entry.article());
        write(&staging.join("entries").join(&entry.slug).join("index.html"), &html)?;
    }

    fs::remove_file(&layout_path).map_err(|e| format!("removing {}: {e}", layout_path.display()))?;
    eprintln!("astronomy-pages: contents + {} entries", entries.len());
    Ok(())
}

/// A page file: its fields and its body, with inlined files resolved.
struct Page {
    title: String,
    description: String,
    fields: BTreeMap<String, String>,
    body: String,
}

impl Page {
    fn load(path: &Path, source: &Path) -> Result<Page, String> {
        let text = read(path)?;
        let (fields, body) = front_matter(&text)
            .ok_or_else(|| format!("{} must open with a <!-- key: value --> comment", path.display()))?;
        let field = |k: &str| {
            fields
                .get(k)
                .cloned()
                .ok_or_else(|| format!("{} has no `{k}:` field", path.display()))
        };
        Ok(Page {
            title: field("title")?,
            description: field("description")?,
            body: inline_files(body, source).map_err(|e| format!("{}: {e}", path.display()))?,
            fields,
        })
    }
}

/// One blog entry: pages/entries/<slug>.html.
struct Entry {
    slug: String,
    number: u32,
    date: String,
    page: Page,
}

impl Entry {
    fn load(path: &Path, source: &Path) -> Result<Entry, String> {
        let page = Page::load(path, source)?;
        let slug = path.file_stem().and_then(|s| s.to_str()).unwrap_or_default().to_owned();
        let get = |k: &str| {
            page.fields
                .get(k)
                .cloned()
                .ok_or_else(|| format!("{} has no `{k}:` field", path.display()))
        };
        let number = get("number")?
            .parse()
            .map_err(|_| format!("{}: `number:` must be a whole number", path.display()))?;
        let date = get("date")?;
        Ok(Entry { slug, number, date, page })
    }

    fn url(&self) -> String {
        format!("/entries/{}/", self.slug)
    }

    fn label(&self) -> String {
        format!("Entry {}", roman(self.number))
    }

    /// The entry as it appears on its own page, in the shared entry header.
    fn article(&self) -> String {
        format!(
            r#"      <nav class="page-nav"><a href="/">&lsaquo; Contents</a></nav>

      <article class="entry">
        <div class="entry-date"><span>{label}</span><span>{date}</span></div>

        <h2 class="entry-title">{title}</h2>

        <div class="prose">

{body}

        </div>

        <p class="entry-mark">&mdash; obs. confirmed &#10003;</p>
      </article>"#,
            label = self.label(),
            date = escape(&self.date),
            title = escape(&self.page.title),
            body = self.page.body,
        )
    }
}

/// The table of contents: one line per entry, like the index of a notebook.
fn contents_list(entries: &[Entry]) -> String {
    let mut out = String::from("        <ol class=\"toc\">\n");
    for e in entries {
        out += &format!(
            r#"          <li class="toc-entry">
            <a class="toc-link" href="{url}">
              <span class="toc-num">{label}</span>
              <span class="toc-title">{title}</span>
              <span class="toc-leader" aria-hidden="true"></span>
              <span class="toc-date">{date}</span>
            </a>
            <p class="toc-desc">{desc}</p>
          </li>
"#,
            url = e.url(),
            label = e.label(),
            title = escape(&e.page.title),
            date = escape(&e.date),
            desc = escape(&e.page.description),
        );
    }
    out + "        </ol>"
}

/// The built layout with one page's title, description and content.
fn fill(layout: &str, title: &str, description: &str, content: &str) -> String {
    let mut html = replace_between(layout, "<title>", "</title>", &escape(title));
    html = replace_between(&html, "<meta name=\"description\" content=\"", "\">", &escape(description));
    html.replacen(CONTENT_MARKER, content, 1)
}

fn replace_between(s: &str, open: &str, close: &str, with: &str) -> String {
    match s.find(open) {
        Some(i) => {
            let from = i + open.len();
            match s[from..].find(close) {
                Some(j) => format!("{}{}{}", &s[..from], with, &s[from + j..]),
                None => s.to_owned(),
            }
        }
        None => s.to_owned(),
    }
}

/// Splits a page into its leading comment's `key: value` fields and the rest.
/// Lines in the comment that aren't `lowercase_key: value` are notes to the
/// reader and are skipped.
fn front_matter(text: &str) -> Option<(BTreeMap<String, String>, &str)> {
    let rest = text.trim_start().strip_prefix("<!--")?;
    let end = rest.find("-->")?;
    let mut fields = BTreeMap::new();
    for line in rest[..end].lines() {
        if let Some((k, v)) = line.split_once(':') {
            let k = k.trim();
            if !k.is_empty() && k.chars().all(|c| c.is_ascii_lowercase() || c == '_') {
                fields.insert(k.to_owned(), v.trim().to_owned());
            }
        }
    }
    Some((fields, rest[end + 3..].trim_matches('\n')))
}

/// Replaces `<link data-trunk rel="inline" href="...svg">` with the file, as
/// trunk would: trunk only processes the one file it builds, the layout.
fn inline_files(body: &str, source: &Path) -> Result<String, String> {
    const OPEN: &str = r#"<link data-trunk rel="inline" href=""#;
    let mut out = String::with_capacity(body.len());
    let mut rest = body;
    while let Some(i) = rest.find(OPEN) {
        out += &rest[..i];
        let after = &rest[i + OPEN.len()..];
        let q = after.find('"').ok_or("unterminated inline href")?;
        let href = &after[..q];
        let close = after[q..].find('>').ok_or("unterminated inline link")?;
        if !href.ends_with(".svg") {
            return Err(format!("can only inline .svg files, not {href}"));
        }
        out += read(&source.join(href))?.trim_end();
        rest = &after[q + close + 1..];
    }
    Ok(out + rest)
}

fn roman(mut n: u32) -> String {
    const NUMERALS: [(u32, &str); 13] = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ];
    let mut out = String::new();
    for (value, numeral) in NUMERALS {
        while n >= value {
            out += numeral;
            n -= value;
        }
    }
    out
}

/// For text and attribute values written from the page fields.
fn escape(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn html_files(dir: &Path) -> Result<Vec<PathBuf>, String> {
    let mut files: Vec<PathBuf> = fs::read_dir(dir)
        .map_err(|e| format!("reading {}: {e}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().is_some_and(|x| x == "html"))
        .collect();
    files.sort();
    Ok(files)
}

fn env_var(name: &str) -> Result<String, String> {
    env::var(name).map_err(|_| format!("{name} is not set; this runs as trunk's post_build hook"))
}

fn read(path: &Path) -> Result<String, String> {
    fs::read_to_string(path).map_err(|e| format!("reading {}: {e}", path.display()))
}

fn write(path: &Path, text: &str) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("creating {}: {e}", dir.display()))?;
    }
    fs::write(path, text).map_err(|e| format!("writing {}: {e}", path.display()))
}
