"""Baseline: the screen diff renderer that prompt_toolkit actually ships.

This is not a reimplementation. The bytes counted here come from calling
prompt_toolkit's own private renderer entry point with two of its own Screen
objects and a real Vt100 output bound to a string buffer, so the numbers are
what ptpython, IPython, pgcli and every other prompt_toolkit application sends
to a terminal for that frame transition.

prompt_toolkit diffs cell by cell and reaches every changed cell with relative
cursor moves. It never uses line or character insert and delete, which is the
difference this project measures.
"""

import io

from .caps import ESC

AVAILABLE = True
VERSION = None
try:  # pragma: no cover - depends on the local environment
    import prompt_toolkit
    from prompt_toolkit.data_structures import Point, Size
    from prompt_toolkit.layout.screen import Char
    from prompt_toolkit.layout.screen import Screen as PtkScreen
    from prompt_toolkit.output.color_depth import ColorDepth
    from prompt_toolkit.output.vt100 import Vt100_Output
    from prompt_toolkit.renderer import (
        _output_screen_diff,
        _StyleStringHasStyleCache,
        _StyleStringToAttrsCache,
    )
    from prompt_toolkit.styles import DummyStyleTransformation, default_ui_style

    VERSION = prompt_toolkit.__version__
except Exception:  # pragma: no cover
    AVAILABLE = False

DECORATIONS = (
    ESC + "[?25l",
    ESC + "[?25h",
    ESC + "[?7l",
    ESC + "[?7h",
    ESC + "[0m",
    ESC + "[?12l",
)


class _Layout:
    current_window = object()


class _App:
    layout = _Layout()


def strip_decorations(stream):
    """Remove the fixed per frame mode and attribute resets."""
    for d in DECORATIONS:
        stream = stream.replace(d, "")
    return stream


def to_ptk_screen(screen):
    """Build a prompt_toolkit Screen from one of our text screens."""
    out = PtkScreen(initial_width=screen.w, initial_height=screen.h)
    out.width = screen.w
    out.height = screen.h
    for r, row in enumerate(screen.cells):
        buf = out.data_buffer[r]
        for c, ch in enumerate(row):
            if ch != " ":
                buf[c] = Char(ch, "")
    return out


class PtkRenderer:
    """Holds the style caches so the cost is the diff, not the setup."""

    def __init__(self, w, h):
        self.w = w
        self.h = h
        style = default_ui_style()
        self.attrs = _StyleStringToAttrsCache(
            style.get_attrs_for_style_str, DummyStyleTransformation()
        )
        self.has_style = _StyleStringHasStyleCache(self.attrs)
        self.app = _App()
        self.size = Size(rows=h, columns=w)
        self.sio = io.StringIO()
        self.output = Vt100_Output(self.sio, lambda: self.size,
                                   term="xterm-256color")

    def diff(self, src, tgt):
        """Byte stream prompt_toolkit would send to go from src to tgt."""
        return self.diff_screens(to_ptk_screen(src), to_ptk_screen(tgt))

    def diff_screens(self, src_screen, tgt_screen):
        """Same, for screens already converted, so the timing is the diff."""
        sio = self.sio
        sio.seek(0)
        sio.truncate(0)
        output = self.output
        _output_screen_diff(
            self.app,
            output,
            tgt_screen,
            Point(x=0, y=0),
            ColorDepth.DEPTH_4_BIT,
            src_screen,
            None,
            False,
            True,
            self.attrs,
            self.has_style,
            self.size,
            self.w,
        )
        output.flush()
        return strip_decorations(sio.getvalue())

    def fixed_overhead(self, screen):
        """Bytes prompt_toolkit sends for a frame where nothing changed."""
        return len(self.diff(screen, screen))
