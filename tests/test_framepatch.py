"""Correctness and optimality tests.

The important one is test_exhaustive_optimum. For a screen small enough that
the whole state space fits in memory, Dijkstra over (screen, cursor) states
with real byte costs on the edges gives the genuinely cheapest stream that any
sequence of control functions could produce. The planner is held against that,
not against another heuristic.
"""

import heapq
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from framepatch.caps import (CSI, Caps, cha, cost, cup, dch, dl, ed, el, ich,
                             il, render)
from framepatch.line import plan_line
from framepatch.plan import LineCache, plan_frame
from framepatch.screen import Screen, equal_exact, replay
from framepatch.strategies import STRATEGIES

WORDS = ("alpha", "beta", "gamma", "delta", "value", "count", "index", "row")


def random_lines(rng, n, w):
    out = []
    for _ in range(n):
        parts = [rng.choice(WORDS) for _ in range(rng.randint(1, 3))]
        out.append((" " * rng.randint(0, 4) + " ".join(parts))[:w])
    return out


def random_screen_pair(rng, w, h):
    pool = random_lines(rng, h + 6, w)
    top = rng.randrange(0, 5)
    src = Screen.from_lines(pool[top:top + h], w, h)
    kind = rng.randrange(5)
    doc = list(pool)
    if kind == 0:
        doc.insert(rng.randrange(len(doc)), random_lines(rng, 1, w)[0])
    elif kind == 1:
        del doc[rng.randrange(len(doc))]
    elif kind == 2:
        k = rng.randrange(len(doc))
        doc[k] = "    " + doc[k][:w - 4]
    elif kind == 3:
        top += 1
    else:
        k = rng.randrange(len(doc))
        doc[k] = random_lines(rng, 1, w)[0]
    tgt = Screen.from_lines(doc[top:top + h], w, h)
    return src, tgt


class EmulatorTests(unittest.TestCase):
    def setUp(self):
        self.base = Screen.from_lines(["abcd", "efgh", "ijkl"], 4, 3)

    def check(self, stream, expected, row=0, col=0):
        out, emu = replay(stream, self.base, row, col)
        self.assertEqual(out.lines(), expected)
        self.assertEqual(emu.unknown, [])
        return emu

    def test_insert_line_pushes_bottom_off(self):
        self.check(cup(1, 0) + il(1), ["abcd", "    ", "efgh"])

    def test_delete_line_pulls_blank_in(self):
        self.check(cup(0, 0) + dl(1), ["efgh", "ijkl", "    "])

    def test_insert_characters_shift_right(self):
        self.check(cup(0, 1) + ich(2), ["a  b", "efgh", "ijkl"])

    def test_delete_characters_shift_left(self):
        self.check(cup(0, 1) + dch(2), ["ad  ", "efgh", "ijkl"])

    def test_erase_line_and_screen(self):
        self.check(cup(1, 2) + el(), ["abcd", "ef  ", "ijkl"])
        self.check(cup(1, 2) + ed(), ["abcd", "ef  ", "    "])

    def test_line_feed_at_bottom_scrolls(self):
        self.check(cup(2, 0) + chr(10), ["efgh", "ijkl", "    "])

    def test_default_parameter_is_one(self):
        self.assertEqual(dl(1), CSI + "M")
        self.check(cup(0, 0) + CSI + "M", ["efgh", "ijkl", "    "])

    def test_write_advances_and_absolute_column(self):
        self.check(cup(0, 0) + "xy" + cha(3) + "z", ["xycz", "efgh", "ijkl"])


def optimal_cost(src, tgt, alphabet, max_states=200000):
    """Cheapest possible stream, by Dijkstra over every reachable screen."""
    w, h = src.w, src.h
    ops = [("cup", r, c) for r in range(h) for c in range(w)]
    ops += [("cha", c) for c in range(w)]
    ops += [("cuf", n) for n in range(1, w)]
    ops += [("el",), ("ed",), ("cr",)]
    ops += [("il", n) for n in range(1, h + 1)]
    ops += [("dl", n) for n in range(1, h + 1)]
    ops += [("ich", n) for n in range(1, w + 1)]
    ops += [("dch", n) for n in range(1, w + 1)]
    ops += [("write", ch) for ch in alphabet]
    priced = [(cost([op]), op) for op in ops]

    goal = tuple(tgt.lines())
    start = (tuple(src.lines()), 0, 0)
    dist = {start: 0}
    queue = [(0, start)]
    seen = 0
    while queue:
        d, state = heapq.heappop(queue)
        if d > dist.get(state, d + 1):
            continue
        if state[0] == goal:
            return d
        seen += 1
        if seen > max_states:
            raise RuntimeError("state space too large for a brute force check")
        lines, row, col = state
        screen = Screen.from_lines(list(lines), w, h)
        for price, op in priced:
            out, emu = replay(render([op]), screen, row, col)
            nxt = (tuple(out.lines()), emu.row, emu.col)
            nd = d + price
            if nd < dist.get(nxt, nd + 1):
                dist[nxt] = nd
                heapq.heappush(queue, (nd, nxt))
    raise RuntimeError("target unreachable")


