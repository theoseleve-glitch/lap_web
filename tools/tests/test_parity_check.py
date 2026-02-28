import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parity_check import compare_values, compare_dicts, ParityResult

def test_exact_match():
    r = compare_values(42, 42, "test")
    assert r.passed

def test_float_within_tolerance():
    r = compare_values(45.1234, 45.1235, "lap_time", tolerance=0.001)
    assert r.passed

def test_float_outside_tolerance():
    r = compare_values(45.123, 45.200, "lap_time", tolerance=0.001)
    assert not r.passed

def test_none_match():
    r = compare_values(None, None, "test")
    assert r.passed

def test_none_vs_value():
    r = compare_values(None, 42, "test")
    assert not r.passed

def test_string_match():
    r = compare_values("A", "A", "grade")
    assert r.passed

def test_string_mismatch():
    r = compare_values("A", "B", "grade")
    assert not r.passed

def test_list_length_mismatch():
    r = compare_values([1, 2], [1, 2, 3], "laps")
    assert not r.passed

def test_list_match():
    r = compare_values([1.0, 2.0], [1.0, 2.0], "laps", tolerance=0.001)
    assert r.passed

def test_compare_dicts_all_pass():
    baseline = {"scores": {"pace": 22.5, "grade": "A"}, "lap_times": [45.1]}
    webapp = {"scores": {"pace": 22.5, "grade": "A"}, "lap_times": [45.1]}
    results = compare_dicts(baseline, webapp)
    assert all(r.passed for r in results)

def test_compare_dicts_with_failure():
    baseline = {"scores": {"pace": 22.5}}
    webapp = {"scores": {"pace": 20.0}}
    results = compare_dicts(baseline, webapp, tolerance=0.5)
    assert not all(r.passed for r in results)

def test_tolerance_auto_classification_time():
    r = compare_values(45.123, 45.1235, "lap_time_s")
    assert r.passed  # within 0.001s default for time fields

def test_tolerance_auto_classification_score():
    r = compare_values(22.5, 22.9, "pace_score")
    assert r.passed  # within 0.5 default for score fields

def test_extra_webapp_key_is_ok():
    baseline = {"a": 1}
    webapp = {"a": 1, "b": 2}
    results = compare_dicts(baseline, webapp)
    assert all(r.passed for r in results)

def test_missing_webapp_key_is_failure():
    baseline = {"a": 1, "b": 2}
    webapp = {"a": 1}
    results = compare_dicts(baseline, webapp)
    assert not all(r.passed for r in results)

def test_diff_report_generation(tmp_path):
    from parity_check import run_parity_check
    import json

    baseline_path = tmp_path / "baseline.json"
    webapp_path = tmp_path / "webapp.json"
    output_path = tmp_path / "diff.txt"

    baseline_path.write_text(json.dumps({"score": 22.5, "grade": "A"}))
    webapp_path.write_text(json.dumps({"score": 20.0, "grade": "A"}))

    passed, results = run_parity_check(str(baseline_path), str(webapp_path), output_path=str(output_path))
    assert not passed
    assert output_path.exists()
    content = output_path.read_text()
    assert "FAIL" in content
