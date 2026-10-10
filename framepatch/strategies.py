"""The update strategies being compared, all producing a real byte stream.

full        clear the screen and paint every non blank row
lines       repaint every row whose content changed, whole row at a time
shift       detect one global vertical shift, then repaint each row optimally
align       this project's row alignment, with the intra row shifts disabled
fast        the full planner with a banded search and fewer prologue budgets
framepatch  the full two level alignment

The two simple strategies are allowed the carriage return and line feed trick
for stepping to the next row, which costs two bytes against four to eight for
an absolute cursor position. The alignment strategies always pay the absolute
move, so the comparison is conservative in their disfavour.

`shift` is the honest competitor. Detecting one global shift and repainting
the rest is what a pager or a scroll optimising renderer already does, so the
distance between `shift` and `framepatch` is the part of the result that comes
from this project rather than from using IL and DL at all.
"""

from .caps import CR, LF, Caps, cost
from .plan import plan_frame, shift_plan

FLAT = Caps(il=False, dl=False, ich=False, dch=False)
ALIGN_ONLY = Caps(il=True, dl=True, ich=False, dch=False)
FULL = Caps()
BLANK = " "
FAST_BAND = 4


def _goto_ops(row, cur_row):
    """Cheapest way to reach column zero of a row from a known row."""
    absolute = [("cup", row, 0)]
    if cur_row is not None and row > cur_row:
        relative = [("write", CR + LF * (row - cur_row))]
        if cost(relative) < cost(absolute):
            return relative
    return absolute


def full_redraw(src, tgt, caps=None, cache=None):
    ops = [("cup", 0, 0), ("ed",)]
    cur = 0
    for r, text in enumerate(tgt.trimmed()):
        if not text:
            continue
        ops.extend(_goto_ops(r, cur))
        ops.append(("write", text))
        cur = r
    return ops, cost(ops)


def line_redraw(src, tgt, caps=None, cache=None):
    s_lines = src.lines()
    t_lines = tgt.lines()
    ops = []
    cur = None
    for r in range(src.h):
        if s_lines[r] == t_lines[r]:
            continue
        text = t_lines[r].rstrip()
        ops.extend(_goto_ops(r, cur))
        if text:
            ops.append(("write", text))
        if len(s_lines[r].rstrip()) > len(text):
            ops.append(("el",))
        cur = r
    return ops, cost(ops)


def shift_detect(src, tgt, caps=None, cache=None):
    blank = BLANK * src.w
    return shift_plan(src.lines(), tgt.lines(), src.h, blank, ALIGN_ONLY, cache)


def align_only(src, tgt, caps=None, cache=None):
    return plan_frame(src, tgt, ALIGN_ONLY, cache)


def framepatch_fast(src, tgt, caps=None, cache=None):
    return plan_frame(src, tgt, FULL, cache, band=FAST_BAND)


def framepatch(src, tgt, caps=None, cache=None):
    return plan_frame(src, tgt, FULL, cache)


STRATEGIES = (
    ("full", full_redraw),
    ("lines", line_redraw),
    ("shift", shift_detect),
    ("align", align_only),
    ("fast", framepatch_fast),
    ("framepatch", framepatch),
)
