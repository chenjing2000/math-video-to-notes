from video_to_notes.workspace import create_workspace


def test_workspace_creation(tmp_path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")

    ws = create_workspace(
        video,
        workspace_root=tmp_path / "workspace",
        copy_source_video=False,
    )

    assert ws.root.exists()
    assert ws.visual.exists()
    assert ws.transcript.exists()
    assert ws.evidence.exists()
    assert ws.project_file.exists()
