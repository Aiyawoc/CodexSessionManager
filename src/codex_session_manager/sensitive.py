"""Local-only, redacted sensitive-content heuristics for conversation review."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from itertools import chain

from codex_session_manager.models import ThreadSnapshot


class SensitiveSeverity(StrEnum):
    MEDIUM = "medium"
    HIGH = "high"


class SensitiveScanCancelled(Exception):
    """Stop a batch scan without returning incomplete findings."""


@dataclass(frozen=True, slots=True)
class SensitiveFinding:
    category: str
    severity: SensitiveSeverity
    count: int


@dataclass(frozen=True, slots=True)
class SensitiveSpan:
    """Source offsets for one finding without retaining the matched value."""

    start: int
    end: int
    category: str
    severity: SensitiveSeverity


@dataclass(frozen=True, slots=True)
class SensitiveScanResult:
    findings: tuple[SensitiveFinding, ...] = ()
    spans: tuple[SensitiveSpan, ...] = ()

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)

    @property
    def maximum_severity(self) -> SensitiveSeverity | None:
        if any(item.severity is SensitiveSeverity.HIGH for item in self.findings):
            return SensitiveSeverity.HIGH
        return SensitiveSeverity.MEDIUM if self.findings else None

    @property
    def summary(self) -> str:
        return "、".join(f"{item.category}×{item.count}" for item in self.findings)


@dataclass(frozen=True, slots=True)
class _PatternRule:
    category: str
    severity: SensitiveSeverity
    pattern: re.Pattern[str]


_RULES = (
    _PatternRule(
        "私钥",
        SensitiveSeverity.HIGH,
        re.compile(
            r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----[\s\S]*?"
            r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----|"
            r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----"
        ),
    ),
    _PatternRule(
        "云服务/API 密钥",
        SensitiveSeverity.HIGH,
        re.compile(
            r"(?<![A-Za-z0-9])(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
            r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}|sk_live_[A-Za-z0-9]{16,}|"
            r"xox[baprs]-[A-Za-z0-9-]{16,}|AIza[0-9A-Za-z_-]{30,})(?![A-Za-z0-9])"
        ),
    ),
    _PatternRule(
        "JWT",
        SensitiveSeverity.HIGH,
        re.compile(
            r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
            r"[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
        ),
    ),
    _PatternRule(
        "口令/令牌赋值",
        SensitiveSeverity.HIGH,
        re.compile(
            r"(?i)\b(?:password|passwd|passphrase|secret|api[_-]?key|access[_-]?token)"
            r"\b\s*[:=]\s*['\"]?(?!\$\{|<|\[?redacted\]?|example\b|placeholder\b)"
            r"[^\s,'\";]{8,}"
        ),
    ),
    _PatternRule(
        "电子邮箱",
        SensitiveSeverity.MEDIUM,
        re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I),
    ),
    _PatternRule(
        "中国大陆手机号",
        SensitiveSeverity.MEDIUM,
        re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ),
)
_CHINA_ID = re.compile(r"(?<!\d)(\d{17}[0-9Xx])(?!\d)")
_CARD_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")
_ANY_DIGIT = re.compile(r"\d")
_API_KEY_PREFIXES = (
    "AKIA",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "sk-",
    "sk_live_",
    "xoxb-",
    "xoxa-",
    "xoxp-",
    "xoxr-",
    "xoxs-",
    "AIza",
)
_ASSIGNMENT_MARKERS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "apikey",
    "api_key",
    "api-key",
    "accesstoken",
    "access_token",
    "access-token",
)
_BATCH_CHUNK_CHARS = 256 * 1024
_BATCH_CHUNK_OVERLAP = 4096


def scan_sensitive_text(text: str) -> SensitiveScanResult:
    """Return redacted categories and source offsets, never matched values."""

    counts, spans = _scan_sensitive_text(text, include_spans=True)
    return SensitiveScanResult(_findings(counts), tuple(spans))


def _scan_sensitive_text(
    text: str,
    *,
    include_spans: bool,
    match_start_range: tuple[int, int] | None = None,
) -> tuple[dict[tuple[str, SensitiveSeverity], int], list[SensitiveSpan]]:
    """Scan one bounded string, optionally retaining exact source offsets."""

    counts: dict[tuple[str, SensitiveSeverity], int] = {}
    spans: list[SensitiveSpan] = []

    def belongs(match: re.Match[str]) -> bool:
        if match_start_range is None:
            return True
        start, end = match_start_range
        return start <= match.start() < end

    for rule in _RULES:
        if not _rule_may_match(rule, text):
            continue
        count = 0
        for match in rule.pattern.finditer(text):
            if not belongs(match):
                continue
            count += 1
            if include_spans:
                spans.append(
                    SensitiveSpan(match.start(), match.end(), rule.category, rule.severity)
                )
        if count:
            counts[(rule.category, rule.severity)] = count

    has_digit = len(text) >= 11 and _ANY_DIGIT.search(text) is not None
    identity_category = "中国居民身份证号"
    identity_severity = SensitiveSeverity.HIGH
    identity_count = 0
    for match in _CHINA_ID.finditer(text) if has_digit else ():
        if not belongs(match) or not _valid_china_id(match.group(1)):
            continue
        identity_count += 1
        if include_spans:
            spans.append(
                SensitiveSpan(
                    match.start(),
                    match.end(),
                    identity_category,
                    identity_severity,
                )
            )
    if identity_count:
        counts[(identity_category, identity_severity)] = identity_count

    card_category = "支付卡号"
    card_severity = SensitiveSeverity.HIGH
    card_count = 0
    for match in _CARD_NUMBER.finditer(text) if has_digit else ():
        if not belongs(match):
            continue
        digits = re.sub(r"\D", "", match.group(0))
        if 16 <= len(digits) <= 19 and len(set(digits)) > 1 and _passes_luhn(digits):
            card_count += 1
            if include_spans:
                spans.append(
                    SensitiveSpan(match.start(), match.end(), card_category, card_severity)
                )
    if card_count:
        counts[(card_category, card_severity)] = card_count

    spans.sort(key=lambda span: (span.start, span.end, span.category, span.severity))
    return counts, spans


def _rule_may_match(rule: _PatternRule, text: str) -> bool:
    """Cheap literal gates avoid running every regex over ordinary prose."""

    if rule.category == "私钥":
        return "PRIVATE KEY" in text
    if rule.category == "云服务/API 密钥":
        return any(prefix in text for prefix in _API_KEY_PREFIXES)
    if rule.category == "JWT":
        first_dot = text.find(".")
        return first_dot >= 0 and text.find(".", first_dot + 1) >= 0
    if rule.category == "口令/令牌赋值":
        lowered = text.lower()
        return any(marker in lowered for marker in _ASSIGNMENT_MARKERS)
    if rule.category == "电子邮箱":
        return "@" in text
    if rule.category == "中国大陆手机号":
        return "1" in text
    return True


def _findings(
    counts: dict[tuple[str, SensitiveSeverity], int],
) -> tuple[SensitiveFinding, ...]:
    return tuple(
        SensitiveFinding(category, severity, count)
        for (category, severity), count in sorted(
            counts.items(), key=lambda value: (value[0][1] != SensitiveSeverity.HIGH, value[0][0])
        )
    )


def _merge_counts(
    destination: dict[tuple[str, SensitiveSeverity], int],
    source: dict[tuple[str, SensitiveSeverity], int],
) -> None:
    for key, count in source.items():
        destination[key] = destination.get(key, 0) + count


def _scan_fragment_counts(
    text: str,
    *,
    lookahead: str,
    cancelled: Callable[[], bool] | None,
) -> dict[tuple[str, SensitiveSeverity], int]:
    """Scan large fields in bounded calls so no regex monopolizes the GIL."""

    counts: dict[tuple[str, SensitiveSeverity], int] = {}
    text_length = len(text)
    for core_start in range(0, max(1, text_length), _BATCH_CHUNK_CHARS):
        if cancelled is not None and cancelled():
            raise SensitiveScanCancelled
        core_end = min(text_length, core_start + _BATCH_CHUNK_CHARS)
        extended_start = max(0, core_start - _BATCH_CHUNK_OVERLAP)
        extended_end = min(text_length, core_end + _BATCH_CHUNK_OVERLAP)
        chunk = text[extended_start:extended_end]
        if extended_end == text_length and lookahead:
            chunk += lookahead[:_BATCH_CHUNK_OVERLAP]
        chunk_counts, _spans = _scan_sensitive_text(
            chunk,
            include_spans=False,
            match_start_range=(
                core_start - extended_start,
                core_end - extended_start,
            ),
        )
        _merge_counts(counts, chunk_counts)
    return counts


def _batched_fragments(
    fragments: Iterable[str],
    *,
    cancelled: Callable[[], bool] | None,
) -> Iterator[str]:
    """Join only small adjacent fields, keeping the working set bounded."""

    parts: list[str] = []
    character_count = 0
    for fragment in fragments:
        if cancelled is not None and cancelled():
            raise SensitiveScanCancelled
        if not fragment:
            continue
        if len(fragment) > _BATCH_CHUNK_CHARS:
            if parts:
                yield "\n".join(parts)
                parts = []
                character_count = 0
            yield fragment
            continue
        separator_size = 1 if parts else 0
        if parts and character_count + separator_size + len(fragment) > _BATCH_CHUNK_CHARS:
            yield "\n".join(parts)
            parts = [fragment]
            character_count = len(fragment)
            continue
        parts.append(fragment)
        character_count += separator_size + len(fragment)
    if parts:
        yield "\n".join(parts)


def scan_sensitive_snapshot(
    snapshot: ThreadSnapshot,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> SensitiveScanResult:
    """Scan model-visible fields from one normalized snapshot locally."""

    fragments = (
        fragment
        for fragment in chain(
            (snapshot.title, snapshot.preview),
            (item.text for turn in snapshot.turns for item in turn.items),
        )
        if fragment
    )
    batches = iter(_batched_fragments(fragments, cancelled=cancelled))
    counts: dict[tuple[str, SensitiveSeverity], int] = {}
    try:
        current = next(batches)
    except StopIteration:
        return SensitiveScanResult()
    for following in batches:
        _merge_counts(
            counts,
            _scan_fragment_counts(
                current,
                lookahead=f"\n{following[: _BATCH_CHUNK_OVERLAP - 1]}",
                cancelled=cancelled,
            ),
        )
        current = following
    _merge_counts(
        counts,
        _scan_fragment_counts(current, lookahead="", cancelled=cancelled),
    )
    # Batch filtering needs only redacted categories/counts. Source offsets are
    # useful solely while rendering one visible context and are not retained in
    # the long-lived task-list cache.
    return SensitiveScanResult(findings=_findings(counts))


def _passes_luhn(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _valid_china_id(value: str) -> bool:
    if len(value) != 18 or not value[:17].isdigit():
        return False
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    checks = "10X98765432"
    expected = checks[
        sum(int(char) * weight for char, weight in zip(value[:17], weights, strict=True)) % 11
    ]
    return value[-1].upper() == expected
