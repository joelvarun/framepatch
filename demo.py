"""Run every strategy over every workload, then write the metrics and figure.

    python demo.py

Writes docs/metrics.json and docs/before_after.png and prints the table that
the README quotes. Nothing is downloaded and nothing is simulated: the frames
come from real files in the local standard library, and every byte count is
the length of a stream that was replayed against an emulator and checked.
"""

import argparse
import os

from framepatch.bench import run, save
from framepatch.chart import build

ROWS = ("full", "lines", "ptk", "shift", "align", "fast", "framepatch")


def table(metrics):
    names = metrics["order"]
    head = "%-11s" % "workload" + "".join("%12s" % n for n in names)
    lines = [head, "-" * len(head)]
    for w in metrics["workloads"]:
        row = "%-11s" % w["name"]
        for n in names:
            row += "%12.0f" % w["strategies"][n]["mean"]
        lines.append(row)
    lines.append("-" * len(head))
    row = "%-11s" % "mean"
    for n in names:
        row += "%12.1f" % metrics["overall"][n]["mean_bytes"]
    lines.append(row)
    row = "%-11s" % "plan us"
    for n in names:
        row += "%12.0f" % metrics["overall"][n]["plan_us"]
    lines.append(row)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs", help="output directory")
    parser.add_argument("--no-chart", action="store_true",
                        help="skip the figure, write metrics only")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    metrics = run()
    save(metrics, os.path.join(args.out, "metrics.json"))

    print()
    print(table(metrics))
    print()
    head = metrics["headline"]
    ver = metrics["verification"]
    cost = metrics["cost"]
    print("baseline          prompt_toolkit %s, its own renderer, %.1f bytes/frame"
          % (metrics["meta"]["prompt_toolkit"], head["baseline_mean_bytes"]))
    print("framepatch        %.1f bytes per frame, %.2f times fewer"
          % (head["framepatch_mean_bytes"], head["factor"]))
    print("session total     %d bytes against %d"
          % (head["total_framepatch_bytes"], head["total_baseline_bytes"]))
    print("verification      %d of %d streams replayed to the exact target frame"
          % (ver["exact_matches"], ver["streams_checked"]))
    print("planning cost     %.1f ms per frame, break even link rate %.2f Mbit/s"
          % (cost["framepatch_plan_us"] / 1000.0,
             cost["breakeven_mbit_per_second"]))
    print("fast mode         %.1f bytes per frame at %.1f ms, break even %.2f Mbit/s"
          % (metrics["ablation"]["fast_mean_bytes"],
             cost["fast_plan_us"] / 1000.0,
             cost["fast_breakeven_mbit_per_second"]))

    if not args.no_chart:
        path = build(metrics, os.path.join(args.out, "before_after.png"))
        print("chart             %s" % path)


if __name__ == "__main__":
    main()
