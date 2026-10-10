"""Frame sequences taken from real files on this machine.

Every workload is a viewport over a real Python source file out of the local
standard library, rendered the way a pager or an editor would render it: a
content area, a status line, and tilde rows past the end of the file. No frame
data is downloaded and none of the documents were written for this benchmark.

The sequences cover the operations terminal applications actually perform:
scrolling, paging, jumping, applying edits, tailing a growing file, folding,
switching line numbers, re-indenting a block, and refreshing a field dashboard.
"""

import ast
import difflib
import os
import random
import sysconfig

from .screen import Screen

W = 80
H = 24

SOURCES = ("argparse.py", "textwrap.py", "pprint.py", "csv.py", "difflib.py")


def stdlib_lines(name):
    path = os.path.join(sysconfig.get_paths()["stdlib"], name)
    with open(path, encoding="utf-8") as handle:
        return handle.read().expandtabs(8).splitlines()


def render_frame(lines, top, title, note="", numbers=False, w=W, h=H):
    body = []
    for i in range(h - 1):
        k = top + i
        if k < len(lines):
            text = lines[k]
            if numbers:
                text = "%4d %s" % (k + 1, text)
        else:
            text = "~"
        body.append(text[:w])
    last = min(top + h - 1, len(lines))
    status = "%s  %d-%d/%d  %s" % (title, top + 1, last, len(lines), note)
    body.append(status[:w])
    return Screen.from_lines(body, w, h)


def scroll_line(lines, title, count=48):
    return [render_frame(lines, t, title, "scroll") for t in range(count)]


def scroll_page(lines, title, count=18):
    step = H - 2
    return [render_frame(lines, k * step, title, "page") for k in range(count)]


def search_jump(lines, title, needle="return", count=24):
    hits = [i for i, line in enumerate(lines) if needle in line]
    picks = hits[:: max(1, len(hits) // count)][:count]
    return [render_frame(lines, max(0, i - 8), title, "match") for i in picks]


def edit_hunks(lines, title, count=24):
    """Apply the real difference between a module and its unparsed form."""
    tree = ast.parse(chr(10).join(lines))
    norm = ast.unparse(tree).expandtabs(8).splitlines()
    matcher = difflib.SequenceMatcher(a=lines, b=norm, autojunk=False)
    doc = list(lines)
    frames = [render_frame(doc, 0, title, "edit")]
    offset = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        doc[i1 + offset:i2 + offset] = norm[j1:j2]
        offset += (j2 - j1) - (i2 - i1)
        top = max(0, i1 + offset - 10)
        frames.append(render_frame(doc, top, title, "edit"))
        if len(frames) >= count:
            break
    return frames


def log_tail(lines, title, count=40):
    frames = []
    buf = []
    for i in range(count):
        buf.append(lines[i % len(lines)])
        top = max(0, len(buf) - (H - 1))
        frames.append(render_frame(buf, top, title, "tail %d" % len(buf)))
    return frames


def _top_level_defs(lines):
    tree = ast.parse(chr(10).join(lines))
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.end_lineno - node.lineno >= 2:
                out.append((node.lineno - 1, node.end_lineno - 1))
    return out


def _apply_folds(lines, defs, folded):
    ends = dict(defs)
    out = []
    i = 0
    while i < len(lines):
        if i in folded and i in ends:
            out.append(lines[i] + " ...")
            i = ends[i] + 1
        else:
            out.append(lines[i])
            i += 1
    return out


def fold_toggle(lines, title, count=20):
    defs = _top_level_defs(lines)
    if not defs:
        return []
    top = max(0, defs[0][0] - 2)
    order = [s for s, _ in defs][: max(1, count // 2)]
    frames = [render_frame(lines, top, title, "fold")]
    folded = set()
    for start in order:
        folded.add(start)
        doc = _apply_folds(lines, defs, folded)
        frames.append(render_frame(doc, top, title, "fold"))
    for start in reversed(order):
        folded.discard(start)
        doc = _apply_folds(lines, defs, folded)
        frames.append(render_frame(doc, top, title, "unfold"))
    return frames


def numbers_toggle(lines, title, count=20):
    frames = []
    for i in range(count):
        top = 10 + (i // 2)
        frames.append(render_frame(lines, top, title, "numbers", numbers=bool(i % 2)))
    return frames


def indent_block(lines, title, count=16):
    defs = _top_level_defs(lines)
    if not defs:
        return []
    start, end = defs[0]
    top = max(0, start - 2)
    frames = []
    for i in range(count):
        depth = (i % 4) + (0 if (i // 4) % 2 == 0 else 1)
        doc = list(lines)
        for k in range(start + 1, min(end + 1, len(doc))):
            doc[k] = (" " * (4 * (depth % 3))) + doc[k]
        frames.append(render_frame(doc, top, title, "indent %d" % depth))
    return frames


def dashboard(labels, title, count=24, seed=7):
    """A field refresh workload in the shape of top or htop."""
    rng = random.Random(seed)
    rows = min(H - 1, len(labels))
    values = [[rng.randrange(1000, 9999), rng.randrange(0, 999)] for _ in range(rows)]
    frames = []
    for _ in range(count):
        for _ in range(6):
            k = rng.randrange(rows)
            values[k][rng.randrange(2)] = rng.randrange(1000, 9999)
        doc = []
        for k in range(rows):
            doc.append("%-28s %8d kB %6.1f %%  %s" % (
                labels[k], values[k][0], values[k][1] / 10.0,
                "#" * (values[k][1] // 100)))
        frames.append(render_frame(doc, 0, title, "refresh"))
    return frames


def all_workloads():
    """Returns a list of (name, description, frames)."""
    arg = stdlib_lines("argparse.py")
    txt = stdlib_lines("textwrap.py")
    ppr = stdlib_lines("pprint.py")
    csvm = stdlib_lines("csv.py")
    labels = sorted(
        n[:-3] for n in os.listdir(sysconfig.get_paths()["stdlib"])
        if n.endswith(".py")
    )
    return [
        ("scroll", "one line at a time through argparse.py",
         scroll_line(arg, "argparse.py")),
        ("page", "page down through argparse.py",
         scroll_page(arg, "argparse.py")),
        ("jump", "jump to each match of a search in argparse.py",
         search_jump(arg, "argparse.py")),
        ("edit", "apply the real diff between pprint.py and its unparsed form",
         edit_hunks(ppr, "pprint.py")),
        ("tail", "follow a growing log file",
         log_tail(txt, "build.log")),
        ("fold", "fold and unfold top level definitions of textwrap.py",
         fold_toggle(txt, "textwrap.py")),
        ("numbers", "switch line numbers on and off while scrolling",
         numbers_toggle(csvm, "csv.py")),
        ("indent", "re-indent a function body in textwrap.py",
         indent_block(txt, "textwrap.py")),
        ("dashboard", "refresh scattered numeric fields, as top does",
         dashboard(labels, "modules")),
    ]
