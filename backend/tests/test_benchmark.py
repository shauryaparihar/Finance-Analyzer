import numpy as np

from backend import benchmark as bm


def test_the_benchmark_input_is_identical_every_time():
    assert bm.make_csv(500) == bm.make_csv(500)
    assert bm.make_csv(500) != bm.make_csv(501)


def test_p95_is_an_observed_value_and_the_median_is_the_middle():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    summary = bm.summarise(values)
    assert summary["median_s"] == 4.0 and summary["p95_s"] == 7.0 and summary["max_s"] == 7.0
    assert bm.percentile(values, 95) in values
    assert np.isclose(bm.percentile([10.0], 95), 10.0)


def test_a_small_benchmark_run_reports_every_stage():
    from backend.ml.categorizer import load_categorizer

    run = bm.one_run(bm.make_csv(300), load_categorizer())
    assert run["rows_after_cleaning"] == 300
    assert {"categorization", "forecast", "anomaly", "summary"} <= set(run["modules"])
    assert run["total"] >= run["pipeline"] >= 0
