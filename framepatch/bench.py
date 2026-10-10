"""Run every strategy over every workload and verify every byte stream.

Rules of the measurement, applied uniformly:

* Each strategy is given consecutive frame pairs and must produce a stream
  that an emulator can replay on the old screen to reach the new screen. A
  frame that fails verification is counted and reported, never averaged away.
* Every strategy, including the third party baseline, is allowed to fall back
  to a full repaint when its own plan would be larger. Real renderers do this,
  and without it a strategy can be made to look bad by a frame it was never
  going to handle well.
* Byte counts are the length of the real stream, not a model of it.
"""

import json
import math
import platform
import sys
import time

from .caps import CSI, render
from .plan import LineCache
from .ptk_baseline import AVAILABLE as PTK_AVAILABLE
from .ptk_baseline import VERSION as PTK_VERSION
from .ptk_baseline import PtkRenderer, to_ptk_screen
from .screen import equal_exact, equal_trimmed, replay
from .strategies import STRATEGIES, full_redraw
from .workloads import H, W, all_workloads

ORDER = ("full", "lines", "ptk", "shift", "align", "fast", "framepatch")


def _blank_stats():
    return {"bytes": 0, "raw_bytes": 0, "max": 0, "seconds": 0.0, "fallback": 0,
            "frames": 0, "exact": 0, "trimmed": 0, "cup_bytes": 0}


def absolute_move_bytes(stream):
    """Bytes spent on absolute cursor positioning in a stream.

    The alignment pays one of these for every row it touches, because the
    cost of repainting a row has to be independent of the rest of the plan
    for the dynamic program to decompose. This counts the price of that.
    """
    total = 0
    n = len(stream)
    i = stream.find(CSI)
    while i >= 0:
        j = i + 2
        while j < n and (stream[j].isdigit() or stream[j] == ";"):
            j += 1
        if j < n and stream[j] == "H":
            total += j - i + 1
        i = stream.find(CSI, j + 1)
    return total


