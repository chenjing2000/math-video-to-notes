from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops


@lru_cache(maxsize=4)
def _dct_matrix(n: int) -> np.ndarray:
    x = np.arange(n, dtype=np.float64)
    k = x[:, None]
    mat = np.cos((math.pi / n) * (x + 0.5) * k)
    mat[0, :] *= 1.0 / math.sqrt(n)
    mat[1:, :] *= math.sqrt(2.0 / n)
    return mat


def phash(path: Path, hash_size: int = 8, highfreq_factor: int = 4) -> int:
    size = hash_size * highfreq_factor
    with Image.open(path) as im:
        gray = im.convert("L").resize((size, size), Image.Resampling.LANCZOS)
        arr = np.asarray(gray, dtype=np.float64)

    c = _dct_matrix(size)
    dct = c @ arr @ c.T
    low = dct[:hash_size, :hash_size]
    values = low.flatten()
    median = np.median(values[1:]) if len(values) > 1 else values[0]
    bits = values > median

    value = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
    return value


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def changed_pixel_ratio(
    a_path: Path,
    b_path: Path,
    *,
    threshold: int = 24,
    compare_width: int = 480,
) -> float:
    with Image.open(a_path) as a_im, Image.open(b_path) as b_im:
        a = a_im.convert("L")
        b = b_im.convert("L")

        def resize(im: Image.Image) -> Image.Image:
            if im.width <= 0 or im.height <= 0:
                return im
            height = max(1, round(im.height * compare_width / im.width))
            return im.resize((compare_width, height), Image.Resampling.BILINEAR)

        a = resize(a)
        b = resize(b)

        h = min(a.height, b.height)
        w = min(a.width, b.width)
        a = a.crop((0, 0, w, h))
        b = b.crop((0, 0, w, h))

        diff = ImageChops.difference(a, b)
        hist = diff.histogram()
        total = w * h
        changed = sum(hist[threshold + 1 :])
        return changed / total if total else 0.0


def compare_images(
    a_path: Path,
    b_path: Path,
    *,
    pixel_threshold: int = 24,
) -> dict[str, float | int]:
    a_hash = phash(a_path)
    b_hash = phash(b_path)
    return {
        "phash_distance": hamming_distance(a_hash, b_hash),
        "change_ratio": changed_pixel_ratio(
            a_path,
            b_path,
            threshold=pixel_threshold,
        ),
    }
