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


def _is_continuation_line(previous: TextLine, candidate: TextLine) -> bool:
    if candidate.page_index != previous.page_index:
        return False
    if previous.role != candidate.role or previous.role not in {"body", "emphasis"}:
        return False
    if abs(previous.font_size - candidate.font_size) > 0.35:
        return False
    if abs(previous.bbox[0] - candidate.bbox[0]) > 3:
        return False
    if candidate.bbox[1] - previous.bbox[1] > previous.font_size * 1.8:
        return False
    return len(_norm(candidate.text)) >= 12


def _merge_continuation_paragraph(lines: list[TextLine]) -> tuple[TextLine, int] | None:
    first = lines[0]
    if first.role not in {"body", "emphasis"} or len(_norm(first.text)) < 24:
        return None
    group = [first]
    for candidate in lines[1:4]:
        if not _is_continuation_line(group[-1], candidate):
            break
        group.append(candidate)
    if len(group) < 2:
        return None
    text = " ".join(_norm(line.text) for line in group)
    return _merge(group, len(group), text), len(group)


def merge_known_semantic_lines(lines: list[TextLine]) -> list[TextLine]:
    """Merge repeated manual fragments that must be translated as one semantic unit."""
    result: list[TextLine] = []
    consumed: set[int] = set()
    i = 0
    while i < len(lines):
        if i in consumed:
            i += 1
            continue
        current = lines[i]
        same_page = [line for line in lines[i : i + 4] if line.page_index == current.page_index]
        texts = [_norm(line.text) for line in same_page]

        if _norm(current.text) in {"Under", "Fully"}:
            target = "Charging:" if _norm(current.text) == "Under" else "Charged:"
            merged_text = "Under Charging:" if _norm(current.text) == "Under" else "Fully Charged:"
            for lookahead_offset, candidate in enumerate(lines[i + 1 : i + 7], start=1):
                if candidate.page_index != current.page_index:
                    continue
                if i + lookahead_offset in consumed:
                    continue
                if _norm(candidate.text) != target:
                    continue
                if abs(candidate.bbox[0] - current.bbox[0]) > 5:
                    continue
                if candidate.bbox[1] <= current.bbox[1]:
                    continue
                result.append(_merge([current, candidate], 2, merged_text))
                consumed.add(i + lookahead_offset)
                break
            else:
                result.append(current)
            i += 1
            continue

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

        if (
            len(texts) >= 2
            and re.match(r'^Press\s+"[\s\u00a0]*"\s+or\s+"[\s\u00a0]*",?$', texts[0])
            and texts[1] in {"check channel.", "check group."}
        ):
            result.append(_merge(same_page, 2, f"{texts[0]} {texts[1]}"))
            i += 2
            continue

        if len(texts) >= 2 and texts[0] == "Under" and texts[1] == "Charging:":
            result.append(_merge(same_page, 2, "Under Charging:"))
            i += 2
            continue

        if len(texts) >= 2 and texts[0] == "Fully" and texts[1] == "Charged:":
            result.append(_merge(same_page, 2, "Fully Charged:"))
            i += 2
            continue

        if (
            len(texts) >= 3
            and texts[0].startswith('Press " " or " ", choose the channel')
            and texts[1] == "will flash."
            and texts[2].startswith("Choose the channel number you want to add")
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
            merged, consumed_count = paragraph
            result.append(merged)
            i += consumed_count
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
    "Orange Light": "橙ランプ",
    "Blue Light": "ブルーランプ",
    "Solid Blue": "ブルー点灯",
    "When received, the blocker prevents the motor receiving signal. To activate it, please remove the sleeping blocker. If the motor is left idle for over 6 months, please insert the sleeping blocker into the charging port to reduce battery consumption.": (
        "受信時、ブロッカーはモーターの信号受信を防ぎます。\n"
        "使用するには、スリーピングブロッカーを取り外してください。\n"
        "6か月以上使用しない場合は、バッテリー消費を抑えるため、\n"
        "ブロッカーを充電ポートに差し込んでください。"
    ),
    "Please fully charge the motor for more than 8 hours before the first use. Once fully charged, it can be used for 3-6 months depending on the frequency of use.": (
        "初回使用前に、モーターを8時間以上フル充電してください。\n"
        "フル充電後は、使用頻度に応じて3～6か月間使用できます。"
    ),
    "Low battery:": "バッテリー低下：",
    "Under Charging:": "充電中：",
    "Fully Charged:": "充電済み：",
    "Type-C Cable x1": "Type-Cケーブル ×1",
    "Extension Cable x1": "延長ケーブル ×1",
    "(Optional)": "（オプション）",
    "Flashing": "点滅",
    "• For Shangri-la Shades": "・シャングリラシェードの場合",
    "• For Zebra Blinds": "・ゼブラブラインドの場合",
    "Only when Shangri-la Shades reach the bottom limit can slats be adjusted.": "シャングリラシェードが下限に達したときのみ、スラットを調整できます。",
    "Tilt vanes": "チルトベーン",
    "Adjust the overlap of stripes": "縞模様の重なりを調整する",
    "Congratulations! Remove the sleeping blocker, chooes the channel number (attached to the bottom rod ) to control the shade. If it cannot work, please refer to page 9-17.": "おめでとうございます！スリープブロッカーを外し、チャンネル番号（下部ロッド取付）を選択してシェードを操作してください。動作しない場合は9～17ページを参照してください。",
}


