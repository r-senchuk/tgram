from tgram.interfaces.web import _linkify, _text


def test_linkify_single_citation():
    text = "As stated in [msg:12345], the service is active."
    expected = "As stated in [↗ msg:12345](#msg-12345), the service is active."
    assert _linkify(text) == expected


def test_linkify_multiple_citations_in_single_tag():
    text = "Refer to [msg:101, msg:102, msg:103] for details."
    expected = "Refer to [↗ msg:101](#msg-101) [↗ msg:102](#msg-102) [↗ msg:103](#msg-103) for details."
    assert _linkify(text) == expected


def test_linkify_separate_citations():
    text = "See [msg:1] and also [msg:2]."
    expected = "See [↗ msg:1](#msg-1) and also [↗ msg:2](#msg-2)."
    assert _linkify(text) == expected


def test_linkify_no_citations():
    text = "No citations here, just [normal bracketed] text."
    assert _linkify(text) == text


def test_text_helper_gradio_blocks():
    # String passes through
    assert _text("hello") == "hello"
    assert _text(None) == ""

    # Gradio 6 block format list
    blocks = [{"text": "Hello "}, {"text": "world!"}]
    assert _text(blocks) == "Hello world!"

    # Mixed list
    mixed = [{"text": "Part 1: "}, "Part 2"]
    assert _text(mixed) == "Part 1: Part 2"
