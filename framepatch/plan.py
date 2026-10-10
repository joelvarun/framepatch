"""Outer level of the alignment: match old screen rows to new screen rows.

A terminal can insert and delete whole lines (IL and DL), which shifts every
row below the cursor. The cheapest update is therefore not a per row diff. It
is an alignment between the rows of the old screen and the rows of the new
screen, where an unmatched old row is deleted, an unmatched new row is
inserted, and a matched pair is repainted by the inner planner.

Three details make the alignment exact rather than approximate.

Deleting a line pulls a blank line in at the bottom of the screen, and that
blank can legitimately be matched against a later new row. Padding the old
screen with one blank per screen row makes those arrivals ordinary candidates
in the same alignment, so no special case is needed.

Inserting a line pushes the bottom row off the screen, and the content that
left is not available to match later. A planner that forgets this produces a
plan that is cheaper on paper and wrong on a terminal. Rather than tracking how
much content a partial plan has already destroyed, the planner may open with a
prologue that deletes the bottom P rows outright. After the prologue those rows
really are blank, so insertions within that budget destroy nothing and the
model is exact. P is searched over a small candidate set and the prologue is
charged like any other sequence.

Runs of deletions and insertions are charged as one control function, because
IL and DL take a count. The transitions are therefore blocks, not units, which
is what makes a page scroll or a fold cost a single sequence. A block
transition would make the dynamic program quadratic in the number of rows, but
the length of a control function only depends on the number of digits in its
parameter, so the candidates fall into three cost tiers and running minima over
those tiers give the same answer in linear time.
"""

from .caps import cup, dl, ed, il, cost
from .line import plan_line

INF = float("inf")
BLANK = " "


class LineCache:
    """Bounded memo for inner plans. Frame sequences repeat row pairs a lot."""

    def __init__(self, limit=60000):
        self.limit = limit
        self.store = {}
        self.hits = 0
        self.misses = 0

    def get(self, src, tgt, row, caps):
        key = (src, tgt, row, caps.key())
        hit = self.store.get(key)
        if hit is not None:
            self.hits += 1
            return hit
        self.misses += 1
        val = plan_line(src, tgt, row, caps)
        if len(self.store) >= self.limit:
            self.store.clear()
        self.store[key] = val
        return val


def _tail_blank_flags(lines, blank):
    h = len(lines)
    tail = [True] * (h + 1)
    for j in range(h - 1, -1, -1):
        tail[j] = tail[j + 1] and lines[j] == blank
    return tail


def best_shift(src_lines, tgt_lines, h, blank):
    """The single vertical shift of the old screen that explains the most rows."""
    best = 0
    score0 = 0
    for r in range(h):
        if tgt_lines[r] != blank and tgt_lines[r] == src_lines[r]:
            score0 += 1
    best_score = score0
    for shift in range(-(h - 1), h):
        if shift == 0:
            continue
        score = 0
        for r in range(h):
            k = r + shift
            if 0 <= k < h and tgt_lines[r] != blank and tgt_lines[r] == src_lines[k]:
                score += 1
        if score > best_score or (score == best_score and score > 0
                                  and abs(shift) < abs(best)):
            best_score = score
            best = shift
    return best, best_score


def shift_plan(src_lines, tgt_lines, h, blank, caps, cache, line_caps=None):
    """One global shift, then the cheapest repaint of every row that differs.

    This is both a strong baseline in its own right and the warm start that
    bounds the search in the exact alignment.
    """
    lc = line_caps if line_caps is not None else caps
    shift, _ = best_shift(src_lines, tgt_lines, h, blank)
    ops = []
    if shift > 0 and caps.dl:
        ops = [("cup", 0, 0), ("dl", shift)]
        shifted = src_lines[shift:] + [blank] * shift
    elif shift < 0 and caps.il:
        n = -shift
        ops = [("cup", 0, 0), ("il", n)]
        shifted = [blank] * n + src_lines[: h - n]
    else:
        shifted = src_lines
    for r in range(h):
        if shifted[r] != tgt_lines[r]:
            line_ops, _ = cache.get(shifted[r], tgt_lines[r], r, lc)
            ops.extend(line_ops)
    return ops, cost(ops)


