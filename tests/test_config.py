from video_to_notes.config import load_config


def test_default_config():
    cfg = load_config()
    assert cfg["project"]["workspace_root"] == "workspace"
    assert cfg["stages"]["visual"]["enabled"] is True
