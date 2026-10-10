"""Show the actual plan for one frame of one workload, op by op.

    python example_plan.py            scroll by one line
    python example_plan.py fold 3     frame 3 of the fold workload
"""

import sys

from framepatch.caps import Caps, render
from framepatch.plan import LineCache, plan_frame
from framepatch.screen import equal_exact, replay
from framepatch.strategies import STRATEGIES
from framepatch.workloads import all_workloads

NAMES = {"cup": "move to row %s column %s", "dl": "delete %s line(s)",
         "il": "insert %s blank line(s)", "ich": "insert %s blank(s) in line",
         "dch": "delete %s character(s) in line", "el": "erase to end of line",
         "ed": "erase to end of screen", "cha": "move to column %s",
         "cuf": "move right %s", "cr": "move to column 0",
         "write": "write %s"}


def describe(op):
    kind = op[0]
    args = op[1:]
    if kind == "write":
        return 'write "%s"' % args[0]
    if kind == "cup":
        return "move to row %d column %d" % (args[0] + 1, args[1] + 1)
    text = NAMES.get(kind, kind)
    return text % args if args else text


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "scroll"
    index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    frames = dict((n, f) for n, _, f in all_workloads())[name]
    src, tgt = frames[index], frames[index + 1]
    cache = LineCache()

    print("workload %s, frame %d to %d" % (name, index, index + 1))
    print()
    for sname, fn in STRATEGIES:
        _, planned = fn(src, tgt, None, cache)
        print("  %-11s %6d bytes" % (sname, planned))
    print()

    ops, planned = plan_frame(src, tgt, Caps(), cache)
    stream = render(ops)
    out, _ = replay(stream, src)
    print("framepatch plan, %d bytes, verified %s"
          % (planned, equal_exact(out, tgt)))
    for op in ops:
        print("  %-4s %-44s %2d bytes" % (op[0], describe(op), len(render([op]))))


if __name__ == "__main__":
    main()
