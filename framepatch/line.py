"""Inner level of the alignment: repaint one screen row for the fewest bytes.

Two ideas live here.

A row only has to be repainted where it differs, and the gaps between the
differing stretches are a free choice: overwrite the matching characters, or
jump over them with a cursor move. Overwriting costs one byte per column and a
move costs four to six, so the choice is per gap and independent of the other
gaps, which makes the cheapest paint a closed form rather than a search.

When the new row is the old row shifted sideways (indenting a block, switching
line numbers on, inserting a character mid line) the terminal can do the shift
itself with ICH or DCH and the application sends only what is genuinely new.

The differing stretches are found with integer and bytes operations rather than
a loop over columns: the two rows are read as big integers, exclusive ored, and
the result walked with lstrip and find. That keeps the inner planner at a few
microseconds, which matters because the row alignment asks for the cost of
every old row against every new row.

Screen content is assumed to be printable single width characters.
"""

from .caps import cha, cuf, cost

BLANK = " "
ZERO = bytes(1)


def diff_runs(src, tgt, start=0):
    """Maximal runs of columns where the two rows differ, from `start` on."""
    if src == tgt:
        return []
    w = len(src)
    a = src.encode("ascii", "replace")
    b = tgt.encode("ascii", "replace")
    mask = (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(w, "big")
    runs = []
    pos = start
    while pos < w:
        sub = mask[pos:]
        stripped = sub.lstrip(ZERO)
        if not stripped:
            break
        s = pos + (len(sub) - len(stripped))
        hole = stripped.find(ZERO)
        e = s + (len(stripped) if hole < 0 else hole)
        runs.append((s, e))
        pos = e
    return runs


def _move_op(frm, to):
    """Cheapest op moving the cursor from a known column to another."""
    if to == frm:
        return None
    gap = to - frm
    if gap > 0 and len(cuf(gap)) <= len(cha(to)):
        return ("cuf", gap)
    return ("cha", to)


def _emit(tgt, row, cursor, runs, el_col, c0):
    """Build the op list for one row, given where the paint starts."""
    ops = []
    if cursor is None:
        ops.append(("cup", row, c0))
        pos = c0
    else:
        pos = cursor
        mv = _move_op(pos, c0)
        if mv is not None:
            ops.append(mv)
        pos = c0

    if runs:
        spans = [[c0, runs[0][1]]]
        for s, e in runs[1:]:
            gap = s - spans[-1][1]
            move_bytes = len(cha(s))
            fwd = len(cuf(gap))
            if fwd < move_bytes:
                move_bytes = fwd
            if gap <= move_bytes:
                spans[-1][1] = e
            else:
                spans.append([s, e])
        for idx, (a, b) in enumerate(spans):
            if idx > 0:
                mv = _move_op(pos, a)
                if mv is not None:
                    ops.append(mv)
                pos = a
            ops.append(("write", tgt[a:b]))
            pos = b

    if el_col is not None:
        gap = el_col - pos
        if gap > 0:
            move_bytes = len(cha(el_col))
            fwd = len(cuf(gap))
            if fwd < move_bytes:
                move_bytes = fwd
            if gap <= move_bytes:
                ops.append(("write", tgt[pos:el_col]))
                pos = el_col
        mv = _move_op(pos, el_col)
        if mv is not None:
            ops.append(mv)
        ops.append(("el",))
    return ops


def paint(src, tgt, row, start, cursor, caps, runs=None):
    """Cheapest repaint of columns [start, w) of one row. Returns (ops, bytes)."""
    if runs is None:
        runs = diff_runs(src, tgt, start)
    if not runs:
        return [], 0
    first = runs[0][0]
    last = runs[-1][1] - 1

    blank_from = len(tgt.rstrip(BLANK))
    if blank_from < start:
        blank_from = start
    el_col = blank_from if (caps.el and blank_from <= last) else None

    if el_col is None:
        keep = runs
    else:
        keep = []
        for s, e in runs:
            if s >= el_col:
                break
            keep.append((s, min(e, el_col)))

    anchors = [keep[0][0] if keep else el_col]
    if cursor is None and anchors[0] > 0:
        anchors.append(0)

    best_ops = None
    best_cost = None
    for c0 in anchors:
        ops = _emit(tgt, row, cursor, keep, el_col, c0)
        c = cost(ops)
        if best_cost is None or c < best_cost:
            best_ops, best_cost = ops, c
    return best_ops, best_cost


def _shift_candidates(src, tgt, p, max_shift, caps):
    """Sideways shifts of the old row that could explain the new row.

    A candidate is rejected by probing a few columns near the end of the new
    row, which costs a handful of comparisons instead of a full evaluation.
    """
    w = len(src)
    q = len(tgt.rstrip(BLANK)) - 1
    probes = [c for c in (q, q - 1, q - 2, (q + p) // 2) if p < c < w]
    if not probes:
        return []
    out = []
    for k in range(1, max_shift + 1):
        if caps.ich and w - k > p:
            sh = src[:p] + BLANK * k + src[p:w - k]
            if all(sh[c] == tgt[c] for c in probes):
                out.append(("ich", k, sh))
        if caps.dch and p + k < w:
            sh = src[:p] + src[p + k:] + BLANK * k
            if all(sh[c] == tgt[c] for c in probes):
                out.append(("dch", k, sh))
    return out


def plan_line(src, tgt, row, caps, max_shift=8, shift_threshold=10):
    """Cheapest op list turning row `row` from `src` into `tgt`."""
    runs = diff_runs(src, tgt)
    if not runs:
        return [], 0
    best_ops, best_cost = paint(src, tgt, row, 0, None, caps, runs)
    if best_cost > shift_threshold and (caps.ich or caps.dch):
        p = runs[0][0]
        for kind, k, shifted in _shift_candidates(src, tgt, p, max_shift, caps):
            head = [("cup", row, p), (kind, k)]
            tail, _ = paint(shifted, tgt, row, p, p, caps)
            ops = head + tail
            c = cost(ops)
            if c < best_cost:
                best_ops, best_cost = ops, c
    return best_ops, best_cost
