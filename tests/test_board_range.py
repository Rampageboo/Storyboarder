"""Board range specs — the export dialog's "1-5, 8" field."""
from __future__ import annotations

import pytest

from storyboard_tool import board_range


class TestParse:
    def test_single_board(self) -> None:
        assert board_range.parse("3", 10) == [2]

    def test_inclusive_range(self) -> None:
        assert board_range.parse("2-5", 10) == [1, 2, 3, 4]

    def test_mixed_list(self) -> None:
        assert board_range.parse("1-3, 6, 9-10", 10) == [0, 1, 2, 5, 8, 9]

    def test_whitespace_and_semicolons_are_separators(self) -> None:
        assert board_range.parse(" 1 ; 4 , 7 ", 10) == [0, 3, 6]

    def test_overlapping_entries_are_deduplicated_and_sorted(self) -> None:
        assert board_range.parse("5, 1-3, 2, 4", 10) == [0, 1, 2, 3, 4]

    def test_open_ended_start_runs_to_the_last_board(self) -> None:
        assert board_range.parse("8-", 10) == [7, 8, 9]

    def test_open_ended_end_runs_from_the_first_board(self) -> None:
        assert board_range.parse("-3", 10) == [0, 1, 2]

    def test_reversed_range_is_normalised(self) -> None:
        assert board_range.parse("5-2", 10) == [1, 2, 3, 4]

    def test_en_dash_is_accepted(self) -> None:
        # Editors autocorrect a hyphen into an en dash; the user still means a range.
        assert board_range.parse("2–4", 10) == [1, 2, 3]

    @pytest.mark.parametrize("spec", ["", "   ", ",", " , ; "])
    def test_empty_spec_is_rejected(self, spec: str) -> None:
        with pytest.raises(ValueError, match="Enter a board range"):
            board_range.parse(spec, 10)

    @pytest.mark.parametrize("spec", ["abc", "2-x", "1..3", "4/5"])
    def test_malformed_spec_names_the_offending_token(self, spec: str) -> None:
        with pytest.raises(ValueError, match="not a board number or range"):
            board_range.parse(spec, 10)

    @pytest.mark.parametrize("spec", ["0", "11", "5-20"])
    def test_out_of_range_reports_the_actual_board_count(self, spec: str) -> None:
        with pytest.raises(ValueError, match="this storyboard has 10"):
            board_range.parse(spec, 10)

    def test_empty_storyboard_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no boards to export"):
            board_range.parse("1", 0)


class TestFilenameSuffix:
    def test_full_selection_keeps_the_plain_name(self) -> None:
        assert board_range.filename_suffix([0, 1, 2], 3) == ""

    def test_single_board(self) -> None:
        assert board_range.filename_suffix([2], 10) == "_board-003"

    def test_contiguous_run(self) -> None:
        assert board_range.filename_suffix([2, 3, 4], 10) == "_boards-003-005"

    def test_short_gappy_selection_lists_every_board(self) -> None:
        assert board_range.filename_suffix([0, 4], 10) == "_boards-001+005"

    def test_long_gappy_selection_stays_a_readable_length(self) -> None:
        suffix = board_range.filename_suffix([0, 2, 4, 6, 8], 10)
        assert suffix == "_boards-001-009-selection"

    def test_distinct_ranges_get_distinct_names(self) -> None:
        # Two exports in one session must not silently overwrite each other.
        assert board_range.filename_suffix([0, 1], 10) != board_range.filename_suffix([2, 3], 10)


class TestDescribe:
    def test_full_selection(self) -> None:
        assert board_range.describe([0, 1, 2], 3) == "All 3 boards"

    def test_single_board(self) -> None:
        assert board_range.describe([4], 10) == "Board 5"

    def test_contiguous_run_shows_both_ends(self) -> None:
        assert board_range.describe([1, 2, 3], 10) == "Boards 2-4 (3 of 10)"

    def test_gappy_selection_shows_a_count(self) -> None:
        assert board_range.describe([0, 5, 9], 10) == "3 of 10 boards"

    def test_empty_selection(self) -> None:
        assert board_range.describe([], 10) == "No boards selected"
