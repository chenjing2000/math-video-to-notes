from video_to_notes.reconstruction.provider import parse_json_response


def test_parse_json_response_accepts_json_fence():
    result = parse_json_response('```json\n{"a": 1}\n```')
    assert result == {"a": 1}


def test_parse_json_response_raises_model_response_error_for_invalid_json():
    import pytest

    from video_to_notes.errors import ModelResponseError

    with pytest.raises(ModelResponseError):
        parse_json_response("not-json")


def test_file_provider_exhaustion_is_transport_error(tmp_path):
    import pytest

    from video_to_notes.errors import TransportError
    from video_to_notes.reconstruction.provider import FileProvider

    provider = FileProvider([])
    with pytest.raises(TransportError):
        provider.generate_json(system="", user="")