def loss_candidates(src_lines, tgt_lines, h, blank, keep=2):
    """Candidate prologue sizes: how many bottom rows the plan may give up."""
    scored = []
    for shift in range(1, h):
        score = 0
        for r in range(shift, h):
            if tgt_lines[r] != blank and tgt_lines[r] == src_lines[r - shift]:
                score += 1
        if score:
            scored.append((score, -shift))
    scored.sort(reverse=True)
    out = [0, 1]
    for _, neg in scored[:keep]:
        out.append(-neg)
    seen = []
    for value in out:
        if value not in seen and 0 <= value < h:
            seen.append(value)
    return seen


def _tiers(lengths, h):
    """Group block sizes 1..h into runs that cost the same number of bytes."""
    out = []
    n = 1
    while n <= h:
        m = n
        while m + 1 <= h and lengths[m + 1] == lengths[n]:
            m += 1
        out.append((n, m, lengths[n]))
        n = m + 1
    return out


def _align(src_stream, tgt_lines, h, blank, caps, cache, budget, ub,
           center=0, band=None):
    """One exact alignment pass for a fixed prologue budget."""
    ns = len(src_stream) + 1
    cup_len = [len(cup(j, 0)) for j in range(h + 1)]
    dl_tiers = _tiers([0] + [len(dl(n)) for n in range(1, h + 1)], h)
    il_tiers = _tiers([0] + [len(il(n)) for n in range(1, h + 1)], h)
    a_del, _, c_del = dl_tiers[-1]
    a_ins, _, c_ins = il_tiers[-1]

    tail_blank = _tail_blank_flags(tgt_lines, blank)
    nonblank = [0] * ns
    for k, line in enumerate(src_stream):
        nonblank[k + 1] = nonblank[k] + (0 if line == blank else 1)

    blank_cost = [cache.get(blank, tgt_lines[j], j, caps)[1] for j in range(h)]
    prefix = [0.0] * (h + 1)
    for j in range(h):
        prefix[j + 1] = prefix[j] + blank_cost[j]

    dp = [[INF] * ns for _ in range(h + 1)]
    par = [[None] * ns for _ in range(h + 1)]
    look = [[INF] * ns for _ in range(h + 1)]
    ins_v = [INF] * ns
    ins_j = [-1] * ns
    dp[0][0] = 0.0
    look[0][0] = cup_len[0] - prefix[0]

    for j in range(h + 1):
        dj = dp[j]
        pj = par[j]
        lo = max(0, j - budget)
        hi = ns - 1
        if band is not None:
            if lo < j + center - band:
                lo = j + center - band
            if hi > j + center + band:
                hi = j + center + band
        if caps.il:
            fold = j - a_ins
            if fold >= 0:
                row = look[fold]
                for i in range(ns):
                    v = row[i]
                    if v < ins_v[i]:
                        ins_v[i] = v
                        ins_j[i] = fold
        pre_v = INF
        pre_i = -1
        for i in range(lo, hi + 1):
            if caps.il and j > 0:
                bv = INF
                bj = -1
                for a, b, c in il_tiers[:-1]:
                    j0 = j - b
                    if j0 < 0:
                        j0 = 0
                    for j1 in range(j0, j - a + 1):
                        v = look[j1][i] + c
                        if v < bv:
                            bv = v
                            bj = j1
                if ins_j[i] >= 0 and ins_v[i] + c_ins < bv:
                    bv = ins_v[i] + c_ins
                    bj = ins_j[i]
                if bj >= 0:
                    v = bv + prefix[j]
                    if v < dj[i] and v <= ub:
                        dj[i] = v
                        pj[i] = (bj, i, ("ins", j - bj, bj))
            if caps.dl and j < h:
                k = i - a_del
                if k >= lo and dj[k] < pre_v:
                    pre_v = dj[k]
                    pre_i = k
                bv = INF
                bi = -1
                for a, b, c in dl_tiers[:-1]:
                    k0 = i - b
                    if k0 < lo:
                        k0 = lo
                    for k in range(k0, i - a + 1):
                        v = dj[k] + c
                        if v < bv:
                            bv = v
                            bi = k
                if pre_i >= 0 and pre_v + c_del < bv:
                    bv = pre_v + c_del
                    bi = pre_i
                if bi >= 0:
                    v = bv + cup_len[j]
                    if v < dj[i] and v <= ub:
                        dj[i] = v
                        pj[i] = (j, bi, ("del", i - bi, j))

            cur = dj[i]
            if cur == INF or cur > ub or j == h:
                continue
            look[j][i] = cur + cup_len[j] - prefix[j]

            if i < ns - 1:
                _, lc = cache.get(src_stream[i], tgt_lines[j], j, caps)
                nxt = cur + lc
                if nxt <= ub and nxt < dp[j + 1][i + 1]:
                    dp[j + 1][i + 1] = nxt
                    par[j + 1][i + 1] = (j, i, ("match", i, j))

            if caps.ed and tail_blank[j]:
                hi = i + (h - j)
                if hi > ns - 1:
                    hi = ns - 1
                if hi > i and nonblank[hi] - nonblank[i] > 0:
                    nxt = cur + cup_len[j] + len(ed())
                    if nxt <= ub and nxt < dp[h][i]:
                        dp[h][i] = nxt
                        par[h][i] = (j, i, ("ed", j))
    return dp, par, ns


