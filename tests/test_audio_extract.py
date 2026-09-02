from pathlib import Path

import pytest

from video_to_notes.transcription.audio import extract_audio


def test_extract_audio_missing_ffmpeg(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")

    with pytest.raises(Exception):
        extract_audio(
            video_path=video,
            ffmpeg=tmp_path / "missing_ffmpeg",
            output_path=tmp_path / "audio.wav",
        )
