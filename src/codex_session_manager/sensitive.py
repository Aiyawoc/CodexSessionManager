"""Local-only, redacted sensitive-content heuristics for conversation review."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from codex_session_manager.models import ThreadSnapshot


class SensitiveSeverity(StrEnum):
    MEDIUM = "medium"
    HIGH = "high"


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


def scan_sensitive_text(text: str) -> SensitiveScanResult:
    """Return redacted categories and source offsets, never matched values."""

    counts: dict[tuple[str, SensitiveSeverity], int] = {}
    spans: list[SensitiveSpan] = []
    for rule in _RULES:
        matches = tuple(rule.pattern.finditer(text))
        if not matches:
            continue
        counts[(rule.category, rule.severity)] = len(matches)
        spans.extend(
            SensitiveSpan(match.start(), match.end(), rule.category, rule.severity)
            for match in matches
        )

    identity_matches = tuple(
        match for match in _CHINA_ID.finditer(text) if _valid_china_id(match.group(1))
    )
    if identity_matches:
        category = "中国居民身份证号"
        severity = SensitiveSeverity.HIGH
        counts[(category, severity)] = len(identity_matches)
        spans.extend(
            SensitiveSpan(match.start(), match.end(), category, severity)
            for match in identity_matches
        )

    card_matches: list[re.Match[str]] = []
    for match in _CARD_NUMBER.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 16 <= len(digits) <= 19 and len(set(digits)) > 1 and _passes_luhn(digits):
            card_matches.append(match)
    if card_matches:
        category = "支付卡号"
        severity = SensitiveSeverity.HIGH
        counts[(category, severity)] = len(card_matches)
        spans.extend(
            SensitiveSpan(match.start(), match.end(), category, severity) for match in card_matches
        )

    findings = tuple(
        SensitiveFinding(category, severity, count)
        for (category, severity), count in sorted(
            counts.items(), key=lambda value: (value[0][1] != SensitiveSeverity.HIGH, value[0][0])
        )
    )
    ordered_spans = tuple(
        sorted(spans, key=lambda span: (span.start, span.end, span.category, span.severity))
    )
    return SensitiveScanResult(findings, ordered_spans)


def scan_sensitive_snapshot(snapshot: ThreadSnapshot) -> SensitiveScanResult:
    """Scan model-visible fields from one normalized snapshot locally."""

    fragments = [snapshot.title, snapshot.preview]
    fragments.extend(item.text for turn in snapshot.turns for item in turn.items if item.text)
    result = scan_sensitive_text("\n".join(fragment for fragment in fragments if fragment))
    # Batch filtering needs only redacted categories/counts. Source offsets are
    # useful solely while rendering one visible context and are not retained in
    # the long-lived task-list cache.
    return SensitiveScanResult(findings=result.findings)


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
