from video_to_notes.reconstruction.provider import parse_json_response


def test_parse_json_response_accepts_json_fence():
    result = parse_json_response('```json\n{"a": 1}\n```')
    assert result == {"a": 1}
