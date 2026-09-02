from video_to_notes.visual.probe import _parse_rate


def test_parse_rate():
    assert _parse_rate("30/1") == 30.0
    assert _parse_rate("30000/1001") > 29.9
    assert _parse_rate("0/0") is None