def run(progress=True):
    workloads = all_workloads()
    ptk = PtkRenderer(W, H) if PTK_AVAILABLE else None
    names = [n for n in ORDER if n != "ptk" or ptk is not None]

    table = dict(STRATEGIES)
    results = []
    overflow_total = 0
    verify_fail = []

    for wname, desc, frames in workloads:
        cache = LineCache()
        ptk_frames = [to_ptk_screen(f) for f in frames] if ptk else None
        stats = {n: _blank_stats() for n in names}
        for i in range(len(frames) - 1):
            src, tgt = frames[i], frames[i + 1]
            full_ops, full_bytes = full_redraw(src, tgt)
            full_stream = render(full_ops)

            for sname in names:
                start = time.perf_counter()
                if sname == "ptk":
                    stream = ptk.diff_screens(ptk_frames[i], ptk_frames[i + 1])
                else:
                    fn = table[sname]
                    ops, _ = fn(src, tgt, None, cache)
                    stream = render(ops)
                elapsed = time.perf_counter() - start

                out, emu = replay(stream, src)
                overflow_total += emu.overflow
                exact = equal_exact(out, tgt)
                trimmed = equal_trimmed(out, tgt)
                if not trimmed:
                    verify_fail.append((wname, i, sname))

                raw = len(stream)
                used = raw
                fallback = 0
                if len(full_stream) < raw:
                    used = len(full_stream)
                    fallback = 1

                st = stats[sname]
                st["raw_bytes"] += raw
                st["cup_bytes"] += absolute_move_bytes(stream)
                st["bytes"] += used
                st["max"] = max(st["max"], used)
                st["seconds"] += elapsed
                st["fallback"] += fallback
                st["frames"] += 1
                st["exact"] += 1 if exact else 0
                st["trimmed"] += 1 if trimmed else 0

        for st in stats.values():
            n = max(1, st["frames"])
            st["mean"] = st["bytes"] / n
            st["plan_us"] = 1e6 * st["seconds"] / n
        results.append({"name": wname, "description": desc,
                        "frames": len(frames), "transitions": len(frames) - 1,
                        "strategies": stats})
        if progress:
            line = "  ".join("%s %.0f" % (n, stats[n]["mean"]) for n in names)
            print("%-10s %s" % (wname, line))
            sys.stdout.flush()

    overall = {}
    for n in names:
        total = sum(r["strategies"][n]["bytes"] for r in results)
        frames = sum(r["strategies"][n]["frames"] for r in results)
        means = [r["strategies"][n]["mean"] for r in results if r["transitions"]]
        logs = [math.log(max(m, 1e-9)) for m in means]
        overall[n] = {
            "total_bytes": total,
            "mean_bytes": total / max(1, frames),
            "geomean_workload_mean": math.exp(sum(logs) / len(logs)),
            "plan_us": 1e6 * sum(r["strategies"][n]["seconds"] for r in results)
                       / max(1, frames),
            "fallback": sum(r["strategies"][n]["fallback"] for r in results),
            "frames": frames,
            "absolute_move_share": (
                sum(r["strategies"][n]["cup_bytes"] for r in results)
                / max(1, sum(r["strategies"][n]["raw_bytes"] for r in results))),
        }

    baseline = "ptk" if ptk is not None else "lines"
    base_mean = overall[baseline]["mean_bytes"]
    ours = overall["framepatch"]["mean_bytes"]
    saved = base_mean - ours
    extra = (overall["framepatch"]["plan_us"] - overall[baseline]["plan_us"]) / 1e6
    breakeven = saved / extra if extra > 0 else None
    fast_saved = base_mean - overall["fast"]["mean_bytes"]
    fast_extra = (overall["fast"]["plan_us"] - overall[baseline]["plan_us"]) / 1e6
    fast_breakeven = fast_saved / fast_extra if fast_extra > 0 else None

    metrics = {
        "meta": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "screen": "%dx%d" % (W, H),
            "prompt_toolkit": PTK_VERSION,
            "workloads": len(results),
            "transitions": sum(r["transitions"] for r in results),
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "order": names,
        "workloads": results,
        "overall": overall,
        "headline": {
            "metric": "bytes written to the terminal per frame",
            "baseline_name": baseline,
            "baseline_mean_bytes": base_mean,
            "framepatch_mean_bytes": ours,
            "factor": base_mean / ours if ours else None,
            "total_baseline_bytes": overall[baseline]["total_bytes"],
            "total_framepatch_bytes": overall["framepatch"]["total_bytes"],
        },
        "ablation": {
            "shift_mean_bytes": overall["shift"]["mean_bytes"],
            "align_mean_bytes": overall["align"]["mean_bytes"],
            "fast_mean_bytes": overall["fast"]["mean_bytes"],
            "framepatch_mean_bytes": ours,
        },
        "cost": {
            "framepatch_plan_us": overall["framepatch"]["plan_us"],
            "fast_plan_us": overall["fast"]["plan_us"],
            "baseline_plan_us": overall[baseline]["plan_us"],
            "breakeven_bytes_per_second": breakeven,
            "breakeven_mbit_per_second": breakeven * 8 / 1e6 if breakeven else None,
            "fast_breakeven_mbit_per_second":
                fast_breakeven * 8 / 1e6 if fast_breakeven else None,
            "ptk_null_frame_bytes": ptk.fixed_overhead(workloads[0][2][0])
                                    if ptk else None,
        },
        "verification": {
            "streams_checked": sum(
                r["strategies"][n]["frames"] for r in results for n in names),
            "exact_matches": sum(
                r["strategies"][n]["exact"] for r in results for n in names),
            "trimmed_matches": sum(
                r["strategies"][n]["trimmed"] for r in results for n in names),
            "failures": verify_fail,
            "autowrap_overflows": overflow_total,
        },
    }
    return metrics


def save(metrics, path):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)
