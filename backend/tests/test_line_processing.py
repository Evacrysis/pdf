from app.models import TextLine
from app.services.line_processing import fixed_translation_for, merge_known_semantic_lines


def _line(index: int, text: str, bbox: tuple[float, float, float, float]) -> TextLine:
    return TextLine(
        page_index=0,
        line_index=index,
        text=text,
        bbox=bbox,
        font_name="Inter",
        font_size=14,
        role="body",
        protected_tokens=[],
        localizable=True,
    )


def _warning_line(index: int, text: str, y0: float) -> TextLine:
    return TextLine(
        page_index=0,
        line_index=index,
        text=text,
        bbox=(84.4, y0, 558.8, y0 + 20),
        origin=(84.4, y0 + 15.5),
        font_name="Helvetica",
        font_size=14,
        role="emphasis",
        localizable=True,
    )


def test_merges_1_9_channel_semantic_pair() -> None:
    lines = [
        _line(0, "1-9 Channel: One channel ", (10, 10, 110, 25)),
        _line(1, "corresponds to one blind.", (10, 25, 120, 40)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert merged[0].text == "1-9 Channel: One channel corresponds to one blind."
    assert merged[0].bbox == (10, 10, 120, 40)
    assert fixed_translation_for(merged[0]) == "1～9チャンネル：1チャンネルに1台のシェードを登録できます。"


def test_fixed_control_all_blinds_translation_is_compact() -> None:
    lines = [
        _line(0, "Control All Blinds", (10, 10, 120, 25)),
        _line(1, "(max 9 blinds)", (10, 25, 110, 40)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert fixed_translation_for(merged[0]) == "全シェード制御（最大9台）"


def test_merges_example_operation_paragraph() -> None:
    lines = [
        _line(0, "If there are 9 blinds, and you want to open ", (10, 10, 200, 25)),
        _line(1, "blinds 1, 3, and 5 together, the operation method is:", (10, 25, 230, 40)),
        _line(2, 'Press 1, 3, and 5 in sequence, and then press " Open ".', (10, 40, 260, 55)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert fixed_translation_for(merged[0]) == (
        "シェードが9台あり、そのうち1・3・5を同時に開ける場合は、"
        "「1」→「3」→「5」の順に押し、その後「開」を押します。"
    )


def test_cable_length_uses_metric_only_fixed_translation() -> None:
    assert fixed_translation_for(_line(0, '118"(3m)', (10, 10, 80, 25))) == "3m"
    assert fixed_translation_for(_line(0, "118ˮ(3m)", (10, 10, 80, 25))) == "3m"
    assert fixed_translation_for(_line(0, '78.7"(2m)', (10, 10, 80, 25))) == "2m"


def test_fixed_translation_preserves_compact_time_and_count_tokens() -> None:
    assert fixed_translation_for(_line(0, "Hold for 16s", (10, 10, 80, 25))) == "16s押し続ける"
    assert fixed_translation_for(_line(0, "Blind jogs 4x", (10, 10, 80, 25))) == "ブラインドが軽く動きます 4x"


def test_fixed_light_labels_are_compact() -> None:
    assert fixed_translation_for(_line(0, "Orange Light", (10, 10, 80, 25))) == "オレンジランプ"
    assert fixed_translation_for(_line(0, "Blue Light", (10, 10, 80, 25))) == "ブルーランプ"
    assert fixed_translation_for(_line(0, "Solid Blue", (10, 10, 80, 25))) == "ブルー点灯"


def test_merges_and_fixes_quote_gap_check_channel_rows() -> None:
    lines = [
        _line(0, 'Press "    " or "    ",', (373, 381, 504, 402)),
        _line(1, "check channel.", (373, 396, 474, 416)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert merged[0].text == 'Press " " or " ", check channel.'
    assert fixed_translation_for(merged[0]) == "「□」または「□」を押す\nチャンネル確認"


def test_merges_and_fixes_quote_gap_check_group_rows() -> None:
    lines = [
        _line(0, 'Press "    " or "    ",', (373, 413, 500, 433)),
        _line(1, "check group.", (373, 427, 460, 447)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert fixed_translation_for(merged[0]) == "「□」または「□」を押す\nグループ確認"


def test_fixed_quote_gap_operation_rows_preserve_icon_placeholders() -> None:
    assert fixed_translation_for(_line(0, 'Press "     "', (10, 10, 90, 25))) == "「□」を押す"
    assert fixed_translation_for(_line(0, 'Hold "     " for 5s', (10, 10, 90, 25))) == "「□」を5s押し続ける"
    assert (
        fixed_translation_for(_line(0, 'Press " " to select other channel numbers.', (10, 10, 90, 25)))
        == "「□」を押して他のチャンネル番号を選択します。"
    )


def test_continuation_warning_lines_merge_into_one_semantic_block() -> None:
    lines = [
        _warning_line(0, "Congratulations! Remove the sleeping blocker, chooes the channel number", 509.1),
        _warning_line(1, "(attached to the bottom rod ) to control the shade. If it cannot work, please", 525.1),
        _warning_line(2, "refer to page 9-17.", 541.1),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert "refer to page 9-17" in merged[0].text
    assert fixed_translation_for(merged[0]) is not None
    assert "\n" not in fixed_translation_for(merged[0])
