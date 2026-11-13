"""HTML reports: index.html (one line per check) and one page per check, for reading in any browser.

Layout of the report folder: index.html, html/<check>.html, txt/<check>.txt (the text reports, written by cli).

The pages are static files (no server, no internet): styles and scripts are inline, the problems of a check
are embedded as JSON and shown in pages of PAGE_SIZE blocks, with a search box and an errors-only filter.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from checker.paratext_link import PROTOCOL
from checker.stages import FIRST_STAGES, GROUPS, STAGES, group_of, stage_number

PAGE_SIZE = 200  # blocks shown at once; large reports (60 000 blocks) would make the browser slow
HTML_FOLDER = "html"
TXT_FOLDER = "txt"


@dataclass
class Problem:
    severity: str  # "error" / "warning"
    message: str
    count: int
    context: str
    where: str
    item: str = ""  # what was found (a word, a character, a pattern): marked in the context
    new: int = 0  # places that the previous run did not have


@dataclass
class CheckResult:
    name: str
    description: str
    errors: int = 0
    warnings: int = 0
    skipped: str = ""  # reason if the check could not run
    problems: list[Problem] = field(default_factory=list)
    note: str = ""  # what the check did not list and why
    new: int | None = None  # places new since the previous run; None = not compared
    fixed: int | None = None  # places of the previous run that are gone
    accepted: int = 0  # places accepted in an earlier report, left out


STYLE = """
:root{--bg:#f7f8f6;--card:#fff;--fg:#1c2421;--muted:#5d6a64;--line:#dbe1dc;--accent:#2f6b55;
--err:#b3261e;--err-bg:#fbeae8;--warn:#875a00;--warn-bg:#fdf4de;--ok:#2f6b55}
@media (prefers-color-scheme:dark){:root{--bg:#141917;--card:#1c2320;--fg:#e3eae5;--muted:#9aa8a0;
--line:#2e3833;--accent:#7cc5a6;--err:#ff8a80;--err-bg:#3a1f1d;--warn:#f0c062;--warn-bg:#352c15;--ok:#7cc5a6}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0 0 4px}
a{color:var(--accent)}
.muted{color:var(--muted)}
.desc{max-width:75ch}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);
font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
td.n,th.n{text-align:right}
tr.stage th{background:var(--bg);padding-top:14px;font-size:.95rem}
tr.group th{background:var(--bg);font-weight:normal;font-style:italic;padding-left:18px}
.first{background:var(--err-bg);color:var(--err);border-left:4px solid var(--err);padding:8px 12px;max-width:75ch}
.e{color:var(--err);font-weight:600}.w{color:var(--warn);font-weight:600}.z{color:var(--muted)}
.tools{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:16px 0}
input[type=search]{flex:1;min-width:200px;padding:7px 10px;border:1px solid var(--line);border-radius:4px;
background:var(--card);color:var(--fg);font:inherit}
.block{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:4px;
padding:10px 14px;margin:0 0 10px}
.block.error{border-left-color:var(--err)}
.block h3{margin:0 0 4px;font-size:1rem;font-weight:600;overflow-wrap:anywhere}
.block .row{font-size:.92rem;overflow-wrap:anywhere}
.block .label{display:inline-block;min-width:4.5em;color:var(--muted)}
a.ref{text-decoration:none;border-bottom:1px dotted var(--accent)}a.ref:hover{border-bottom-style:solid}
.text{font-family:Consolas,monospace;background:var(--bg);padding:1px 4px;border-radius:3px}
button{font:inherit;padding:6px 14px;border:1px solid var(--line);border-radius:4px;background:var(--card);
color:var(--fg);cursor:pointer}
.scroll{overflow-x:auto}
code.item{font-family:Consolas,monospace;font-weight:400;background:#1f2933;color:#f5f7f6;padding:1px 6px;
border-radius:4px;cursor:copy;white-space:pre-wrap}
code.item:hover{outline:2px solid var(--accent)}
.sp{background:rgba(240,192,98,.55);border-radius:2px}
mark{background:var(--warn-bg);color:inherit;font-weight:700;outline:1px solid var(--warn);border-radius:2px}
#copied{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#1f2933;color:#f5f7f6;
padding:6px 14px;border-radius:4px;opacity:0;transition:opacity .2s;pointer-events:none}
#copied.on{opacity:1}
.new{display:inline-block;background:var(--accent);color:var(--card);font-size:.75rem;font-weight:700;
padding:0 6px;border-radius:3px;margin-left:6px;vertical-align:middle}
.block{position:relative}
.block h3{padding-right:6.5em}
a.accept{position:absolute;top:8px;right:10px;font-size:.85rem;text-decoration:none;border:1px solid var(--line);
border-radius:4px;padding:1px 8px;color:var(--muted)}
a.accept:hover{color:var(--accent);border-color:var(--accent)}
.block.done{opacity:.45}
.block.done a.accept{opacity:1}
@media (prefers-color-scheme:dark){code.item{background:#000;border:1px solid var(--line)}}
"""

# Raw string: the regular expressions below keep their backslashes.
SCRIPT = r"""
const data = JSON.parse(document.getElementById('data').textContent);
const list = document.getElementById('list'), more = document.getElementById('more'),
      info = document.getElementById('info'), search = document.getElementById('search'),
      errorsOnly = document.getElementById('errors-only'), newOnly = document.getElementById('new-only');
let shown = 0, matches = [];
function esc(s){return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
// "MAT 27:46, 28:1 (2×); MRK 15:34": each chapter:verse becomes a link that makes Paratext show the verse
// (checker/paratext_link.py); places without a book stay text. 0:0 (the introduction) opens 1:0: Paratext has the
// introduction there and does not accept chapter 0.
function refLink(ref){
  return `${LINK.protocol}:${encodeURIComponent(LINK.project)}/${encodeURIComponent(ref).replace(/%3A/g, ':')}`
       + (LINK.vrs ? `?vrs=${encodeURIComponent(LINK.vrs)}` : '');
}
function where(text){
  if (!LINK.project) return esc(text);
  return text.split('; ').map(group => {
    const m = /^([0-9A-Z]{3}) (.+)$/.exec(group);
    if (!m) return esc(group);
    return esc(m[1]) + ' ' + m[2].split(', ').map(part => {
      const v = /^(\d+):(\d+)/.exec(part);
      if (!v) return esc(part);
      const target = +v[1] ? `${+v[1]}:${+v[2]}` : '1:0';
      return `<a class="ref" href="${esc(refLink(`${m[1]} ${target}`))}" title="Show in Paratext">${esc(part)}</a>`;
    }).join(', ');
  }).join('; ');
}
// Spaces that cannot be seen (no-break, narrow, zero width) are marked; the real character stays for copying.
const INVISIBLE = /[  -‍ ⁠﻿]/;
function visible(s, edges){
  let out = '';
  [...s].forEach((c, k) => {
    const edge = edges && c === ' ' && (k === 0 || k === s.length - 1);
    out += (INVISIBLE.test(c) || edge)
      ? `<span class="sp" title="U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}">${c}</span>`
      : esc(c);
  });
  return out;
}
// 'something' in a message = what was found: shown without the quotes, on a dark background, copied on click.
const QUOTED = /'(.+?)'(?=[\s,.;:)\]!?]|$)/g;
function chips(message){
  let out = '', last = 0;
  for (const m of message.matchAll(QUOTED)) {
    out += esc(message.slice(last, m.index))
         + `<code class="item" title="Click to copy" data-copy="${esc(m[1])}">${visible(m[1], true)}</code>`;
    last = m.index + m[0].length;
  }
  return out + esc(message.slice(last));
}
// The found item is marked in the text around it.
function context(p){
  let item = p.item || '', at = item ? p.context.indexOf(item) : -1;
  if (at < 0 && item.includes('_')) {  // a punctuation pattern: _ stands for a space
    item = item.replace(/^_|_$/g, '').replace(/_/g, ' ');
    at = item ? p.context.indexOf(item) : -1;
  }
  if (at < 0) return visible(p.context, false);
  return visible(p.context.slice(0, at), false) + `<mark>${visible(item, false)}</mark>`
       + visible(p.context.slice(at + item.length), false);
}
// Accept = "this is not a problem": a link that this program (scripturechecker:accept, checker/history.py) turns
// into a line of accepted.json; the next reports leave the problem out. The page remembers the click only for the
// look (the real list is the file).
function runFolder(){
  if (location.protocol !== 'file:') return LINK.run || '';
  const url = new URL('..', location.href);
  let path = decodeURIComponent(url.pathname).replace(/\/$/, '');
  if (/^\/[A-Za-z]:/.test(path)) path = path.slice(1);
  if (url.host) path = '//' + url.host + path;
  return path.replace(/\//g, '\\');
}
const RUN = runFolder(), STORE = 'accepted ' + RUN + ' ' + CHECK;
let done = new Set();
try { done = new Set(JSON.parse(localStorage.getItem(STORE) || '[]')); } catch (e) {}
function remember(){ try { localStorage.setItem(STORE, JSON.stringify([...done])); } catch (e) {} }
function acceptLink(p, undo){
  return `${LINK.protocol}:accept?run=${encodeURIComponent(RUN)}&check=${encodeURIComponent(CHECK)}`
       + `&severity=${encodeURIComponent(p.severity)}&message=${encodeURIComponent(p.message)}` + (undo ? '&undo=1' : '');
}
function acceptButton(p, i){
  const undo = done.has(i);
  return `<a class="accept" data-i="${i}" href="${esc(acceptLink(p, undo))}" `
       + `title="${undo ? 'Show it again in the next reports' : 'Not a problem: hide it in the next reports'}">`
       + `${undo ? 'Undo' : 'Accept'}</a>`;
}
function newBadge(p){
  if (!p.new) return '';
  return `<span class="new" title="Not in the previous report">${p.new === p.count ? 'NEW' : `NEW: ${p.new}`}</span>`;
}
function block(p, i){
  const rows = [];
  if (p.count > 1) rows.push(`<div class="row"><span class="label">Found:</span> ${p.count} times</div>`);
  if (p.context) rows.push(`<div class="row"><span class="label">Text:</span> <span class="text">${context(p)}</span></div>`);
  rows.push(`<div class="row"><span class="label">Where:</span> ${where(p.where)}</div>`);
  return `<div class="block ${p.severity}${done.has(i) ? ' done' : ''}" data-i="${i}">${RUN ? acceptButton(p, i) : ''}`
       + `<h3>${i + 1}. ${chips(p.message)}${newBadge(p)}</h3>${rows.join('')}</div>`;
}
const toast = document.createElement('div'); toast.id = 'copied'; toast.textContent = 'Copied';
document.body.appendChild(toast);
function copied(){ toast.classList.add('on'); setTimeout(() => toast.classList.remove('on'), 900); }
function copyText(text){
  const fallback = () => {
    const area = document.createElement('textarea'); area.value = text; document.body.appendChild(area);
    area.select(); document.execCommand('copy'); area.remove(); copied();
  };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(copied, fallback);
  else fallback();
}
list.addEventListener('click', e => {
  const chip = e.target.closest('code.item');
  if (chip) copyText(chip.dataset.copy);
  const button = e.target.closest('a.accept');
  if (button) {
    // The browser opens the link first; then the button turns into Undo (or back).
    const i = +button.dataset.i;
    setTimeout(() => {
      if (done.has(i)) done.delete(i); else done.add(i);
      remember();
      const div = button.closest('.block');
      div.classList.toggle('done', done.has(i));
      button.outerHTML = acceptButton(data[i], i);
    }, 0);
  }
});
function render(){
  const q = search.value.trim().toLowerCase();
  matches = data.map((p, i) => [p, i]).filter(([p]) =>
    (!errorsOnly.checked || p.severity === 'error') && (!newOnly || !newOnly.checked || p.new) &&
    (!q || (p.message + ' ' + p.context + ' ' + p.where).toLowerCase().includes(q)));
  list.innerHTML = ''; shown = 0; showMore();
}
function showMore(){
  const next = matches.slice(shown, shown + PAGE);
  list.insertAdjacentHTML('beforeend', next.map(([p, i]) => block(p, i)).join(''));
  shown += next.length;
  info.textContent = `Showing ${shown} of ${matches.length} problems`;
  more.hidden = shown >= matches.length;
}
search.addEventListener('input', render); errorsOnly.addEventListener('change', render);
if (newOnly) newOnly.addEventListener('change', render);
more.addEventListener('click', showMore);
render();
"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{html.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n<main>\n{body}\n"
            f"</main>\n</body>\n</html>\n")


def _counts(result: CheckResult, compared: bool) -> str:
    if result.skipped:
        # "!" instead of 0: the check had nothing to check with (a file or a list of the project is missing).
        reason = html.escape(result.skipped)
        short = html.escape(result.skipped.split(". ")[0].rstrip("."))
        return (f'<td class="n" colspan="{5 if compared else 3}" title="{reason}"><span class="e">!</span> '
                f'<span class="z">{short}</span></td>')
    errors = f'<span class="e">{result.errors}</span>' if result.errors else '<span class="z">0</span>'
    warnings = f'<span class="w">{result.warnings}</span>' if result.warnings else '<span class="z">0</span>'
    cells = f'<td class="n">{errors}</td><td class="n">{warnings}</td><td class="n">{len(result.problems)}</td>'
    if compared:
        if result.new is None:
            cells += '<td class="n z" colspan="2" title="Not in the previous run">-</td>'
        else:
            new = f'<span class="new">+{result.new}</span>' if result.new else '<span class="z">0</span>'
            fixed = f'<span class="w">-{result.fixed}</span>' if result.fixed else '<span class="z">0</span>'
            cells += f'<td class="n">{new}</td><td class="n">{fixed}</td>'
    return cells


def _first_stages_note(results: list[CheckResult]) -> str:
    """A line on top when an early stage has errors and later stages were checked too: fix the early ones first."""
    early = [r for r in results if 0 < stage_number(r.name) <= FIRST_STAGES and r.errors]
    if not early or all(0 < stage_number(r.name) <= FIRST_STAGES for r in results):
        return ""
    names = ", ".join(html.escape(r.name) for r in early)
    return (f"<p class=\"first\">Units 1-{FIRST_STAGES} have errors ({names}). Fix them first: "
            "they can cause false problems in the later units.</p>\n")


def _index_rows(results: list[CheckResult], compared: bool = False) -> str:
    rows, stage, group = [], None, ""
    width = 7 if compared else 5
    for r in results:
        number = stage_number(r.name)
        if number != stage:
            stage, group = number, ""
            title = STAGES[number - 1][0] if number else "Other checks"
            rows.append(f'<tr class="stage"><th colspan="{width}">{html.escape(title)}</th></tr>')
        # A group of a unit has its own heading; its checks are numbered in the order to fix them.
        if group_of(r.name) != group:
            group = group_of(r.name)
            if group:
                rows.append(f'<tr class="group"><th colspan="{width}">{html.escape(group)}: fix in this order</th></tr>')
        step = next((f"{checks.index(r.name) + 1}. " for _, title, checks in GROUPS
                     if title == group and r.name in checks), "")
        rows.append(f'<tr><td>{step}<a href="{HTML_FOLDER}/{html.escape(r.name)}.html">{html.escape(r.name)}</a></td>'
                    f'{_counts(r, compared)}<td><a class="muted" href="{TXT_FOLDER}/{html.escape(r.name)}.txt">txt</a></td></tr>')
    return "\n".join(rows)


def write_index(report_dir: Path, project: str, results: list[CheckResult], location_help: str,
                previous: str = "") -> Path:
    """One row per check, under the title of its stage (results are expected in stage order).

    `previous`: the name of the run folder the results were compared with ("" = none)."""
    compared = bool(previous) and any(r.new is not None for r in results)
    rows = _index_rows(results, compared)
    errors = sum(r.errors for r in results)
    warnings = sum(r.warnings for r in results)
    accepted = sum(r.accepted for r in results)
    since = (f"<p class=\"muted\">New and Fixed: compared with the run of {html.escape(previous)} "
             "(only the checks and books of both runs).</p>\n" if compared else "")
    hidden = (f"<p class=\"muted\">{accepted} places you accepted earlier are hidden "
              "(to show them again: the Accepted button in the window).</p>\n" if accepted else "")
    body = (f"<h1>{html.escape(project)}</h1>\n"
            f"<p class=\"muted\">Checked {datetime.now():%Y-%m-%d %H:%M}. "
            f"Errors: {errors}, warnings: {warnings}. Click a check to see its problems.</p>\n"
            + since + hidden + _first_stages_note(results) +
            f"<p><a href=\"{TXT_FOLDER}/\">Open the folder of text reports (txt)</a> "
            f"<span class=\"muted\">&middot; <a class=\"muted\" href=\"{HTML_FOLDER}/\">html</a></span></p>\n"
            f"<p class=\"muted desc\">{html.escape(location_help)}</p>\n"
            "<div class=\"scroll\"><table>\n<thead><tr><th>Check</th><th class=\"n\">Errors</th>"
            "<th class=\"n\">Warnings</th><th class=\"n\">Different problems</th>"
            + ("<th class=\"n\">New</th><th class=\"n\">Fixed</th>" if compared else "")
            + "<th></th></tr></thead>\n"
            f"<tbody>\n{rows}\n</tbody>\n</table></div>")
    path = report_dir / "index.html"
    path.write_text(_page(f"{project} checks", body), encoding="utf-8")
    return path


def write_check_page(report_dir: Path, project: str, result: CheckResult, location_help: str,
                     link: dict[str, str] | None = None) -> Path:
    """`link`: {"project": Paratext short name, "vrs": Settings.xml Versification} for links to Paratext."""
    txt = f"../{TXT_FOLDER}/{html.escape(result.name)}.txt"
    header = (f"<p><a href=\"../index.html\">&larr; All checks of {html.escape(project)}</a> "
              f"<span class=\"muted\">&middot; <a class=\"muted\" href=\"{txt}\">txt</a></span></p>\n"
              f"<h1>{html.escape(result.name)}</h1>\n<p class=\"desc\">{html.escape(result.description)}</p>\n")
    if result.skipped:
        body = header + f"<p class=\"muted\">{html.escape(result.skipped)}</p>"
    else:
        data = json.dumps([p.__dict__ for p in result.problems], ensure_ascii=False).replace("</", "<\\/")
        body = (header
                + f"<p>Errors: <span class=\"e\">{result.errors}</span>, warnings: "
                  f"<span class=\"w\">{result.warnings}</span>. "
                  f"<span class=\"muted\">{html.escape(location_help)}</span></p>\n"
                + (f"<p class=\"desc\">{html.escape(result.note)}</p>\n" if result.note else "")
                + "<div class=\"tools\"><input type=\"search\" id=\"search\" placeholder=\"Search in this report\">"
                  "<label><input type=\"checkbox\" id=\"errors-only\"> Errors only</label>"
                + ("<label><input type=\"checkbox\" id=\"new-only\"> Only new</label>"
                   if result.new else "")
                + "<span class=\"muted\">Accept = not a problem: hidden in the next reports.</span>"
                  "<span class=\"muted\" id=\"info\"></span></div>\n"
                  "<div id=\"list\"></div>\n<button id=\"more\" type=\"button\" hidden>Show more</button>\n"
                  f"<script type=\"application/json\" id=\"data\">{data}</script>\n"
                  f"<script>const PAGE = {PAGE_SIZE}; const LINK = {_link_json(link, report_dir)}; "
                  f"const CHECK = {json.dumps(result.name)};{SCRIPT}</script>")
    path = report_dir / HTML_FOLDER / f"{result.name}.html"
    path.write_text(_page(f"{result.name} - {project}", body), encoding="utf-8")
    return path


def _link_json(link: dict[str, str] | None, run: Path | None = None) -> str:
    """Data of the links: to Paratext (project, versification) and to accept a problem (the run folder, used when
    the page is not opened from the disk)."""
    data = {"protocol": PROTOCOL, "project": "", "vrs": "", "run": str(run.resolve()) if run else "", **(link or {})}
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def write_html_report(report_dir: Path, project: str, results: list[CheckResult], location_help: str,
                      link: dict[str, str] | None = None, previous: str = "") -> Path:
    """Write index.html and one page per check; returns the path of index.html."""
    (report_dir / HTML_FOLDER).mkdir(parents=True, exist_ok=True)
    for result in results:
        write_check_page(report_dir, project, result, location_help, link)
    return write_index(report_dir, project, results, location_help, previous)
