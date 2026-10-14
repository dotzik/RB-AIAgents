"""Kapitoly security/*.md jako jedna HTML stránka se záložkami.

    uv run --no-project --with markdown python security/build_html.py

Bez argumentů čte kapitoly vedle sebe a píše `bezpecnostni-navrh.html`.
`--artifact` vynechá načtení mermaid knihovny (artifact kreslí diagramy sám).
"""
import html
import pathlib
import re
import sys

import markdown

args = [a for a in sys.argv[1:] if not a.startswith("--")]
ARTIFACT = "--artifact" in sys.argv
HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(args[0]) if args else HERE
OUT = pathlib.Path(args[1]) if len(args) > 1 else HERE / "bezpecnostni-navrh.html"
MERMAID = (
    ""
    if ARTIFACT
    else '<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>\n'
    "<script>mermaid.initialize({ startOnLoad: false, theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default' });</script>\n"
)

files = ["README.md"] + sorted(p.name for p in SRC.glob("0*.md"))
tab_id = {f: ("prehled" if f == "README.md" else "k" + f[:2]) for f in files}
labels = {"README.md": "Přehled"}


def convert(text: str) -> str:
    text = text.replace("[← Rozcestník](README.md)\n\n", "")
    blocks = []

    def keep_mermaid(m):
        blocks.append(m.group(1))
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}\n\n"

    text = re.sub(r"```mermaid\n(.*?)```", keep_mermaid, text, flags=re.S)
    out = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    for i, b in enumerate(blocks):
        out = out.replace(
            f"<p>MERMAIDBLOCK{i}</p>",
            f'<div class="diagram"><pre class="mermaid">{html.escape(b)}</pre></div>',
        )
    for f, t in tab_id.items():
        out = out.replace(f'href="{f}"', f'href="#{t}" data-tab="{t}"')
    out = out.replace("<table>", '<div class="tbl"><table>').replace("</table>", "</table></div>")
    return out


sections, nav = [], []
for f in files:
    text = (SRC / f).read_text(encoding="utf-8")
    title = re.search(r"^# (.+)$", text, flags=re.M).group(1)
    label = labels.get(f, title)
    body = convert(text)
    if f == "README.md":
        body = re.sub(r"<h1>.*?</h1>", "", body, count=1)
    t = tab_id[f]
    nav.append(f'<a href="#{t}" data-tab="{t}">{html.escape(label)}</a>')
    sections.append(f'<section id="{t}" class="tab" hidden>{body}</section>')

main_title = re.search(r"^# (.+)$", (SRC / "README.md").read_text(encoding="utf-8"), flags=re.M).group(1)

HEAD = "" if ARTIFACT else (
    '<!doctype html>\n<html lang="cs">\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
)

