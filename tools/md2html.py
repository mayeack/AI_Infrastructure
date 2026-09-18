#!/usr/bin/env python3
"""Stdlib Markdown-to-HTML converter for the app docs; writes <basename>.html next to each .md.

Supports headings, paragraphs, fenced code blocks, inline code / bold / italic / links, pipe tables,
ordered and unordered lists (one level of nesting) and horizontal rules. Self-contained dark CSS.
"""
import argparse
import html
import os
import re
import sys

CSS = """
:root{color-scheme:dark}
body{margin:0;padding:32px 16px;background:#171D21;color:#E1E6EB;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1080px;margin:0 auto}
h1,h2,h3,h4{color:#FFFFFF;line-height:1.25;margin:1.6em 0 .5em}
h1{font-size:2em;border-bottom:1px solid #3C444D;padding-bottom:.3em}
h2{font-size:1.5em;border-bottom:1px solid #31373D;padding-bottom:.25em}
h3{font-size:1.2em}
a{color:#009CEB;text-decoration:none}a:hover{text-decoration:underline}
code{font-family:"SF Mono",Menlo,Consolas,monospace;font-size:.9em;background:#2B3033;padding:.1em .35em;border-radius:3px}
pre{background:#0F1316;border:1px solid #3C444D;border-radius:6px;padding:12px 14px;overflow-x:auto}
pre code{background:none;padding:0;font-size:.85em}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:.92em}
th,td{border:1px solid #3C444D;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#212527;color:#FFFFFF}
tr:nth-child(even) td{background:#1C2125}
blockquote{border-left:4px solid #7B56DB;margin:1em 0;padding:.2em 1em;color:#B8C0C8}
hr{border:0;border-top:1px solid #3C444D;margin:2em 0}
ul,ol{padding-left:1.6em}
li{margin:.2em 0}
"""

INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text):
    """Escape then apply inline markup; code spans are protected from further substitution."""
    parts = []
    pos = 0
    text = text.replace("\\`", "\x00")  # escaped backtick: literal inside or outside a code span
    for m in INLINE_CODE.finditer(text):
        parts.append(("t", text[pos:m.start()]))
        parts.append(("c", m.group(1)))
        pos = m.end()
    parts.append(("t", text[pos:]))
    out = []
    for kind, s in parts:
        if kind == "c":
            out.append("<code>%s</code>" % html.escape(s))
        else:
            s = html.escape(s, quote=False)
            s = LINK.sub(lambda m: '<a href="%s">%s</a>' % (html.escape(m.group(2), quote=True), m.group(1)), s)
            s = BOLD.sub(r"<strong>\1</strong>", s)
            s = ITALIC.sub(r"<em>\1</em>", s)
            out.append(s)
    return "".join(out).replace("\x00", "`")


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur).strip())
    return cells


def is_sep_row(line):
    return re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", line) is not None


def convert(md):
    lines = md.splitlines()
    out = []
    i = 0
    n = len(lines)
    list_stack = []  # list of tags currently open

    def close_lists(depth=0):
        while len(list_stack) > depth:
            out.append("</%s>" % list_stack.pop())

    while i < n:
        line = lines[i]
        stripped = line.strip()
        # fenced code
        if stripped.startswith("```"):
            close_lists()
            lang = stripped[3:].strip()
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = ' class="lang-%s"' % html.escape(lang) if lang else ""
            out.append("<pre><code%s>%s</code></pre>" % (cls, html.escape("\n".join(buf))))
            continue
        # heading
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            close_lists()
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
            i += 1
            continue
        # horizontal rule
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            close_lists()
            out.append("<hr>")
            i += 1
            continue
        # table
        if "|" in line and i + 1 < n and is_sep_row(lines[i + 1]):
            close_lists()
            head = split_row(line)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            out.append("<table><thead><tr>%s</tr></thead><tbody>" % "".join("<th>%s</th>" % inline(c) for c in head))
            for r in rows:
                r = r + [""] * (len(head) - len(r))
                out.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r[:len(head)]))
            out.append("</tbody></table>")
            continue
        # list item
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            depth = len(m.group(1).replace("\t", "    ")) // 2 + 1
            tag = "ol" if m.group(2)[0].isdigit() else "ul"
            while len(list_stack) > depth or (len(list_stack) == depth and list_stack[-1] != tag):
                out.append("</%s>" % list_stack.pop())
            while len(list_stack) < depth:
                list_stack.append(tag)
                out.append("<%s>" % tag)
            out.append("<li>%s</li>" % inline(m.group(3)))
            i += 1
            continue
        # blockquote
        if stripped.startswith(">"):
            close_lists()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote><p>%s</p></blockquote>" % inline(" ".join(buf)))
            continue
        # blank
        if not stripped:
            close_lists()
            i += 1
            continue
        # paragraph
        close_lists()
        buf = [stripped]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|\s*([-*+]|\d+[.)])\s|>|\s*\|)", lines[i]) \
                and not (("|" in lines[i]) and i + 1 < n and is_sep_row(lines[i + 1])):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(buf)))
    close_lists()
    return "\n".join(out)


def title_of(md, fallback):
    m = re.search(r"^#\s+(.+?)\s*$", md, re.M)
    return m.group(1) if m else fallback


def render(md_path, out_path=None):
    md = open(md_path, encoding="utf-8").read()
    body = convert(md)
    title = html.escape(re.sub(r"[`*]", "", title_of(md, os.path.basename(md_path))))
    doc = ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
           "<title>%s</title><style>%s</style></head><body><main>\n%s\n</main></body></html>\n" % (title, CSS, body))
    out_path = out_path or os.path.splitext(md_path)[0] + ".html"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.chmod(out_path, 0o644)
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render Markdown files to self-contained dark HTML twins")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    for f in a.files:
        if not os.path.isfile(f):
            print("skip (missing): %s" % f)
            continue
        print("wrote %s" % render(f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
