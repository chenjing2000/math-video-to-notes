import sys
from types import SimpleNamespace

from video_to_notes.transcription.whisper_engine import transcribe_audio


class FakeSegment:
    def __init__(self):
        self.start = 1.25
        self.end = 3.50
        self.text = " 测试文本 "
        self.avg_logprob = -0.2
        self.no_speech_prob = 0.01
        self.words = None


class FakeModel:
    def __init__(self, model_name, device, compute_type):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, path, **kwargs):
        info = SimpleNamespace(
            language="zh",
            language_probability=0.99,
            duration=4.0,
            duration_after_vad=3.8,
        )
        return iter([FakeSegment()]), info


def test_transcribe_audio_with_fake_model(tmp_path, monkeypatch):
    fake_module = SimpleNamespace(WhisperModel=FakeModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    # Force an explicit CPU config so the test does not depend on ctranslate2.
    result = transcribe_audio(
        tmp_path / "audio.wav",
        config={
            "model": "large-v3",
            "language": "zh",
            "device": "cpu",
            "compute_type": "int8",
            "beam_size": 5,
            "vad_filter": True,
            "word_timestamps": False,
            "condition_on_previous_text": True,
        },
    )

    assert result.metadata["language_detected"] == "zh"
    assert result.segments[0]["start"] == 1.25
    assert result.segments[0]["end"] == 3.5
    assert result.segments[0]["text"] == "测试文本"
