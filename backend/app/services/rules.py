from __future__ import annotations

import re
from collections import defaultdict

from app.models import GateResult, GateSeverity, TranslatedLine


ASCII_WORD_RE = re.compile(r"[A-Za-z]{3,}")


class RuleEngine:
    def validate(self, lines: list[TranslatedLine]) -> list[GateResult]:
        results: list[GateResult] = []
        results.extend(self._no_missing_translation(lines))
        results.extend(self._no_text_scaling(lines))
        results.extend(self._same_role_font_consistency(lines))
        results.extend(self._protected_tokens_preserved(lines))
        results.extend(self._no_english_residue(lines))
        return results

    def _no_missing_translation(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            src = item.source
            if src.localizable and not item.translated_text.strip():
                failures.append(
                    GateResult(
                        code="missing_translation",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=src.page_index,
                        line_index=src.line_index,
                        message="Localizable source line has empty translation.",
                    )
                )
        return failures

    def _no_text_scaling(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            src = item.source
            if abs(item.output_font_size - src.font_size) > 0.01:
                failures.append(
                    GateResult(
                        code="text_scaling_forbidden",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=src.page_index,
                        line_index=src.line_index,
                        message="Output font size differs from source role size.",
                        details={"source_size": src.font_size, "output_size": item.output_font_size},
                    )
                )
        return failures

    def _same_role_font_consistency(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        grouped: dict[tuple[int, str], list[TranslatedLine]] = defaultdict(list)
        for item in lines:
            if item.source.localizable:
                grouped[(item.source.page_index, item.source.role)].append(item)
        for (page_index, role), items in grouped.items():
            sizes = {round(item.output_font_size, 2) for item in items}
            if len(sizes) > 1 and role in {"body", "figure_label", "section_title", "title"}:
                failures.append(
                    GateResult(
                        code="same_role_font_mismatch",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=page_index,
                        message=f"Same role has mixed font sizes: {role}.",
                        details={"sizes": sorted(sizes), "role": role},
                    )
                )
        return failures

    def _protected_tokens_preserved(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        for item in lines:
            for token in item.source.protected_tokens:
                normalized = token.strip("\"'")
                if normalized and normalized not in item.translated_text and token not in item.translated_text:
                    failures.append(
                        GateResult(
                            code="protected_token_missing",
                            severity=GateSeverity.hard_fail,
                            passed=False,
                            page_index=item.source.page_index,
                            line_index=item.source.line_index,
                            message="Protected token is missing from translated line.",
                            details={"token": token, "translation": item.translated_text},
                        )
                    )
        return failures

    def _no_english_residue(self, lines: list[TranslatedLine]) -> list[GateResult]:
        failures: list[GateResult] = []
        allowed = {
            "Alexa",
            "Apple",
            "Google",
            "Matter",
            "Shades",
            "Shangri",
            "Yoolax",
            "Zebra",
        }
        for item in lines:
            if not item.source.localizable:
                continue
            words = set(ASCII_WORD_RE.findall(item.translated_text))
            residue = sorted(word for word in words if word not in allowed)
            if residue:
                failures.append(
                    GateResult(
                        code="english_residue",
                        severity=GateSeverity.hard_fail,
                        passed=False,
                        page_index=item.source.page_index,
                        line_index=item.source.line_index,
                        message="Translated line still contains likely untranslated English.",
                        details={"words": residue, "translation": item.translated_text},
                    )
                )
        return failures
