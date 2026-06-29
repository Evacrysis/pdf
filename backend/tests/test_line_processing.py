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


def test_merges_1_9_channel_semantic_pair() -> None:
    lines = [
        _line(0, "1-9 Channel: One channel ", (10, 10, 110, 25)),
        _line(1, "corresponds to one blind.", (10, 25, 120, 40)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert merged[0].text == "1-9 Channel: One channel corresponds to one blind."
    assert merged[0].bbox == (10, 10, 120, 40)
    assert fixed_translation_for(merged[0]) == "1～9チャンネル：\n1チャンネルに1台の\nシェードを登録できます。"


def test_fixed_control_all_blinds_translation_is_compact() -> None:
    lines = [
        _line(0, "Control All Blinds", (10, 10, 120, 25)),
        _line(1, "(max 9 blinds)", (10, 25, 110, 40)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert fixed_translation_for(merged[0]) == "全シェード制御\n（最大9台）"


def test_merges_example_operation_paragraph() -> None:
    lines = [
        _line(0, "If there are 9 blinds, and you want to open ", (10, 10, 200, 25)),
        _line(1, "blinds 1, 3, and 5 together, the operation method is:", (10, 25, 230, 40)),
        _line(2, 'Press 1, 3, and 5 in sequence, and then press " Open ".', (10, 40, 260, 55)),
    ]

    merged = merge_known_semantic_lines(lines)

    assert len(merged) == 1
    assert fixed_translation_for(merged[0]) == (
        "シェードが9台あり、そのうち1・3・5を同時に開ける場合は、\n"
        "「1」→「3」→「5」の順に押し、その後「開」を押します。"
    )
