"""Unit tests for Phase 8B: Hardened string matching (BenchJack Pattern 5).

Tests MatchingEngine and NumericComparator for robust structural comparisons.
"""


from services.structural_scorer import MatchingEngine, NumericComparator

# =========================================================================
# MatchingEngine — normalize_for_comparison
# =========================================================================


class TestNormalizeForComparison:
    def setup_method(self):
        self.engine = MatchingEngine()

    def test_lowercases(self):
        assert self.engine.normalize_for_comparison("Hello World") == "hello world"

    def test_strips_whitespace(self):
        assert self.engine.normalize_for_comparison("  hello  ") == "hello"

    def test_collapses_multiple_spaces(self):
        assert self.engine.normalize_for_comparison("hello    world") == "hello world"

    def test_preserves_punctuation(self):
        """DO NOT strip punctuation — unlike GAIA's broken normalizer."""
        result = self.engine.normalize_for_comparison("Hello, World! $100.")
        assert "," in result
        assert "!" in result
        assert "$" in result
        assert "." in result

    def test_preserves_numbers(self):
        assert self.engine.normalize_for_comparison("value: 42") == "value: 42"

    def test_preserves_number_formatting(self):
        """'1,500' != '1500' != '15.00' — different formatting preserved."""
        assert self.engine.normalize_for_comparison("1,500") != self.engine.normalize_for_comparison("1500")
        assert self.engine.normalize_for_comparison("1500") != self.engine.normalize_for_comparison("15.00")

    def test_preserves_unicode(self):
        assert self.engine.normalize_for_comparison("café résumé") == "café résumé"


# =========================================================================
# MatchingEngine — are_tool_calls_duplicate
# =========================================================================


class TestAreToolCallsDuplicate:
    def setup_method(self):
        self.engine = MatchingEngine()

    def test_identical_calls_are_duplicate(self):
        call_a = {"name": "search", "input": {"query": "hello"}}
        call_b = {"name": "search", "input": {"query": "hello"}}
        assert self.engine.are_tool_calls_duplicate(call_a, call_b, span_distance=1)

    def test_different_tool_names_not_duplicate(self):
        call_a = {"name": "search", "input": {"query": "hello"}}
        call_b = {"name": "read_file", "input": {"query": "hello"}}
        assert not self.engine.are_tool_calls_duplicate(call_a, call_b)

    def test_different_params_not_duplicate(self):
        call_a = {"name": "search", "input": {"query": "hello"}}
        call_b = {"name": "search", "input": {"query": "world"}}
        assert not self.engine.are_tool_calls_duplicate(call_a, call_b)

    def test_slightly_different_params_not_duplicate(self):
        """Even slightly different params should NOT be duplicates."""
        call_a = {"name": "search", "input": {"query": "hello", "limit": 10}}
        call_b = {"name": "search", "input": {"query": "hello", "limit": 11}}
        assert not self.engine.are_tool_calls_duplicate(call_a, call_b)

    def test_far_apart_spans_not_duplicate(self):
        """Calls >5 spans apart could be intentional retries."""
        call_a = {"name": "search", "input": "hello"}
        call_b = {"name": "search", "input": "hello"}
        assert not self.engine.are_tool_calls_duplicate(call_a, call_b, span_distance=6)

    def test_json_key_order_does_not_matter(self):
        """Params with different key order should still be duplicates."""
        call_a = {"name": "search", "input": {"query": "hello", "limit": 10}}
        call_b = {"name": "search", "input": {"limit": 10, "query": "hello"}}
        assert self.engine.are_tool_calls_duplicate(call_a, call_b, span_distance=1)

    def test_string_input_comparison(self):
        """String inputs should be compared directly."""
        call_a = {"name": "bash", "input": "ls -la"}
        call_b = {"name": "bash", "input": "ls -la"}
        assert self.engine.are_tool_calls_duplicate(call_a, call_b, span_distance=1)

    def test_number_normalization(self):
        """Integer 10 and float 10.0 should be treated as equal."""
        call_a = {"name": "query", "input": {"limit": 10}}
        call_b = {"name": "query", "input": {"limit": 10.0}}
        assert self.engine.are_tool_calls_duplicate(call_a, call_b, span_distance=1)


# =========================================================================
# MatchingEngine — is_output_section_present
# =========================================================================


