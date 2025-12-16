"""Generate simple panning videos from a single image.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import imageio.v2 as iio
import numpy as np


def _ensure_even_hw(image: np.ndarray) -> np.ndarray:
    # Many H.264 encoders require even dimensions for yuv420p.
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError(f"Expected HxWxC image with >=3 channels, got {image.shape!r}.")

    height, width = image.shape[0], image.shape[1]
    height_even = height - (height % 2)
    width_even = width - (width % 2)
    return image[:height_even, :width_even, :3]


def generate_horizontal_pan_mp4(
    image_rgb: np.ndarray,
    *,
    crop_fraction: float = 0.8,
    duration_s: float = 4.0,
    fps: int = 30,
) -> bytes:
    """Generate a left-to-right horizontal panning MP4.

    The motion is a linear trajectory between the leftmost crop (x=0) and the
    rightmost crop (x=max_x).

    Args:
        image_rgb: Input image as uint8 RGB array (H, W, 3).
        crop_fraction: Fraction of width to keep in the crop window in (0, 1].
        duration_s: Output video duration in seconds.
        fps: Frames per second.

    Returns:
        MP4 file bytes.
    """
    if not (0.0 < crop_fraction <= 1.0):
        raise ValueError("crop_fraction must be in (0, 1].")
    if duration_s <= 0.0:
        raise ValueError("duration_s must be > 0.")
    if fps <= 0:
        raise ValueError("fps must be > 0.")

    image_rgb = _ensure_even_hw(image_rgb)
    height, width = image_rgb.shape[0], image_rgb.shape[1]

    crop_width = int(round(width * crop_fraction))
    crop_width = max(2, min(width, crop_width))
    crop_width -= crop_width % 2
    crop_width = max(2, crop_width)

    frame_count = max(2, int(round(duration_s * fps)))
    max_x = max(0, width - crop_width)

    if max_x == 0:
        xs = np.zeros((frame_count,), dtype=np.int32)
    else:
        xs = np.linspace(0, max_x, num=frame_count)
        xs = np.clip(np.round(xs).astype(np.int32), 0, max_x)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        writer = iio.get_writer(
            output_path,
            fps=fps,
            codec="libx264",
            pixelformat="yuv420p",
            quality=8,
        )
        try:
            for x in xs:
                frame = image_rgb[:, x : x + crop_width, :]
                writer.append_data(frame)
        finally:
            writer.close()

        return output_path.read_bytes()
    finally:
        output_path.unlink(missing_ok=True)
