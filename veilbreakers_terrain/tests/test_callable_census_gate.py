from scripts.callable_census_gate import CallableEntry, CensusResult


def test_census_result_reports_zero_uncovered_as_full_coverage():
    result = CensusResult(total_callables=4, graded_callables=4)

    assert result.uncovered_count == 0
    assert result.coverage_pct == 100.0


def test_census_result_counts_uncovered_callables():
    result = CensusResult(
        total_callables=4,
        graded_callables=3,
        uncovered=[
            CallableEntry(
                filename="terrain_waterfalls.py",
                func_name="build_waterfall_profile",
                qualified_name="build_waterfall_profile",
                lineno=42,
            )
        ],
    )

    assert result.uncovered_count == 1
    assert result.coverage_pct == 75.0
