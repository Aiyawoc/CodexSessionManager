"""Parse Codex protocol markup without treating ordinary comparisons as tags.

The App Server can surface both literal XML-like markup and HTML-entity encoded
markup.  A regular expression cannot safely find the closing ``>`` when an
attribute contains that character, and the encoded form needs a different
terminator.  This module keeps the parsing small, deterministic, and independent
from Qt so it can be regression-tested directly.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_TAG_BODY = re.compile(
    r"^\s*(?P<closing>/)?\s*(?P<name>[A-Za-z_][\w:.-]*)(?:\s|/|$)",
    re.DOTALL,
)
_ENCODED_OPENERS = ("&lt;", "&#60;", "&#x3c;")
_ENCODED_CLOSERS = ("&gt;", "&#62;", "&#x3e;")
_ENCODED_QUOTES = ("&quot;", "&#34;", "&#x22;", "&apos;", "&#39;", "&#x27;")


@dataclass(frozen=True, slots=True)
class ProtocolTagSpan:
    """One literal or entity-encoded protocol tag in source coordinates."""

    start: int
    end: int
    name: str
    closing: bool = False
    encoded: bool = False


def protocol_tag_spans(text: str) -> tuple[ProtocolTagSpan, ...]:
    """Return XML-like tag spans while preserving source offsets.

    The scanner accepts namespaced/hyphenated names, multiline attributes,
    quoted ``>`` characters, comments, CDATA, and encoded ``&lt;tag&gt;`` forms.
    Expressions such as ``a < b`` and ``x &lt; y`` are deliberately ignored.
    """

    spans: list[ProtocolTagSpan] = []
    lowered = text.casefold()
    cursor = 0
    while cursor < len(text):
        literal_at = text.find("<", cursor)
        encoded_at, encoded_opener = _next_encoded_opener(lowered, cursor)
        candidates = [value for value in (literal_at, encoded_at) if value >= 0]
        if not candidates:
            break
        start = min(candidates)
        encoded = start == encoded_at and (literal_at < 0 or encoded_at <= literal_at)
        if encoded:
            assert encoded_opener is not None
            parsed = _scan_encoded(text, lowered, start, encoded_opener)
        else:
            parsed = _scan_literal(text, start)
        if parsed is None:
            cursor = start + 1
            continue
        end, body, special_name = parsed
        if special_name is not None:
            spans.append(ProtocolTagSpan(start, end, special_name, encoded=encoded))
            cursor = end
            continue
        match = _TAG_BODY.match(html.unescape(body))
        if match is None:
            cursor = start + 1
            continue
        spans.append(
            ProtocolTagSpan(
                start=start,
                end=end,
                name=match.group("name"),
                closing=bool(match.group("closing")),
                encoded=encoded,
            )
        )
        cursor = end
    return tuple(spans)


def strip_protocol_tags(text: str) -> str:
    """Remove recognized protocol markup without changing ordinary angle text."""

    spans = protocol_tag_spans(text)
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for span in spans:
        parts.append(text[cursor : span.start])
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts)


def protocol_segments(text: str) -> tuple[tuple[int, int], ...]:
    """Split source after every closed ``codex_delegation`` block."""

    if not text:
        return ()
    ends = [
        span.end
        for span in protocol_tag_spans(text)
        if span.closing and span.name.casefold() == "codex_delegation"
    ]
    segments: list[tuple[int, int]] = []
    start = 0
    for end in ends:
        if end > start:
            segments.append((start, end))
            start = end
    if start < len(text):
        segments.append((start, len(text)))
    return tuple(segments)


def _next_encoded_opener(lowered: str, start: int) -> tuple[int, str | None]:
    matches = [
        (index, opener)
        for opener in _ENCODED_OPENERS
        if (index := lowered.find(opener, start)) >= 0
    ]
    return min(matches, default=(-1, None), key=lambda value: value[0])


def _scan_encoded(
    text: str, lowered: str, start: int, opener: str
) -> tuple[int, str, str | None] | None:
    body_start = start + len(opener)
    quote: str | None = None
    cursor = body_start
    while cursor < len(text):
        if quote is not None:
            if lowered.startswith(quote, cursor):
                cursor += len(quote)
                quote = None
                continue
            if quote in {'"', "'"} and text[cursor] == quote:
                quote = None
            cursor += 1
            continue
        if text[cursor] in {'"', "'"}:
            quote = text[cursor]
            cursor += 1
            continue
        encoded_quote = next(
            (candidate for candidate in _ENCODED_QUOTES if lowered.startswith(candidate, cursor)),
            None,
        )
        if encoded_quote is not None:
            quote = encoded_quote
            cursor += len(encoded_quote)
            continue
        closer = next(
            (candidate for candidate in _ENCODED_CLOSERS if lowered.startswith(candidate, cursor)),
            None,
        )
        if closer is not None:
            return cursor + len(closer), text[body_start:cursor], None
        cursor += 1
    return None


def _scan_literal(text: str, start: int) -> tuple[int, str, str | None] | None:
    if text.startswith("<!--", start):
        end = text.find("-->", start + 4)
        return None if end < 0 else (end + 3, text[start + 1 : end + 2], "#comment")
    if text.startswith("<![CDATA[", start):
        end = text.find("]]>", start + 9)
        return None if end < 0 else (end + 3, text[start + 1 : end + 2], "#cdata")

    quote: str | None = None
    cursor = start + 1
    while cursor < len(text):
        char = text[cursor]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == ">":
            body = text[start + 1 : cursor]
            if body.startswith("?"):
                return cursor + 1, body, "#processing"
            if body.startswith("!"):
                return cursor + 1, body, "#declaration"
            return cursor + 1, body, None
        elif char == "<":
            return None
        cursor += 1
    return None
