"""A fixed size character screen and a VT emulator that replays a byte stream.

The emulator is the verifier for the whole package. Every strategy produces a
byte stream, the stream is replayed against the previous screen, and the result
must equal the frame the application asked for. A planner that is clever but
wrong therefore cannot reach the benchmark table.

Autowrap is assumed off, which is what a full screen application sets. Writes
past the last column are clamped and counted so the benchmark can assert that
no planner ever relies on wrapping.
"""

from .caps import ESC, CR, LF, BS

BLANK = " "


class Screen:
    """A w by h grid of single width characters."""

    __slots__ = ("w", "h", "cells")

    def __init__(self, w, h, cells=None):
        self.w = w
        self.h = h
        if cells is None:
            self.cells = [[BLANK] * w for _ in range(h)]
        else:
            self.cells = cells

    @classmethod
    def from_lines(cls, lines, w, h):
        cells = []
        for r in range(h):
            text = lines[r] if r < len(lines) else ""
            row = list(text[:w])
            row.extend([BLANK] * (w - len(row)))
            cells.append(row)
        return cls(w, h, cells)

    def copy(self):
        return Screen(self.w, self.h, [row[:] for row in self.cells])

    def lines(self):
        return ["".join(row) for row in self.cells]

    def trimmed(self):
        return [line.rstrip() for line in self.lines()]

    def __eq__(self, other):
        return self.w == other.w and self.h == other.h and self.cells == other.cells

    def __repr__(self):
        return "Screen(%dx%d)" % (self.w, self.h)


def equal_exact(a, b):
    return a.cells == b.cells


def equal_trimmed(a, b):
    """Equality ignoring trailing blanks, for renderers that never paint them."""
    return a.trimmed() == b.trimmed()


class Emulator:
    """Replays a byte stream against a screen."""

    def __init__(self, screen, row=0, col=0):
        self.s = screen
        self.row = row
        self.col = col
        self.overflow = 0
        self.unknown = []

    def _scroll_up(self, n=1):
        for _ in range(n):
            self.s.cells.pop(0)
            self.s.cells.append([BLANK] * self.s.w)

    def _put(self, ch):
        if self.col >= self.s.w:
            self.overflow += 1
            self.col = self.s.w - 1
        self.s.cells[self.row][self.col] = ch
        self.col += 1

    def _csi(self, params, private, final):
        def arg(i, default=1):
            if i < len(params) and params[i] != "":
                return int(params[i])
            return default

        s = self.s
        if private:
            return  # mode set and reset, for example cursor visibility
        if final in ("H", "f"):
            self.row = min(max(arg(0) - 1, 0), s.h - 1)
            self.col = min(max(arg(1) - 1, 0), s.w - 1)
        elif final == "A":
            self.row = max(self.row - arg(0), 0)
        elif final == "B":
            self.row = min(self.row + arg(0), s.h - 1)
        elif final == "C":
            self.col = min(self.col + arg(0), s.w - 1)
        elif final == "D":
            self.col = max(self.col - arg(0), 0)
        elif final == "G":
            self.col = min(max(arg(0) - 1, 0), s.w - 1)
        elif final == "d":
            self.row = min(max(arg(0) - 1, 0), s.h - 1)
        elif final == "K":
            mode = arg(0, 0)
            row = s.cells[self.row]
            if mode == 0:
                for c in range(self.col, s.w):
                    row[c] = BLANK
            elif mode == 1:
                for c in range(0, min(self.col + 1, s.w)):
                    row[c] = BLANK
            else:
                for c in range(s.w):
                    row[c] = BLANK
        elif final == "J":
            mode = arg(0, 0)
            if mode == 0:
                for c in range(self.col, s.w):
                    s.cells[self.row][c] = BLANK
                for r in range(self.row + 1, s.h):
                    s.cells[r] = [BLANK] * s.w
            elif mode == 1:
                for c in range(0, min(self.col + 1, s.w)):
                    s.cells[self.row][c] = BLANK
                for r in range(0, self.row):
                    s.cells[r] = [BLANK] * s.w
            else:
                for r in range(s.h):
                    s.cells[r] = [BLANK] * s.w
        elif final == "L":
            n = min(arg(0), s.h - self.row)
            for _ in range(n):
                s.cells.insert(self.row, [BLANK] * s.w)
                s.cells.pop()
        elif final == "M":
            n = min(arg(0), s.h - self.row)
            for _ in range(n):
                s.cells.pop(self.row)
                s.cells.append([BLANK] * s.w)
        elif final == "@":
            n = min(arg(0), s.w - self.col)
            row = s.cells[self.row]
            for _ in range(n):
                row.insert(self.col, BLANK)
                row.pop()
        elif final == "P":
            n = min(arg(0), s.w - self.col)
            row = s.cells[self.row]
            for _ in range(n):
                row.pop(self.col)
                row.append(BLANK)
        elif final == "X":
            n = min(arg(0), s.w - self.col)
            row = s.cells[self.row]
            for c in range(self.col, self.col + n):
                row[c] = BLANK
        elif final in ("m", "h", "l", "s", "u", "r"):
            return
        else:
            self.unknown.append(final)

    def feed(self, stream):
        i = 0
        n = len(stream)
        while i < n:
            ch = stream[i]
            if ch == ESC:
                if i + 1 < n and stream[i + 1] == "[":
                    j = i + 2
                    private = False
                    if j < n and stream[j] in "?><!":
                        private = True
                        j += 1
                    start = j
                    while j < n and (stream[j].isdigit() or stream[j] == ";"):
                        j += 1
                    if j < n:
                        self._csi(stream[start:j].split(";"), private, stream[j])
                        i = j + 1
                    else:
                        i = n
                else:
                    i += 2
                continue
            if ch == CR:
                self.col = 0
            elif ch == LF:
                if self.row >= self.s.h - 1:
                    self._scroll_up()
                else:
                    self.row += 1
            elif ch == BS:
                self.col = max(self.col - 1, 0)
            elif ch == chr(7) or ch == chr(9):
                pass
            else:
                self._put(ch)
            i += 1
        return self.s


def replay(stream, screen, row=0, col=0):
    """Apply a stream to a copy of a screen. Returns (screen, emulator)."""
    emu = Emulator(screen.copy(), row, col)
    emu.feed(stream)
    return emu.s, emu
