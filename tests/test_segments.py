from PIL import Image, ImageDraw

from video_to_notes.visual.segments import build_segments


def test_progressive_board_classification(tmp_path):
    paths = []
    for i in range(4):
        path = tmp_path / f"{i}.jpg"
        im = Image.new("RGB", (400, 240), "white")
        d = ImageDraw.Draw(im)
        for j in range(i):
            d.line(
                (20, 30 + 35*j, 180, 30 + 35*j),
                fill="black",
                width=4,
            )
        im.save(path)
        paths.append(path)

    scan = [
        {
            "id": f"scan_{i}",
            "time": float(i * 10),
            "path": str(paths[i]),
            "source": "scan",
        }
        for i in range(4)
    ]

    coverage = [
        {
            "id": "cov_0",
            "time": 0.0,
            "path": str(paths[0]),
            "source": "coverage",
        }
    ]

    segments = build_segments(
        duration=40.0,
        scan_frames=scan,
        coverage_frames=coverage,
        scene_events=[],
        transition_cfg={
            "duplicate_change_ratio": 0.001,
            "duplicate_phash_distance": 1,
            "incremental_change_ratio": 0.30,
            "incremental_phash_distance": 30,
            "pixel_difference_threshold": 20,
        },
        classification_cfg={
            "progressive_min_incremental_events": 2,
            "dynamic_events_per_minute": 20.0,
            "dynamic_min_mean_change_ratio": 0.40,
        },
        output_path=tmp_path / "segments.json",
    )

    assert any(
        s["visual_type"] == "progressive_board"
        for s in segments
    )