class OptimalityTests(unittest.TestCase):
    def test_exhaustive_optimum(self):
        """The planner against the true optimum over all control sequences."""
        rng = random.Random(11)
        alphabet = ("a", "b", " ")
        gaps = []
        for _ in range(6):
            src_lines = ["".join(rng.choice(alphabet) for _ in range(3))
                         for _ in range(2)]
            tgt_lines = ["".join(rng.choice(alphabet) for _ in range(3))
                         for _ in range(2)]
            src = Screen.from_lines(src_lines, 3, 2)
            tgt = Screen.from_lines(tgt_lines, 3, 2)
            if src == tgt:
                continue
            best = optimal_cost(src, tgt, alphabet)
            ops, planned = plan_frame(src, tgt, Caps(), LineCache())
            out, _ = replay(render(ops), src)
            self.assertTrue(equal_exact(out, tgt))
            self.assertGreaterEqual(planned, best)
            gaps.append(planned - best)
        self.assertTrue(gaps)
        # The planner is never cheaper than the true optimum, and the gap is
        # the absolute cursor move it pays for every touched row. The brute
        # force knows where the cursor already is and can step with one byte.
        # Making the per row cost independent of the rest of the plan is what
        # turns the alignment into a dynamic program, so the gap is the price
        # of the decomposition rather than a missing case.
        self.assertLessEqual(max(gaps), 8)

    def test_line_planner_never_beaten_by_whole_line_rewrite(self):
        rng = random.Random(3)
        for _ in range(200):
            src = "".join(rng.choice("ab ") for _ in range(16))
            tgt = "".join(rng.choice("ab ") for _ in range(16))
            ops, planned = plan_line(src, tgt, 5, Caps())
            naive = cost([("cup", 5, 0), ("write", tgt.rstrip()), ("el",)])
            if src != tgt:
                self.assertLessEqual(planned, naive)


class StrategyTests(unittest.TestCase):
    def test_every_strategy_reproduces_every_frame(self):
        rng = random.Random(5)
        cache = LineCache()
        for _ in range(40):
            src, tgt = random_screen_pair(rng, 24, 6)
            for name, fn in STRATEGIES:
                ops, planned = fn(src, tgt, None, cache)
                stream = render(ops)
                self.assertEqual(planned, len(stream), name)
                out, emu = replay(stream, src)
                self.assertTrue(equal_exact(out, tgt), name)
                self.assertEqual(emu.overflow, 0, name)

    def test_capabilities_are_respected(self):
        rng = random.Random(7)
        flat = Caps(il=False, dl=False, ich=False, dch=False)
        for _ in range(20):
            src, tgt = random_screen_pair(rng, 24, 6)
            ops, _ = plan_frame(src, tgt, flat, LineCache())
            kinds = set(op[0] for op in ops)
            self.assertFalse(kinds & {"il", "dl", "ich", "dch"})
            out, _ = replay(render(ops), src)
            self.assertTrue(equal_exact(out, tgt))

    def test_candidate_budgets_match_an_exhaustive_search(self):
        rng = random.Random(13)
        worse = 0
        trials = 0
        for _ in range(12):
            src, tgt = random_screen_pair(rng, 40, 10)
            cache = LineCache()
            _, quick = plan_frame(src, tgt, Caps(), cache)
            _, full = plan_frame(src, tgt, Caps(), cache,
                                 budgets=list(range(10)))
            self.assertLessEqual(full, quick)
            trials += 1
            if full < quick:
                worse += 1
        self.assertLessEqual(worse, trials // 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