QUOTE_BLANK_RE = re.compile(r'"[\s\u00a0]*"')
QUOTE_GAP_RE = re.compile(r'^Press\s+"[\s\u00a0]*"\s+or\s+"[\s\u00a0]*"\s*$')
CABLE_LENGTH_RE = re.compile(r'^\d+(?:\.\d+)?\s*(?:"|”|″|ˮ)\s*\((\d+(?:\.\d+)?m)\)$')
HOLD_FOR_TIME_RE = re.compile(r"^Hold for (\d+s)$", re.IGNORECASE)
BLIND_JOGS_COUNT_RE = re.compile(r"^Blind jogs (\d+x)$", re.IGNORECASE)


def quote_blank_key(text: str) -> str:
    return _norm(QUOTE_BLANK_RE.sub('"□"', text))


def fixed_translation_for(line: TextLine) -> str | None:
    text = _norm(line.text)
    quote_key = quote_blank_key(text)
    if QUOTE_GAP_RE.match(text):
        return "「□」または「□」を押す"
    if quote_key == 'Press "□"':
        return "「□」を押す"
    if quote_key == 'Press "□" or "□", check channel.':
        return "「□」または「□」を押す\nチャンネル確認"
    if quote_key == 'Press "□" or "□", check group.':
        return "「□」または「□」を押す\nグループ確認"
    hold_gap = re.match(r'^Hold "□" for\s+(\d+s)$', quote_key, re.IGNORECASE)
    if hold_gap:
        return f"「□」を{hold_gap.group(1)}押し続ける"
    hold_gap_exit = re.match(r'^Hold "□" for\s+(\d+s) to exit clock setting\.$', quote_key, re.IGNORECASE)
    if hold_gap_exit:
        return f"「□」を{hold_gap_exit.group(1)}押し続け、時計設定を終了します。"
    if quote_key == 'Press "□" to select other channel numbers.':
        return "「□」を押して他のチャンネル番号を選択します。"
    if quote_key == 'Please ensure your remote is in setting mode ("□" shows up). If not, please refer to page 19.':
        return "リモコンが設定モードになっていることを確認してください。\n（「□」が表示されます）\n設定モードでない場合は19ページを参照してください。"
    if quote_key == 'Please ensure your remote is not in setting mode ("□" is not shows up). If not, please refer to page 19 to exit setting mode.':
        return "リモコンが設定モードになっていないことを確認してください。\n（「□」が表示されていない状態）\n設定モードの場合は19ページを参照して終了してください。"
    if quote_key.startswith('Press "□" or "□", choose the channel number you want to cancel.'):
        return (
            "「□」または「□」を押し、\n"
            "キャンセルしたいチャンネル番号を選択します。\n"
            "「OK」を押すとキャンセルされ、この番号が点滅します。\n"
            "追加したいチャンネル番号を選択します。\n"
            "「OK」を押すと確定され、この番号は点滅しません。"
        )
    cable_length = CABLE_LENGTH_RE.match(text)
    if cable_length:
        return cable_length.group(1)
    hold_for_time = HOLD_FOR_TIME_RE.match(text)
    if hold_for_time:
        return f"{hold_for_time.group(1)}押し続ける"
    blind_jogs_count = BLIND_JOGS_COUNT_RE.match(text)
    if blind_jogs_count:
        return f"ブラインドが軽く動きます {blind_jogs_count.group(1)}"
    return FIXED_TRANSLATIONS.get(text)