def _reconstruct(dp, par, ns, h, src_stream, tgt_lines, blank, caps, cache):
    """Walk the parent pointers back and turn the actions into ops."""
    end_i = min(range(ns), key=lambda i: dp[h][i])
    if dp[h][end_i] == INF:
        return None, INF
    actions = []
    j, i = h, end_i
    while (j, i) != (0, 0):
        step = par[j][i]
        if step is None:
            return None, INF
        pj, pi, action = step
        actions.append(action)
        j, i = pj, pi
    actions.reverse()

    ops = []
    for action in actions:
        kind = action[0]
        if kind == "match":
            line_ops, _ = cache.get(src_stream[action[1]], tgt_lines[action[2]],
                                    action[2], caps)
            ops.extend(line_ops)
        elif kind == "del":
            ops.append(("cup", action[2], 0))
            ops.append(("dl", action[1]))
        elif kind == "ins":
            n, tj = action[1], action[2]
            ops.append(("cup", tj, 0))
            ops.append(("il", n))
            for t in range(n):
                line_ops, _ = cache.get(blank, tgt_lines[tj + t], tj + t, caps)
                ops.extend(line_ops)
        elif kind == "ed":
            ops.append(("cup", action[1], 0))
            ops.append(("ed",))
    return ops, cost(ops)


def plan_frame(src_screen, tgt_screen, caps, cache=None, ub=INF, warm=True,
               band=None, budgets=None):
    """Cheapest op list turning one screen into the next. Returns (ops, bytes)."""
    h = src_screen.h
    w = src_screen.w
    blank = BLANK * w
    src_lines = src_screen.lines()
    tgt_lines = tgt_screen.lines()
    if cache is None:
        cache = LineCache()

    best_ops = None
    best_cost = ub
    center, _ = best_shift(src_lines, tgt_lines, h, blank)
    if warm:
        wops, wcost = shift_plan(src_lines, tgt_lines, h, blank, caps, cache)
        if wcost < best_cost:
            best_ops, best_cost = wops, wcost

    if budgets is None:
        budgets = loss_candidates(src_lines, tgt_lines, h, blank) if caps.il else [0]
        if band is not None:
            budgets = budgets[:2]
    for budget in budgets:
        if budget and not caps.dl:
            continue
        prologue = []
        if budget:
            prologue = [("cup", h - budget, 0), ("dl", budget)]
        head = cost(prologue)
        if head >= best_cost:
            continue
        stream = src_lines[: h - budget] + [blank] * (h + budget)
        dp, par, ns = _align(stream, tgt_lines, h, blank, caps, cache, budget,
                             best_cost - head, max(center, 0), band)
        ops, body = _reconstruct(dp, par, ns, h, stream, tgt_lines, blank,
                                 caps, cache)
        if ops is not None and head + body < best_cost:
            best_cost = head + body
            best_ops = prologue + ops

    if best_ops is None:
        stream = src_lines + [blank] * h
        dp, par, ns = _align(stream, tgt_lines, h, blank, caps, cache, 0, INF)
        best_ops, best_cost = _reconstruct(dp, par, ns, h, stream, tgt_lines,
                                           blank, caps, cache)
    return best_ops, best_cost
