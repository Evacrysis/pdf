from __future__ import annotations

import re

from app.models import TextLine


def _norm(text: str) -> str:
    return " ".join(text.split())


def _union_bbox(lines: list[TextLine]) -> tuple[float, float, float, float]:
    return (
        min(line.bbox[0] for line in lines),
        min(line.bbox[1] for line in lines),
        max(line.bbox[2] for line in lines),
        max(line.bbox[3] for line in lines),
    )


def _merge(lines: list[TextLine], count: int, text: str) -> TextLine:
    first = lines[0]
    tokens: list[str] = []
    for line in lines[:count]:
        tokens.extend(token for token in line.protected_tokens if token not in tokens)
    return first.model_copy(
        update={
            "text": text,
            "bbox": _union_bbox(lines[:count]),
            "protected_tokens": tokens,
            "localizable": any(line.localizable for line in lines[:count]),
        }
    )


def _is_continuation_line(first: TextLine, candidate: TextLine) -> bool:
    if candidate.page_index != first.page_index:
        return False
    if first.role != candidate.role or first.role not in {"body", "emphasis"}:
        return False
    if abs(first.font_size - candidate.font_size) > 0.35:
        return False
    if abs(first.bbox[0] - candidate.bbox[0]) > 3:
        return False
    if candidate.bbox[1] - first.bbox[1] > first.font_size * 3.2:
        return False
    return len(_norm(candidate.text)) >= 12


def _merge_continuation_paragraph(lines: list[TextLine]) -> tuple[TextLine, int] | None:
    first = lines[0]
    if first.role not in {"body", "emphasis"} or len(_norm(first.text)) < 24:
        return None
    group = [first]
    for candidate in lines[1:4]:
        if not _is_continuation_line(first, candidate):
            break
        group.append(candidate)
    if len(group) < 2:
        return None
    text = " ".join(_norm(line.text) for line in group)
    return _merge(group, len(group), text), len(group)


def merge_known_semantic_lines(lines: list[TextLine]) -> list[TextLine]:
    """Merge repeated manual fragments that must be translated as one semantic unit."""
    result: list[TextLine] = []
    i = 0
    while i < len(lines):
        current = lines[i]
        same_page = [line for line in lines[i : i + 4] if line.page_index == current.page_index]
        texts = [_norm(line.text) for line in same_page]

        if len(texts) >= 2 and texts[0] == "Control All Blinds" and texts[1] == "(max 9 blinds)":
            result.append(_merge(same_page, 2, "Control All Blinds (max 9 blinds)"))
            i += 2
            continue

        if len(texts) >= 3 and texts[0].startswith("Knob") and texts[1].startswith("Adjust the opening") and texts[2].startswith("percentage"):
            result.append(_merge(same_page, 3, "Knob: Adjust the opening percentage"))
            i += 3
            continue

        if len(texts) >= 2 and texts[0].startswith("1-9 Channel: One channel") and texts[1].startswith("corresponds to one blind"):
            result.append(_merge(same_page, 2, "1-9 Channel: One channel corresponds to one blind."))
            i += 2
            continue

        if (
            len(texts) >= 3
            and texts[0].startswith("If there are 9 blinds")
            and texts[1].startswith("blinds 1, 3, and 5 together")
            and texts[2].startswith("Press 1, 3, and 5 in sequence")
        ):
            result.append(_merge(same_page, 3, " ".join(texts[:3])))
            i += 3
            continue

        if len(texts) >= 2 and texts[0].startswith("Only when Shangri-la Shades reach") and texts[1].startswith("can slats be adjusted"):
            result.append(_merge(same_page, 2, "Only when Shangri-la Shades reach the bottom limit can slats be adjusted."))
            i += 2
            continue

        paragraph = _merge_continuation_paragraph(same_page)
        if paragraph is not None:
            merged, consumed = paragraph
            result.append(merged)
            i += consumed
            continue

        result.append(current)
        i += 1
    return result


FIXED_TRANSLATIONS = {
    "Remote Control": "リモコン",
    "Features": "特徴",
    "Setup Guide": "設定ガイド",
    "Control All Blinds (max 9 blinds)": "全シェード制御（最大9台）",
    "Knob: Adjust the opening percentage": "つまみ：開き具合を調整",
    "Open": "開",
    "Close": "閉",
    "Stop": "停止",
    "Slight Open": "微開",
    "Slight Close": "微閉",
    "Favorite Position": "お気に入り位置",
    "1-9 Channel: One channel corresponds to one blind.": "1～9チャンネル：1チャンネルに1台のシェードを登録できます。",
    "Example Operation:": "操作例：",
    "If there are 9 blinds, and you want to open blinds 1, 3, and 5 together, the operation method is: Press 1, 3, and 5 in sequence, and then press \" Open \".": "シェードが9台あり、そのうち1・3・5を同時に開ける場合は、「1」→「3」→「5」の順に押し、その後「開」を押します。",
    "Set key P1": "キーP1を設定",
    "Set key P2": "キーP2を設定",
    "• For Shangri-la Shades": "・シャングリラシェードの場合",
    "• For Zebra Blinds": "・ゼブラブラインドの場合",
    "Only when Shangri-la Shades reach the bottom limit can slats be adjusted.": "シャングリラシェードが下限に達したときのみ、スラットを調整できます。",
    "Tilt vanes": "チルトベーン",
    "Adjust the overlap of stripes": "縞模様の重なりを調整する",
    "Congratulations! Remove the sleeping blocker, chooes the channel number (attached to the bottom rod ) to control the shade. If it cannot work, please refer to page 9-17.": "おめでとうございます！スリープブロッカーを外し、チャンネル番号（下部ロッド取付）を選択してシェードを操作してください。動作しない場合は9～17ページを参照してください。",
}


QUOTE_GAP_RE = re.compile(r'^Press\s+"[\s\u00a0]*"\s+or\s+"[\s\u00a0]*"\s*$')
CABLE_LENGTH_RE = re.compile(r'^\d+(?:\.\d+)?\s*(?:"|”|″)\s*\((\d+(?:\.\d+)?m)\)$')


def fixed_translation_for(line: TextLine) -> str | None:
    text = _norm(line.text)
    if QUOTE_GAP_RE.match(text):
        return "「□」または「□」を押す"
    cable_length = CABLE_LENGTH_RE.match(text)
    if cable_length:
        return cable_length.group(1)
    return FIXED_TRANSLATIONS.get(text)
