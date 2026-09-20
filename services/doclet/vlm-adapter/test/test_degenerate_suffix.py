"""Regression test for doclet_vlm_adapter's degenerate-suffix trimmer.

degenerate_suffix_fixture_599.txt is the real, unmodified output from a
genuine production run (experiments/doclet-service/production-run-2026-09-18-v2,
formula #/texts/599) -- not a synthetic example. Stdlib-only, run directly
(no pytest dependency, matching this project's other adapter code):

    python3 test/test_degenerate_suffix.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from doclet_vlm_adapter import _detect_degenerate_suffix, _sanitize_output  # noqa: E402

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "degenerate_suffix_fixture_599.txt")


def test_real_production_fixture():
    with open(FIXTURE_PATH) as f:
        text = f.read()

    hit = _detect_degenerate_suffix(text)
    assert hit is not None, "expected the real degenerate output to be detected"
    trim_index, period, repeats = hit
    assert period == 2, f"expected the '\\\\ ' (backslash-space) unit, got period={period}"
    assert repeats >= 8

    trimmed, finish_reason = _sanitize_output(request_id=0, text=text)
    assert finish_reason == "length"
    assert "\\quad ( 3 )" in trimmed, "the real equation content must survive the trim"
    assert "\\ \\ \\ " not in trimmed, "trimmed output must not still contain the repeated run"
    print(f"OK: trimmed {len(text) - len(trimmed)} of {len(text)} chars, "
          f"recovered prefix: {trimmed!r}")


def test_normal_output_untouched():
    normal = (
        "\\sigma ^ { T + 1 } ( I , a ) = \\frac { R _ { i } ^ { T , + } ( I , a ) } "
        "{ \\sum _ { b \\in A ( I ) } R _ { i } ^ { T , + } ( I , b ) } \\quad ( 1 )"
    )
    trimmed, finish_reason = _sanitize_output(request_id=0, text=normal)
    assert trimmed == normal
    assert finish_reason == "stop"
    print("OK: normal formula output passes through unchanged")


def test_short_legitimate_repetition_not_flagged():
    # A real table/list can legitimately repeat a short token a handful of
    # times -- the detector must not fire on this, only on a long run.
    text = "The values were 0.0 0.0 0.0 across all three trials, as expected."
    hit = _detect_degenerate_suffix(text)
    assert hit is None, "a few legitimate repeats must not be flagged"
    print("OK: short legitimate repetition left alone")


def test_no_prefix_not_flagged():
    # All-repetition with no real content before it doesn't meet the
    # "substantial non-repeating prefix" bar -- conservative by design,
    # even though this actually looks pathological too.
    text = "\\ " * 50
    hit = _detect_degenerate_suffix(text)
    assert hit is None, "a suffix with no real prefix must not be flagged (too conservative to trim blindly)"
    print("OK: repetition with no real prefix left alone (conservative)")


if __name__ == "__main__":
    test_real_production_fixture()
    test_normal_output_untouched()
    test_short_legitimate_repetition_not_flagged()
    test_no_prefix_not_flagged()
    print("\nall tests passed")
