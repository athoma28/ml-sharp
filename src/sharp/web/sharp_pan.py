"""Model-based horizontal panning using SHARP.

This uses the same pipeline as `sharp predict --render`, but tailored for a simple
"swipe" camera trajectory and returning MP4 bytes.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path
from typing import Any

import imageio.v2 as iio
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageOps

from sharp.models import PredictorParams, RGBGaussianPredictor, create_predictor
from sharp.utils import camera
from sharp.utils.gaussians import Gaussians3D, SceneMetaData, unproject_gaussians
from sharp.utils.io import convert_focallength, extract_exif

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"

_STATE_DICT: dict[str, Any] | None = None
_PREDICTOR_BY_DEVICE: dict[str, RGBGaussianPredictor] = {}


def _load_upload_rgb_and_fpx(image_bytes: bytes) -> tuple[np.ndarray, float]:
    with Image.open(io.BytesIO(image_bytes)) as img_pil:
        img_pil = ImageOps.exif_transpose(img_pil)
        img_pil = img_pil.convert("RGB")

        img_exif: dict[str, object]
        try:
            img_exif = extract_exif(img_pil)
        except Exception:
            img_exif = {}

        # Mirror the CLI logic: try 35mm-equivalent first, fall back to focal length.
        f_35mm = img_exif.get("FocalLengthIn35mmFilm", img_exif.get("FocalLenIn35mmFilm", None))
        if f_35mm is None or (isinstance(f_35mm, (int, float)) and f_35mm < 1):
            f_35mm = img_exif.get("FocalLength", None)

        if not isinstance(f_35mm, (int, float)):
            f_35mm = 30.0
        if f_35mm < 10.0:
            # Crude approximation (same as CLI).
            f_35mm *= 8.4

        image_rgb = np.asarray(img_pil, dtype=np.uint8)
        height, width = image_rgb.shape[:2]
        f_px = float(convert_focallength(width, height, float(f_35mm)))
        return image_rgb, f_px


def _ensure_even_hw_uint8_rgb(image_rgb: np.ndarray) -> np.ndarray:
    if image_rgb.ndim != 3 or image_rgb.shape[2] != 3:
        raise ValueError(f"Expected HxWx3 RGB uint8 image, got {image_rgb.shape!r}.")
    if image_rgb.dtype != np.uint8:
        image_rgb = image_rgb.astype(np.uint8, copy=False)

    height, width = image_rgb.shape[:2]
    height_even = height - (height % 2)
    width_even = width - (width % 2)
    return image_rgb[:height_even, :width_even, :]


def _pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _get_state_dict() -> dict[str, Any]:
    global _STATE_DICT
    if _STATE_DICT is None:
        LOGGER.info("Downloading SHARP checkpoint: %s", DEFAULT_MODEL_URL)
        _STATE_DICT = torch.hub.load_state_dict_from_url(DEFAULT_MODEL_URL, progress=True)
    return _STATE_DICT


def _get_predictor(device: torch.device) -> RGBGaussianPredictor:
    key = str(device)
    predictor = _PREDICTOR_BY_DEVICE.get(key)
    if predictor is None:
        predictor = create_predictor(PredictorParams())
        predictor.load_state_dict(_get_state_dict())
        predictor.eval().to(device)
        _PREDICTOR_BY_DEVICE[key] = predictor
    return predictor


def _resize_max_side(image_rgb: np.ndarray, max_side: int) -> np.ndarray:
    if max_side <= 0:
        return image_rgb
    height, width = image_rgb.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image_rgb
    scale = max_side / float(longest)
    new_w = max(2, int(round(width * scale)))
    new_h = max(2, int(round(height * scale)))
    # PIL resize for speed & quality.
    img = Image.fromarray(image_rgb)
    # Pillow 10+: Image.Resampling.BICUBIC; keep backward compat.
    resample_bicubic = getattr(
        getattr(Image, "Resampling", None),
        "BICUBIC",
        getattr(Image, "BICUBIC", 3),
    )
    img = img.resize((new_w, new_h), resample=resample_bicubic)
    return np.asarray(img, dtype=np.uint8)


@torch.no_grad()
def _predict_gaussians(image_rgb: np.ndarray, f_px: float, device: torch.device) -> Gaussians3D:
    # This mirrors `sharp.cli.predict.predict_image`.
    internal_shape = (1536, 1536)

    image_pt = torch.from_numpy(image_rgb.copy()).float().to(device).permute(2, 0, 1) / 255.0
    _, height, width = image_pt.shape
    disparity_factor = torch.tensor([f_px / width]).float().to(device)

    image_resized_pt = F.interpolate(
        image_pt[None],
        size=(internal_shape[1], internal_shape[0]),
        mode="bilinear",
        align_corners=True,
    )

    predictor = _get_predictor(device)

    LOGGER.info("Running SHARP inference")
    gaussians_ndc = predictor(image_resized_pt, disparity_factor)

    intrinsics = (
        torch.tensor(
            [
                [f_px, 0, width / 2, 0],
                [0, f_px, height / 2, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        )
        .float()
        .to(device)
    )
    intrinsics_resized = intrinsics.clone()
    intrinsics_resized[0] *= internal_shape[0] / width
    intrinsics_resized[1] *= internal_shape[1] / height

    gaussians = unproject_gaussians(
        gaussians_ndc, torch.eye(4).to(device), intrinsics_resized, internal_shape
    )
    return gaussians


@torch.no_grad()
def _predict_depth_for_warp(
    image_rgb: np.ndarray,
    f_px: float,
    device: torch.device,
    *,
    internal_shape: tuple[int, int] = (1536, 1536),
) -> tuple[torch.Tensor, torch.Tensor]:
    """Predict a metric-ish depth map for simple parallax warping.

    Returns:
        image_pt: (1, 3, H, W) float32 in [0,1] at original resolution on `device`
        depth: (1, 1, H, W) float32 metric depth on `device`
    """
    predictor = _get_predictor(device)

    image_pt = torch.from_numpy(image_rgb.copy()).float().to(device).permute(2, 0, 1) / 255.0
    _, height, width = image_pt.shape

    # Match the predictor's conversion from monodepth disparity to metric depth.
    disparity_factor = torch.tensor([f_px / width], device=device, dtype=torch.float32)

    image_resized_pt = F.interpolate(
        image_pt[None],
        size=(internal_shape[1], internal_shape[0]),
        mode="bilinear",
        align_corners=True,
    )

    # Run monodepth only.
    monodepth_output = predictor.monodepth_model(image_resized_pt)
    disparity = monodepth_output.disparity
    disparity_factor = disparity_factor[:, None, None, None]
    depth_resized = disparity_factor / disparity.clamp(min=1e-4, max=1e4)

    depth = F.interpolate(depth_resized, size=(height, width), mode="bilinear", align_corners=True)
    return image_pt[None], depth


@torch.no_grad()
def _render_depth_parallax_swipe_mp4(
    image_rgb: np.ndarray,
    f_px: float,
    device: torch.device,
    *,
    duration_s: float,
    fps: int,
    max_disparity: float,
) -> bytes:
    """MPS/CPU fallback: depth-based parallax warp.

    This is not full 3D Gaussian splatting, but it still uses the SHARP model
    (monodepth sub-network) to compute a depth field, then warps the image along
    a left↔right trajectory.
    """
    # Keep memory bounded on MPS/CPU.
    image_rgb = _resize_max_side(image_rgb, max_side=1024)
    image_rgb = _ensure_even_hw_uint8_rgb(image_rgb)

    image_pt, depth = _predict_depth_for_warp(image_rgb, f_px, device)
    _, _, height, width = image_pt.shape

    # Compute a normalized inverse-depth map (near -> +1, far -> -1).
    inv_depth = 1.0 / depth.clamp(min=1e-3)

    # Use cheap quantiles from a downsampled map (computed on CPU for portability).
    inv_small = F.interpolate(inv_depth, size=(128, 128), mode="bilinear", align_corners=True)
    inv_cpu = inv_small.detach().float().cpu().flatten()
    q05 = torch.quantile(inv_cpu, 0.05).item()
    q50 = torch.quantile(inv_cpu, 0.50).item()
    q95 = torch.quantile(inv_cpu, 0.95).item()
    scale = max(1e-6, (q95 - q05))

    inv_norm = (inv_depth - q50) / scale
    inv_norm = inv_norm.clamp(min=-1.0, max=1.0)

    # Pixel shift map; max_disparity ~ fraction of width.
    max_shift_px = float(max_disparity) * float(width)
    shift_px = inv_norm * max_shift_px

    # Base sampling grid.
    ys = torch.linspace(-1.0, 1.0, height, device=device)
    xs = torch.linspace(-1.0, 1.0, width, device=device)
    grid_y, grid_x = torch.meshgrid(ys, xs, indexing="ij")
    base_grid = torch.stack([grid_x, grid_y], dim=-1)[None]  # (1, H, W, 2)

    frame_count = max(2, int(round(duration_s * fps)))
    ts = torch.linspace(-1.0, 1.0, frame_count)

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
            for t in ts:
                # Normalize pixel shift into [-1,1] space for grid_sample.
                x_shift = (2.0 * float(t) * shift_px) / max(1.0, float(width - 1))
                grid = base_grid.clone()
                # Keep sampling inside bounds for MPS compatibility.
                grid[..., 0] = (grid[..., 0] + x_shift[:, 0, :, :]).clamp(-1.0, 1.0)
                warped = F.grid_sample(
                    image_pt,
                    grid,
                    mode="bilinear",
                    padding_mode="zeros",
                    align_corners=True,
                )
                frame = (warped[0].permute(1, 2, 0) * 255.0).clamp(0, 255).to(torch.uint8)
                frame_np = frame.detach().cpu().numpy()
                frame_np = _ensure_even_hw_uint8_rgb(frame_np)
                writer.append_data(frame_np)
        finally:
            writer.close()

        return output_path.read_bytes()
    finally:
        output_path.unlink(missing_ok=True)


def generate_sharp_swipe_mp4(
    image_bytes: bytes,
    *,
    duration_s: float = 4.0,
    fps: int = 30,
    max_disparity: float = 0.08,
) -> bytes:
    """Generate a model-based swipe (horizontal pan) MP4.

    Requires CUDA, because gsplat rendering is CUDA-only in this repo.
    """
    if duration_s <= 0:
        raise ValueError("duration_s must be > 0")
    if fps <= 0:
        raise ValueError("fps must be > 0")

    image_rgb, f_px = _load_upload_rgb_and_fpx(image_bytes)
    image_rgb = _ensure_even_hw_uint8_rgb(image_rgb)
    height, width = image_rgb.shape[:2]

    device = _pick_device()

    # Full 3DGS rendering path (CUDA).
    if device.type == "cuda":
        # Lazy import so macOS/MPS environments can still start the web server.
        from sharp.utils.gsplat import GSplatRenderer

        gaussians = _predict_gaussians(image_rgb, f_px, device)

        metadata = SceneMetaData(f_px, (width, height), "linearRGB")

        frame_count = max(2, int(round(duration_s * fps)))
        params = camera.TrajectoryParams(type="swipe", num_steps=frame_count, num_repeats=1)
        params.max_disparity = float(max_disparity)

        intrinsics = torch.tensor(
            [
                [f_px, 0, (width - 1) / 2.0, 0],
                [0, f_px, (height - 1) / 2.0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            device=device,
            dtype=torch.float32,
        )

        camera_model = camera.create_camera_model(
            gaussians, intrinsics, resolution_px=metadata.resolution_px
        )
        trajectory = camera.create_eye_trajectory(
            gaussians, params, resolution_px=metadata.resolution_px, f_px=f_px
        )

        renderer = GSplatRenderer(color_space=metadata.color_space)

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
                for eye_position in trajectory:
                    camera_info = camera_model.compute(eye_position.to(device))
                    rendering_output = renderer(
                        gaussians.to(device),
                        extrinsics=camera_info.extrinsics[None].to(device),
                        intrinsics=camera_info.intrinsics[None].to(device),
                        image_width=camera_info.width,
                        image_height=camera_info.height,
                    )
                    color = (rendering_output.color[0].permute(1, 2, 0) * 255.0).to(
                        dtype=torch.uint8
                    )
                    frame = color.detach().cpu().numpy()
                    frame = _ensure_even_hw_uint8_rgb(frame)
                    writer.append_data(frame)
            finally:
                writer.close()

            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)

    # Fallback: use monodepth to produce depth-based parallax warp (MPS/CPU).
    LOGGER.warning("CUDA not available; using depth-parallax fallback on %s", device.type)
    return _render_depth_parallax_swipe_mp4(
        image_rgb,
        f_px,
        device,
        duration_s=duration_s,
        fps=fps,
        max_disparity=max_disparity,
    )
