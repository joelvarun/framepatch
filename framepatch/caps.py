"""Terminal control sequences and their exact byte cost.

Every planner in this package emits a list of ops. An op is a tuple whose first
element names the control function. ``render`` turns ops into the real byte
stream, so the cost model is never a separate estimate: the cost of a plan is
by construction the length of the stream a terminal would receive.

Sequences follow ECMA-48 as implemented by xterm. Where a control function
takes a single numeric parameter that defaults to 1, the parameter is omitted,
which is what a hand tuned renderer does and saves one byte per call.
"""

ESC = chr(27)
CSI = ESC + "["
CR = chr(13)
LF = chr(10)
BS = chr(8)


def _p(n):
    """Parameter text for a control function whose default value is 1."""
    return "" if n == 1 else str(n)


def cup(row, col):
    """Cursor position, zero based row and column."""
    if row == 0 and col == 0:
        return CSI + "H"
    if col == 0:
        return CSI + str(row + 1) + "H"
    return CSI + str(row + 1) + ";" + str(col + 1) + "H"


def cha(col):
    """Cursor horizontal absolute, zero based column."""
    if col == 0:
        return CR
    return CSI + str(col + 1) + "G"


def cuf(n):
    """Cursor forward n columns."""
    return CSI + _p(n) + "C"


def el():
    """Erase from the cursor to the end of the line."""
    return CSI + "K"


def ed():
    """Erase from the cursor to the end of the screen."""
    return CSI + "J"


def il(n):
    """Insert n blank lines at the cursor row, shifting the rest down."""
    return CSI + _p(n) + "L"


def dl(n):
    """Delete n lines at the cursor row, shifting the rest up."""
    return CSI + _p(n) + "M"


def ich(n):
    """Insert n blanks at the cursor, shifting the rest of the line right."""
    return CSI + _p(n) + "@"


def dch(n):
    """Delete n characters at the cursor, shifting the rest of the line left."""
    return CSI + _p(n) + "P"


_RENDER = {
    "cup": lambda r, c: cup(r, c),
    "cha": lambda c: cha(c),
    "cuf": lambda n: cuf(n),
    "cr": lambda: CR,
    "write": lambda s: s,
    "el": lambda: el(),
    "ed": lambda: ed(),
    "il": lambda n: il(n),
    "dl": lambda n: dl(n),
    "ich": lambda n: ich(n),
    "dch": lambda n: dch(n),
}


def render(ops):
    """Render a list of ops into the byte stream a terminal would receive."""
    out = []
    for op in ops:
        out.append(_RENDER[op[0]](*op[1:]))
    return "".join(out)


def cost(ops):
    """Exact number of bytes the ops occupy on the wire."""
    return len(render(ops))


def move_cost(col):
    """Cheapest absolute move to a column, given nothing about the cursor."""
    return len(cha(col))


class Caps:
    """Which optional control functions a terminal is allowed to receive."""

    def __init__(self, il=True, dl=True, ich=True, dch=True, el=True, ed=True):
        self.il = il
        self.dl = dl
        self.ich = ich
        self.dch = dch
        self.el = el
        self.ed = ed

    def key(self):
        return (self.il, self.dl, self.ich, self.dch, self.el, self.ed)

    def describe(self):
        on = [k for k in ("il", "dl", "ich", "dch", "el", "ed") if getattr(self, k)]
        return "+".join(on) if on else "none"


FULL = Caps()
NO_BLOCK_OPS = Caps(il=False, dl=False, ich=False, dch=False)
