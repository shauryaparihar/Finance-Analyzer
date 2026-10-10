"""
Reproducible timing of the analysis on a large synthetic upload.

    python -m backend.benchmark                      # 50,000 rows, 1 warm-up run, 7 measured runs
    python -m backend.benchmark --rows 10000 --runs 5 --out /tmp/bench.json

What is timed, per run (wall clock, single process, one CPU-bound thread):
  * parse_validate  - the same function the upload endpoint calls: size/row/column checks, type conversion, cleaning
  * pipeline        - categorization (the shipped model), forecast, unusual-transaction ranking and summary, exactly
                      as the background worker runs them; the four modules are also reported separately
What is NOT included: HTTP/network time, authentication, database reads and writes (queueing the job, storing the
transactions and results), JSON serialisation of the API responses and the browser. Do not read these numbers as the
time a person waits after pressing upload on the live site.

The data is generated here (generator version DATA_VERSION, fixed seed), so two runs on the same machine use identical
input. Descriptions are drawn from the project's synthetic merchant list; this says nothing about real statements.
"""
import argparse
import json
import platform
import statistics
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

DATA_VERSION = "benchmark-data-v1"
SEED = 20261010
MERCHANTS = [
    ("WHOLE FOODS MKT 10234 AUSTIN TX", 82), ("KROGER #4402 AUSTIN TX", 64), ("TRADER JOE'S #512", 47), ("COSTCO WHSE #0452", 143),
    ("STARBUCKS #4821 SEATTLE WA", 6), ("CHIPOTLE 2291 AUSTIN TX", 13), ("MCDONALD'S F3321", 9), ("DOORDASH*PIZZA PLACE", 28),
    ("SHELL OIL 57444 DALLAS TX", 44), ("UBER *TRIP HELP.UBER.COM", 19), ("CHEVRON 0098", 39), ("AMAZON.COM*2K4LP", 36),
    ("TARGET 00012345", 58), ("WALMART #5421", 42), ("CVS/PHARMACY #1822", 22), ("AMC THEATRES 0831", 31),
    ("NETFLIX.COM", 15.49), ("SPOTIFY USA", 10.99), ("COMCAST CABLE COMM", 79.99), ("VERIZON WIRELESS", 65.0),
]


def make_csv(rows: int) -> bytes:
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(MERCHANTS), size=rows)
    days = rng.integers(0, 3 * 365, size=rows)
    start = date(2023, 1, 1)
    frame = pd.DataFrame(
        {
            "date": [(start + timedelta(days=int(d))).isoformat() for d in days],
            "amount": [round(float(MERCHANTS[i][1] * rng.lognormal(0, 0.25)), 2) for i in idx],
            "description": [MERCHANTS[i][0] for i in idx],
        }
    )
    return frame.to_csv(index=False).encode()


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q, method="higher"))  # a real observed run, not an interpolated one


def summarise(values: list[float]) -> dict:
    return {"median_s": round(statistics.median(values), 3), "p95_s": round(percentile(values, 95), 3), "min_s": round(min(values), 3), "max_s": round(max(values), 3)}


class Timer:
    def __init__(self):
        self.modules: dict[str, float] = {}
        self._start: dict[str, float] = {}

    def on_start(self, module: str) -> None:
        self._start[module] = time.perf_counter()

    def on_finish(self, module: str, outcome, duration_ms: int) -> None:
        self.modules[module] = time.perf_counter() - self._start[module]
        self.modules[f"{module}_status"] = outcome.status


def one_run(csv_bytes: bytes, categorizer) -> dict:
    from backend.ml.pipeline import run_full_pipeline
    from backend.utils.csv_ingest import validate_and_clean_csv

    t0 = time.perf_counter()
    ingest = validate_and_clean_csv(csv_bytes, "benchmark.csv", "auto", max_bytes=10**9, max_rows=10**9, max_invalid_share=0.5)
    t1 = time.perf_counter()
    timer = Timer()
    run_full_pipeline(ingest.df, categorizer, timer)
    t2 = time.perf_counter()
    return {"parse_validate": t1 - t0, "pipeline": t2 - t1, "total": t2 - t0, "modules": timer.modules, "rows_after_cleaning": len(ingest.df)}


def environment() -> dict:
    import sklearn

    import backend.ml.categorizer as cat_module

    return {
        "python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
        "processor": platform.processor() or "unknown", "cpu_count": __import__("os").cpu_count(),
        "pandas": pd.__version__, "numpy": np.__version__, "scikit_learn": sklearn.__version__, "categorizer_module": cat_module.__name__,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--runs", type=int, default=7, help="measured runs (after the warm-up run)")
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--out", help="also write the JSON report to this path")
    args = parser.parse_args()

    from backend.ml.categorizer import load_categorizer

    categorizer = load_categorizer()
    csv_bytes = make_csv(args.rows)
    for _ in range(args.warmups):
        one_run(csv_bytes, categorizer)
    runs = [one_run(csv_bytes, categorizer) for _ in range(args.runs)]

    module_names = [k for k in runs[0]["modules"] if not k.endswith("_status")]
    report = {
        "data_version": DATA_VERSION, "seed": SEED, "rows_generated": args.rows, "rows_after_cleaning": runs[0]["rows_after_cleaning"],
        "csv_bytes": len(csv_bytes), "warmup_runs_discarded": args.warmups, "measured_runs": args.runs,
        "model_version": categorizer.version,
        "included": ["csv parse and validation", "categorization", "forecast", "unusual-transaction ranking", "summary"],
        "excluded": ["network/HTTP", "authentication", "database reads and writes", "job queueing", "API response serialisation", "browser rendering"],
        "parse_validate": summarise([r["parse_validate"] for r in runs]),
        "pipeline": summarise([r["pipeline"] for r in runs]),
        "total": summarise([r["total"] for r in runs]),
        "modules": {m: summarise([r["modules"][m] for r in runs]) for m in module_names},
        "module_status_last_run": {m: runs[-1]["modules"][f"{m}_status"] for m in module_names},
        "environment": environment(),
        "note": "p95 here is the 'higher' percentile of the measured runs; with few runs it equals the slowest run.",
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w") as handle:
            handle.write(text + "\n")


if __name__ == "__main__":
    main()
