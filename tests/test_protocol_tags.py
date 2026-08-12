from codex_session_manager.gui.protocol_tags import (
    protocol_segments,
    protocol_tag_spans,
    strip_protocol_tags,
)


def test_protocol_tag_scanner_handles_quoted_multiline_and_encoded_tags() -> None:
    source = (
        'a < b\n<codex_delegation mode="a > b"\nsource="worker">\n'
        "&lt;source_thread_id note=&quot;a &gt; b&quot;&gt;source&lt;/source_thread_id&gt;\n"
        "</codex_delegation>\n<payload>tail</payload>\nx &lt; y"
    )
    spans = protocol_tag_spans(source)

    assert [span.name for span in spans] == [
        "codex_delegation",
        "source_thread_id",
        "source_thread_id",
        "codex_delegation",
        "payload",
        "payload",
    ]
    assert spans[1].encoded and spans[2].encoded
    assert strip_protocol_tags(source) == "a < b\n\nsource\n\ntail\nx &lt; y"
    assert len(protocol_segments(source)) == 2


def test_protocol_tag_scanner_handles_comments_cdata_and_incomplete_markup() -> None:
    source = "<!-- note > -->\n<![CDATA[<raw>]]>\n<open attr='>'>x</open>\n<incomplete"
    spans = protocol_tag_spans(source)

    assert [span.name for span in spans] == ["#comment", "#cdata", "open", "open"]
    assert strip_protocol_tags(source).endswith("x\n<incomplete")