page = HEAD + f"""<title>Bezpečnost timeagenta</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:opsz,wght@8..60,600&family=JetBrains+Mono:wght@400&display=swap">
<style>
body {{ margin: 0; }}
/* Layout: úzký čtecí sloupec, nahoře lepící lišta kapitol; tabulky scrollují samy */
:root {{
  --bg: #f6f7f9; --surface: #ffffff; --fg: #1b2330; --muted: #5a6577;
  --line: #dde2ea; --accent: #2f5d8a; --accent-soft: #e6eef7; --code-bg: #eef1f5;
  --display: "Source Serif 4", Georgia, serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #12161d; --surface: #191f28; --fg: #e3e8ef; --muted: #9aa5b5;
  --line: #2b3441; --accent: #8db8e3; --accent-soft: #1f2d3d; --code-bg: #212a36; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #12161d; --surface: #191f28; --fg: #e3e8ef; --muted: #9aa5b5;
  --line: #2b3441; --accent: #8db8e3; --accent-soft: #1f2d3d; --code-bg: #212a36; color-scheme: dark }}
body {{ background: var(--bg); color: var(--fg); font: 16px/1.6 var(--body); }}
header {{ padding-inline: 16px; padding-block: 28px 8px; max-width: 980px; margin: 0 auto; }}
header h1 {{ font: 600 1.7rem/1.25 var(--display); margin: 0; text-wrap: balance; }}
header p {{ color: var(--muted); margin: .3rem 0 0; font-size: .95rem; }}
nav {{ position: sticky; top: env(safe-area-inset-top, 0px); z-index: 2; background: var(--bg);
  border-bottom: 1px solid var(--line); }}
nav .in {{ max-width: 980px; margin: 0 auto; padding-inline: 16px; display: flex; gap: 4px; overflow-x: auto; }}
nav a {{ white-space: nowrap; padding: 10px 12px; color: var(--muted); text-decoration: none;
  border-bottom: 2px solid transparent; font-weight: 600; font-size: .92rem; }}
nav a:hover {{ color: var(--fg); }}
nav a[aria-current="true"] {{ color: var(--accent); border-bottom-color: var(--accent); }}
nav a:focus-visible, main a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
main {{ max-width: 980px; margin: 0 auto; padding-inline: 16px; padding-block: 8px 64px; }}
.tab > h1 {{ font: 600 1.5rem/1.3 var(--display); margin: 1.4rem 0 .6rem; }}
h2 {{ font: 700 1.15rem/1.35 var(--body); margin: 2rem 0 .6rem; padding-top: .8rem; border-top: 1px solid var(--line); text-wrap: balance; }}
p, ul, ol {{ max-width: 72ch; }}
li {{ margin: .2rem 0; }}
a {{ color: var(--accent); }}
code {{ font: .86em var(--mono); background: var(--code-bg); padding: .08em .35em; border-radius: 4px; }}
blockquote {{ margin: 1rem 0; padding: .6rem 1rem; background: var(--accent-soft); border-radius: 6px; }}
.tbl {{ overflow-x: auto; margin: .8rem 0 1.2rem; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }}
table {{ border-collapse: collapse; width: 100%; font-size: .93rem; font-variant-numeric: tabular-nums; }}
th, td {{ text-align: left; vertical-align: top; padding: .55rem .75rem; border-bottom: 1px solid var(--line); }}
th {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); background: var(--code-bg); }}
tr:last-child td {{ border-bottom: 0; }}
td:first-child {{ white-space: nowrap; }}
.diagram {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin: 1rem 0; }}
.diagram pre {{ margin: 0; background: none; }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto !important; }} }}
</style>
<header>
  <h1>{html.escape(main_title)}</h1>
  <p>Závěrečný projekt kurzu Security for AI · náhled souborů <code>RB-AIAgents/security/</code></p>
</header>
{MERMAID}<nav><div class="in">{''.join(nav)}</div></nav>
<main>{''.join(sections)}</main>
<script>
(function () {{
  var tabs = document.querySelectorAll('section.tab');
  var links = document.querySelectorAll('nav a');
  function show(id) {{
    var found = false;
    tabs.forEach(function (s) {{ var on = s.id === id; s.hidden = !on; if (on) found = true; }});
    if (!found) {{ id = 'prehled'; document.getElementById(id).hidden = false; }}
    links.forEach(function (a) {{ a.setAttribute('aria-current', a.dataset.tab === id ? 'true' : 'false'); }});
    if (window.mermaid) {{
      var nodes = document.getElementById(id).querySelectorAll('pre.mermaid:not([data-processed])');
      if (nodes.length) mermaid.run({{ nodes: nodes }});
    }}
  }}
  document.addEventListener('click', function (e) {{
    var a = e.target.closest('a[data-tab]');
    if (!a) return;
    e.preventDefault();
    show(a.dataset.tab);
    try {{ history.replaceState(null, '', '#' + a.dataset.tab); }} catch (_) {{}}
    window.scrollTo(0, 0);
  }});
  show((location.hash || '#prehled').slice(1));
}})();
</script>
"""
OUT.write_text(page, encoding="utf-8")
print("ok", OUT, len(page))
