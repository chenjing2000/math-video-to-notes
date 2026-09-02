from video_to_notes.transcription.formatting import (
    _srt_timestamp,
    write_transcript_srt,
    write_transcript_txt,
)


def test_srt_timestamp():
    assert _srt_timestamp(0.0) == "00:00:00,000"
    assert _srt_timestamp(61.234) == "00:01:01,234"
    assert _srt_timestamp(3661.005) == "01:01:01,005"


def test_write_srt_and_txt(tmp_path):
    segments = [
        {
            "id": "tr_000000",
            "start": 0.5,
            "end": 2.0,
            "text": "第一句。",
        },
        {
            "id": "tr_000001",
            "start": 2.1,
            "end": 4.3,
            "text": "第二句。",
        },
    ]

    srt = tmp_path / "a.srt"
    txt = tmp_path / "a.txt"

    write_transcript_srt(srt, segments)
    write_transcript_txt(txt, segments)

    srt_text = srt.read_text(encoding="utf-8")
    txt_text = txt.read_text(encoding="utf-8")

    assert "00:00:00,500 --> 00:00:02,000" in srt_text
    assert "第一句。" in srt_text
    assert txt_text == "第一句。\n第二句。"