class TestIsOutputSectionPresent:
    def setup_method(self):
        self.engine = MatchingEngine()

    def test_markdown_header_present(self):
        output = "## Root Cause\nThe server crashed due to an out-of-memory error in the worker process."
        assert self.engine.is_output_section_present(output, "Root Cause")

    def test_bold_header_present(self):
        output = "**Root Cause:** The server crashed due to an out-of-memory error in the worker."
        assert self.engine.is_output_section_present(output, "Root Cause")

    def test_colon_header_present(self):
        output = "Root Cause: The server crashed due to an out-of-memory error in the worker process."
        assert self.engine.is_output_section_present(output, "Root Cause")

    def test_missing_section(self):
        output = "## Summary\nEverything looks good, no issues found in the analysis."
        assert not self.engine.is_output_section_present(output, "Root Cause")

    def test_stub_section_fails(self):
        """Section with < 20 non-whitespace chars should fail."""
        output = "## Root Cause\nTODO"
        assert not self.engine.is_output_section_present(output, "Root Cause")

    def test_empty_section_fails(self):
        """Completely empty section should fail."""
        output = "## Root Cause\n\n## Next Steps\nSome real content here that is long enough."
        assert not self.engine.is_output_section_present(output, "Root Cause")

    def test_duplicate_content_detected(self):
        """Section whose content matches another section should fail."""
        content = "The server crashed due to an out-of-memory error in the worker process."
        output = f"## Root Cause\n{content}\n## Next Steps\n{content}"
        # When checking Next Steps, pass Root Cause's content as existing
        assert not self.engine.is_output_section_present(
            output, "Next Steps", all_section_contents=[content]
        )

    def test_format_check_bullet_list(self):
        output = "## Steps\n- First do this\n- Then do that\n- Finally check results"
        assert self.engine.is_output_section_present(output, "Steps", expected_format="bullet list")

    def test_format_check_bullet_list_fails(self):
        output = "## Steps\nJust a plain paragraph with enough content to pass the length check."
        assert not self.engine.is_output_section_present(output, "Steps", expected_format="bullet list")

    def test_format_check_json(self):
        output = '## Config\n{"key": "value", "count": 42, "enabled": true}'
        assert self.engine.is_output_section_present(output, "Config", expected_format="json")

    def test_case_insensitive_header_match(self):
        output = "## root cause\nThe server crashed due to an out-of-memory error in the worker process."
        assert self.engine.is_output_section_present(output, "Root Cause")


# =========================================================================
# NumericComparator — numbers_match
# =========================================================================


class TestNumericComparator:
    def setup_method(self):
        self.comp = NumericComparator()

    def test_same_number_different_formatting(self):
        """$1,500 vs $1500 should match."""
        assert self.comp.numbers_match("$1,500", "$1500")

    def test_suffix_m_matches_full_number(self):
        """Revenue was $2.3M vs revenue: 2300000 should match."""
        assert self.comp.numbers_match("Revenue was $2.3M", "revenue: 2300000")

    def test_percentage_matches_decimal(self):
        """15% vs 0.15 should match."""
        assert self.comp.numbers_match("15%", "0.15")

    def test_different_numbers_dont_match(self):
        """1,500 vs 15.00 should NOT match — different numbers entirely."""
        assert not self.comp.numbers_match("1,500", "15.00")

    def test_no_numbers_returns_false(self):
        """No extractable numbers should return False."""
        assert not self.comp.numbers_match("hello", "world")

    def test_one_side_no_numbers_returns_false(self):
        assert not self.comp.numbers_match("revenue: 100", "no numbers here")

    def test_exact_match(self):
        assert self.comp.numbers_match("42", "42")

    def test_close_within_tolerance(self):
        """Values within 1% tolerance should match."""
        assert self.comp.numbers_match("100", "99.5", tolerance=0.01)

    def test_outside_tolerance(self):
        """Values outside tolerance should not match."""
        assert not self.comp.numbers_match("100", "90", tolerance=0.01)

    def test_suffix_k(self):
        """2.5K should equal 2500."""
        assert self.comp.numbers_match("2.5K users", "2500 total users")

    def test_suffix_b(self):
        """$1.2B should equal 1200000000."""
        assert self.comp.numbers_match("$1.2B", "1200000000")

    def test_negative_numbers(self):
        assert self.comp.numbers_match("loss: -500", "net: -500")

    def test_zero_values(self):
        assert self.comp.numbers_match("0", "0.00")

    def test_currency_symbols_ignored(self):
        """Currency symbols should not prevent matching."""
        assert self.comp.numbers_match("$100", "100 dollars")
        assert self.comp.numbers_match("€50", "50")
