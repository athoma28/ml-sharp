"""Model-based motion rendering using SHARP.

This uses the same pipeline as `sharp predict --render`, but tailored for a simple
single-image camera trajectory and returning MP4 bytes.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path
from typing import Any, Callable, Literal

import imageio.v2 as iio
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageOps

from sharp.models import PredictorParams, RGBGaussianPredictor, create_predictor
from sharp.utils import camera
from sharp.utils.gaussians import Gaussians3D, SceneMetaData, save_ply, unproject_gaussians
from sharp.utils.io import convert_focallength, extract_exif

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL_URL = "https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"

_STATE_DICT: dict[str, Any] | None = None
_PREDICTOR_BY_DEVICE: dict[str, RGBGaussianPredictor] = {}

TrajectoryType = Literal["swipe", "shake", "rotate", "rotate_forward"]
ProgressCallback = Callable[[str, float, str | None], None]


def _safe_progress(progress_cb: ProgressCallback | None, stage: str, progress: float, detail: str) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(stage, float(progress), detail)
    except Exception:
        return


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


def _resize_max_side_with_scale(image_rgb: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    """Resize while returning the uniform scale factor applied.

    Returns (resized_image_rgb, scale). `scale` is 1.0 when no resize occurs.
    """
    if max_side <= 0:
        return image_rgb, 1.0
    height, width = image_rgb.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image_rgb, 1.0
    scale = max_side / float(longest)
    new_w = max(2, int(round(width * scale)))
    new_h = max(2, int(round(height * scale)))

    img = Image.fromarray(image_rgb)
    resample_bicubic = getattr(
        getattr(Image, "Resampling", None),
        "BICUBIC",
        getattr(Image, "BICUBIC", 3),
    )
    img = img.resize((new_w, new_h), resample=resample_bicubic)
    return np.asarray(img, dtype=np.uint8), float(scale)


@torch.no_grad()
def _predict_gaussians(image_rgb: np.ndarray, f_px: float, device: torch.device) -> Gaussians3D:
    # This mirrors `sharp.cli.predict.predict_image`.
    internal_shape = (1536, 1536)

    image_pt = torch.from_numpy(image_rgb.copy()).float().to(device).permute(2, 0, 1) / 255.0
    _, height, width = image_pt.shape

    disparity_factor = torch.tensor([f_px / width], device=device, dtype=torch.float32)

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


def _gaussians_to_ply_bytes(
    gaussians: Gaussians3D, f_px: float, image_shape: tuple[int, int]
) -> bytes:
    """Serialize Gaussians to a .ply file and return the bytes."""
    with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        save_ply(gaussians, f_px, image_shape, path)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


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


def _trajectory_xyzoom(
    trajectory_type: TrajectoryType,
    frame_count: int,
    num_repeats: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (tx, ty, zoom01) arrays for each frame.

    tx/ty are in roughly [-1, 1] and represent a normalized lateral motion
    direction. zoom01 is in [0,1] and can be used to modulate a per-layer zoom.
    """
    frame_count = int(max(2, frame_count))
    num_repeats = int(max(1, num_repeats))
    ps = np.linspace(0.0, 1.0, frame_count, dtype=np.float32)

    if trajectory_type == "swipe":
        tx = np.linspace(-0.6, 0.6, frame_count, dtype=np.float32)
        ty = np.zeros_like(tx)
        zoom01 = np.zeros_like(tx)
        return tx, ty, zoom01

    if trajectory_type == "shake":
        tx = np.zeros((frame_count,), dtype=np.float32)
        ty = np.zeros((frame_count,), dtype=np.float32)
        zoom01 = np.zeros((frame_count,), dtype=np.float32)
        mid = frame_count // 2
        p0 = np.linspace(0.0, float(num_repeats), max(1, mid), dtype=np.float32)
        p1 = np.linspace(0.0, float(num_repeats), frame_count - mid, dtype=np.float32)
        if mid > 0:
            tx[:mid] = np.sin(2.0 * np.pi * p0)
        if frame_count - mid > 0:
            ty[mid:] = np.sin(2.0 * np.pi * p1)
        return tx, ty, zoom01

    if trajectory_type == "rotate":
        ang = (2.0 * np.pi) * (float(num_repeats) * ps)
        tx = np.sin(ang).astype(np.float32)
        ty = np.cos(ang).astype(np.float32)
        zoom01 = np.zeros_like(tx)
        return tx, ty, zoom01

    if trajectory_type == "rotate_forward":
        ang = (2.0 * np.pi) * (float(num_repeats) * ps)
        tx = np.sin(ang).astype(np.float32)
        ty = np.zeros_like(tx)
        zoom01 = ((1.0 - np.cos(ang)) / 2.0).astype(np.float32)
        return tx, ty, zoom01

    raise ValueError(f"Unsupported trajectory_type={trajectory_type!r}")


@torch.no_grad()
def _render_depth_parallax_trajectory_mp4(
    image_rgb: np.ndarray,
    f_px: float,
    device: torch.device,
    *,
    duration_s: float,
    fps: int,
    max_disparity: float,
    wobble_scale: float,
    trajectory_type: TrajectoryType,
    max_zoom: float,
    num_repeats: int,
    max_side: int,
    progress_cb: ProgressCallback | None,
) -> bytes:
    """MPS/CPU fallback: depth-based parallax warp.

    This is not full 3D Gaussian splatting, but it still uses the SHARP model
    (monodepth sub-network) to compute a depth field, then warps the image along
    a lightweight camera-motion trajectory (e.g. swipe, shake, rotate).
    """
    # Keep memory bounded on MPS/CPU and keep intrinsics consistent.
    resized, scale = _resize_max_side_with_scale(image_rgb, max_side=int(max_side))
    f_px = float(f_px) * float(scale)
    resized_w = int(resized.shape[1])
    image_rgb = _ensure_even_hw_uint8_rgb(resized)
    f_px = float(f_px) * (float(image_rgb.shape[1]) / max(1.0, float(resized_w)))

    _safe_progress(progress_cb, "inference", 0.0, "Predicting depth…")
    image_pt, depth = _predict_depth_for_warp(image_rgb, f_px, device)
    _safe_progress(progress_cb, "inference", 1.0, "Depth ready.")
    _, _, height, width = image_pt.shape

    _safe_progress(progress_cb, "trajectory", 0.15, "Building depth planes…")
    # Normalize inverse-depth to [0,1] so far shifts ~0 and near shifts ~1.
    inv = (1.0 / depth.clamp(min=1e-3))[0, 0]
    inv_small = F.interpolate(inv[None, None], size=(128, 128), mode="bilinear", align_corners=True)
    inv_cpu = inv_small.detach().float().cpu().flatten()
    q05 = float(torch.quantile(inv_cpu, 0.05).item())
    q95 = float(torch.quantile(inv_cpu, 0.95).item())
    scale_inv = max(1e-6, (q95 - q05))
    inv01 = ((inv - q05) / scale_inv).clamp(0.0, 1.0)

    # Edge-aware stabilization of inverse-depth.
    # Minor monodepth noise around strong RGB edges can cause "zippering" in the
    # plane assignment, which shows up as thin cracks/ghosting during parallax.
    lum = (0.299 * image_pt[0, 0] + 0.587 * image_pt[0, 1] + 0.114 * image_pt[0, 2]).to(
        torch.float32
    )
    sobel_x = torch.tensor(
        [[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]],
        device=device,
        dtype=torch.float32,
    )[None, None]
    sobel_y = torch.tensor(
        [[-1.0, -2.0, -1.0], [0.0, 0.0, 0.0], [1.0, 2.0, 1.0]],
        device=device,
        dtype=torch.float32,
    )[None, None]
    gx = F.conv2d(lum[None, None], sobel_x, padding=1)
    gy = F.conv2d(lum[None, None], sobel_y, padding=1)
    edge = (gx.abs() + gy.abs())[0, 0]
    edge_small = F.interpolate(edge[None, None], size=(128, 128), mode="bilinear", align_corners=True)
    edge_cpu = edge_small.detach().float().cpu().flatten()
    e90 = float(torch.quantile(edge_cpu, 0.90).item())
    edge01 = (edge / max(1e-6, e90)).clamp(0.0, 1.0)
    # Smooth more in flat regions, less across edges.
    # Aggressive settings help suppress residual cracking/"black trails".
    for _ in range(4):
        inv01_blur = F.avg_pool2d(inv01[None, None], kernel_size=9, stride=1, padding=4)[0, 0]
        alpha = 0.60 * (1.0 - edge01).pow(2.0)
        inv01 = inv01 * (1.0 - alpha) + inv01_blur * alpha

    # Build depth planes (MPI) and composite far->near.
    # Use a *two-plane* soft assignment in inverse-depth space. This reduces
    # edge tearing vs. hard one-hot binning while keeping the layer model.
    num_planes = 32
    pos = inv01 * float(num_planes - 1)
    idx0 = torch.floor(pos).to(torch.int64).clamp(0, num_planes - 1)
    idx1 = (idx0 + 1).clamp(0, num_planes - 1)
    frac = (pos - idx0.to(pos.dtype)).clamp(0.0, 1.0)
    w0 = (1.0 - frac).to(dtype=torch.float32)
    w1 = frac.to(dtype=torch.float32)

    one_hot0 = F.one_hot(idx0, num_classes=num_planes).permute(2, 0, 1).to(dtype=torch.float32)
    one_hot1 = F.one_hot(idx1, num_classes=num_planes).permute(2, 0, 1).to(dtype=torch.float32)
    plane_a = (one_hot0 * w0[None, :, :] + one_hot1 * w1[None, :, :])[:, None, :, :]  # (L,1,H,W)
    plane_rgb = image_pt[0][None].to(torch.float32) * plane_a  # premultiplied

    frame_count = max(2, int(round(duration_s * fps)))
    tx_np, ty_np, zoom01_np = _trajectory_xyzoom(trajectory_type, frame_count, num_repeats)
    tx = torch.from_numpy(tx_np).to(device=device, dtype=torch.float32)
    ty = torch.from_numpy(ty_np).to(device=device, dtype=torch.float32)
    zoom01 = torch.from_numpy(zoom01_np).to(device=device, dtype=torch.float32)
    _safe_progress(progress_cb, "trajectory", 1.0, "Trajectory ready.")

    # Pixel shift amplitude.
    max_shift_px = float(max_disparity) * float(width)

    # Add a subtle vertical oscillation (cosine wave) over the duration.
    # The amplitude is intentionally small; the UI exposes an additional scale.
    wobble_scale = float(max(0.0, wobble_scale))
    y_amp_px = wobble_scale * max(0.75, 0.04 * max_shift_px)

    # Avoid tearing at both ends by rendering into a replicate-padded canvas and
    # cropping back. This avoids relying on grid_sample padding_mode="border",
    # which isn't consistently supported on MPS.
    max_abs_tx = float(tx.abs().max().item()) if frame_count > 0 else 0.6
    max_abs_ty = float(ty.abs().max().item()) if frame_count > 0 else 0.0
    pad_x = int(np.ceil(max_abs_tx * max_shift_px)) + 2
    pad_y = int(np.ceil(max_abs_ty * max_shift_px + y_amp_px)) + 2
    height_p = height + 2 * pad_y
    width_p = width + 2 * pad_x
    plane_a_p = F.pad(plane_a, (pad_x, pad_x, pad_y, pad_y), mode="replicate")
    plane_rgb_p = F.pad(plane_rgb, (pad_x, pad_x, pad_y, pad_y), mode="replicate")

    # Base sampling grid (padded canvas).
    ys = torch.linspace(-1.0, 1.0, height_p, device=device)
    xs = torch.linspace(-1.0, 1.0, width_p, device=device)
    grid_y, grid_x = torch.meshgrid(ys, xs, indexing="ij")
    base_grid = torch.stack([grid_x, grid_y], dim=-1)[None]  # (1,Hp,Wp,2)

    # Diffusion kernel to fill cracks/holes without using the original frame.
    kernel = torch.ones((1, 1, 5, 5), device=device, dtype=torch.float32)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        output_path = Path(tmp.name)

    try:
        _safe_progress(progress_cb, "render", 0.0, "Rendering frames…")
        writer = iio.get_writer(
            output_path,
            fps=fps,
            codec="libx264",
            pixelformat="yuv420p",
            quality=8,
            macro_block_size=1,
        )
        try:
            for frame_idx in range(frame_count):
                progress = 0.0 if frame_count <= 1 else float(frame_idx) / float(frame_count - 1)
                _safe_progress(
                    progress_cb,
                    "render",
                    float(progress),
                    f"Frame {frame_idx + 1}/{frame_count}",
                )

                t_x = tx[frame_idx]
                t_y = ty[frame_idx]
                zoom_t = float(max(0.0, max_zoom)) * float(zoom01[frame_idx].item())

                wobble_px = 0.0
                if trajectory_type == "swipe" and y_amp_px > 0.0:
                    wobble_px = float(y_amp_px) * float(-np.cos(np.pi * progress))

                y_shift = (2.0 * float(wobble_px)) / max(1.0, float(height_p - 1))

                out_rgb = torch.zeros((1, 3, height_p, width_p), device=device, dtype=torch.float32)
                out_a = torch.zeros((1, 1, height_p, width_p), device=device, dtype=torch.float32)

                for li in range(num_planes):
                    center01 = float(li) / max(1.0, float(num_planes - 1))
                    shift_x_px = center01 * float(t_x) * max_shift_px
                    shift_y_px = center01 * float(t_y) * max_shift_px
                    x_shift = (2.0 * shift_x_px) / max(1.0, float(width_p - 1))
                    y_shift_layer = (2.0 * shift_y_px) / max(1.0, float(height_p - 1))

                    zoom_layer = float(zoom_t) * float(center01)
                    scale = max(0.35, 1.0 - zoom_layer)
                    grid = base_grid * scale
                    grid[..., 0] = grid[..., 0] + x_shift
                    grid[..., 1] = grid[..., 1] + y_shift + y_shift_layer

                    # Soft alpha only to unpremultiply (avoid dark fringes).
                    a_soft = F.grid_sample(
                        plane_a_p[li : li + 1],
                        grid,
                        mode="bilinear",
                        padding_mode="zeros",
                        align_corners=True,
                    )
                    rgb_premul = F.grid_sample(
                        plane_rgb_p[li : li + 1],
                        grid,
                        mode="bilinear",
                        padding_mode="zeros",
                        align_corners=True,
                    )

                    # Premultiplied-alpha compositing. Avoiding per-layer unpremultiply
                    # removes division noise that shows up as jagged "rips" at strong
                    # depth discontinuities.
                    a = a_soft.clamp(0.0, 1.0)
                    rgb = rgb_premul

                    out_rgb = out_rgb + (1.0 - out_a) * rgb
                    out_a = out_a + (1.0 - out_a) * a

                # Crop back to original frame size.
                out_rgb = out_rgb[:, :, pad_y : pad_y + height, pad_x : pad_x + width]
                out_a = out_a[:, :, pad_y : pad_y + height, pad_x : pad_x + width]

                # Diffuse-fill tiny holes in the final unpremultiplied image.
                img = out_rgb / out_a.clamp(min=1e-4)
                # Treat low-alpha pixels as holes to avoid amplifying tiny alpha via
                # unpremultiply (which can look like thin black cracks / black trails).
                m = (out_a > 0.20).to(torch.float32)

                # De-pepper: sometimes you get isolated dark speckles near soft edges
                # where alpha is non-zero but unreliable. Detect those and treat them
                # as holes so the diffusion fill overwrites them.
                lum = (0.299 * img[:, 0:1] + 0.587 * img[:, 1:2] + 0.114 * img[:, 2:3]).clamp(0.0, 1.0)
                lum_mean = F.avg_pool2d(lum, kernel_size=3, stride=1, padding=1)
                speckle = (
                    (m > 0.5)
                    & (out_a < 0.90)
                    & (lum < (0.25 * lum_mean))
                    & (lum_mean > 0.06)
                )
                m = torch.where(speckle, torch.zeros_like(m), m)

                for _ in range(6):
                    if float(m.mean().item()) > 0.999:
                        break
                    sum_rgb = F.conv2d(img * m, kernel.expand(3, 1, 5, 5), padding=2, groups=3)
                    cnt = F.conv2d(m, kernel, padding=2)
                    fill = sum_rgb / cnt.clamp(min=1.0)
                    fill_mask = (cnt > 0.0).to(dtype=torch.float32)
                    img = torch.where(m.bool(), img, fill)
                    m = torch.where(m.bool(), m, fill_mask)

                frame = (img[0].permute(1, 2, 0) * 255.0).clamp(0, 255).to(torch.uint8)
                frame_np = frame.detach().cpu().numpy()
                frame_np = _ensure_even_hw_uint8_rgb(frame_np)
                writer.append_data(frame_np)
        finally:
            writer.close()

        _safe_progress(progress_cb, "render", 1.0, "Frames rendered.")
        return output_path.read_bytes()
    finally:
        output_path.unlink(missing_ok=True)


def generate_sharp_swipe_mp4(
    image_bytes: bytes,
    *,
    duration_s: float = 4.0,
    fps: int = 30,
    max_disparity: float = 0.08,
    motion_scale: float = 0.20,
    wobble_scale: float = 0.25,
    trajectory_type: TrajectoryType | str = "swipe",
    max_zoom: float = 0.15,
    num_repeats: int = 1,
    max_side: int = 1536,
    render_max_side: int = 1536,
    progress_cb: ProgressCallback | None = None,
    return_meta: bool = False,
    return_ply: bool = False,
    force_depth_fallback: bool = False,
    render_video: bool = True,
) -> bytes | tuple[bytes, dict[str, Any]] | tuple[bytes, dict[str, Any], bytes | None]:
    """Generate a model-based motion MP4.

    - CUDA: predicts 3D Gaussians and renders a true camera trajectory (gsplat).
    - MPS/CPU: depth-based parallax warp driven by SHARP monodepth.

    Set `return_ply=True` to also export the predicted Gaussians as `.ply` bytes.
    Set `render_video=False` to only export the PLY (no MP4).
    Set `force_depth_fallback=True` to always use the depth-based renderer for video,
    even on CUDA.
    """
    if duration_s <= 0:
        raise ValueError("duration_s must be > 0")
    if fps <= 0:
        raise ValueError("fps must be > 0")
    if num_repeats <= 0:
        raise ValueError("num_repeats must be > 0")
    if max_side <= 0:
        raise ValueError("max_side must be > 0")
    if render_max_side < 0:
        raise ValueError("render_max_side must be >= 0")
    if max_zoom < 0:
        raise ValueError("max_zoom must be >= 0")

    # Scale the overall swipe motion (centered) while keeping the rendering logic intact.
    # 1.0 = full motion, 0.1 = 10% of the motion, etc.
    if motion_scale <= 0:
        raise ValueError("motion_scale must be > 0")
    max_disparity = float(max_disparity) * float(motion_scale)

    if wobble_scale < 0:
        raise ValueError("wobble_scale must be >= 0")

    trajectory_t = str(trajectory_type)
    allowed = {"swipe", "shake", "rotate", "rotate_forward"}
    if trajectory_t not in allowed:
        raise ValueError(f"trajectory_type must be one of {sorted(allowed)} (got {trajectory_t!r})")

    _safe_progress(progress_cb, "load", 0.0, "Loading image…")
    image_rgb, f_px = _load_upload_rgb_and_fpx(image_bytes)
    image_rgb = _ensure_even_hw_uint8_rgb(image_rgb)
    height, width = image_rgb.shape[:2]
    _safe_progress(progress_cb, "load", 1.0, f"Image ready ({width}×{height}).")

    if render_max_side and render_max_side > 0:
        longest = max(image_rgb.shape[:2])
        if longest > int(render_max_side):
            resized, scale = _resize_max_side_with_scale(image_rgb, max_side=int(render_max_side))
            image_rgb = _ensure_even_hw_uint8_rgb(resized)
            f_px = float(f_px) * float(scale)
            height, width = image_rgb.shape[:2]
            _safe_progress(progress_cb, "load", 1.0, f"Image resized to {width}×{height}.")

    device = _pick_device()
    meta: dict[str, Any] = {"device": str(device)}
    ply_bytes: bytes | None = None
    need_video = bool(render_video)
    need_ply = bool(return_ply)

    use_depth_only = force_depth_fallback or device.type != "cuda"
    renderer_cls = None
    if not use_depth_only:
        try:
            from sharp.utils.gsplat import GSplatRenderer  # type: ignore
        except Exception as exc:
            LOGGER.warning(
                "CUDA detected but gsplat renderer unavailable; falling back to depth-parallax. (%s)",
                exc,
            )
            use_depth_only = True
        else:
            renderer_cls = GSplatRenderer

    # Full 3DGS rendering path (CUDA + gsplat available + not forced fallback).
    if not use_depth_only and renderer_cls is not None:
        _safe_progress(progress_cb, "inference", 0.0, "Running SHARP inference…")
        gaussians = _predict_gaussians(image_rgb, f_px, device)
        _safe_progress(progress_cb, "inference", 1.0, "Gaussians ready.")

        metadata = SceneMetaData(f_px, (width, height), "linearRGB")

        frame_count = max(2, int(round(duration_s * fps)))
        params = camera.TrajectoryParams(
            type=trajectory_t, num_steps=frame_count, num_repeats=int(num_repeats)
        )
        params.max_disparity = float(max_disparity)
        params.max_zoom = float(max_zoom)

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
        _safe_progress(progress_cb, "trajectory", 0.0, "Creating trajectory…")
        trajectory = camera.create_eye_trajectory(
            gaussians, params, resolution_px=metadata.resolution_px, f_px=f_px
        )
        if trajectory_t == "swipe" and wobble_scale > 0:
            max_offset_xyz_m = camera.compute_max_offset(
                gaussians,
                params,
                resolution_px=metadata.resolution_px,
                f_px=f_px,
            )
            _, offset_y_m, _ = max_offset_xyz_m
            y_amp_m = float(wobble_scale) * 0.04 * float(offset_y_m)
            ps = np.linspace(0.0, 1.0, len(trajectory), dtype=np.float32)
            trajectory = [
                eye + torch.tensor([0.0, float(y_amp_m * (-np.cos(np.pi * float(p)))), 0.0])
                for (eye, p) in zip(trajectory, ps, strict=True)
            ]
        _safe_progress(progress_cb, "trajectory", 1.0, "Trajectory ready.")

        video_bytes: bytes | None = None
        if need_video:
            renderer = renderer_cls(color_space=metadata.color_space)
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                output_path = Path(tmp.name)
            try:
                _safe_progress(progress_cb, "render", 0.0, "Rendering frames…")
                writer = iio.get_writer(
                    output_path,
                    fps=fps,
                    codec="libx264",
                    pixelformat="yuv420p",
                    quality=8,
                )
                try:
                    for frame_idx, eye_position in enumerate(trajectory):
                        progress = (
                            1.0
                            if len(trajectory) <= 1
                            else float(frame_idx) / float(len(trajectory) - 1)
                        )
                        _safe_progress(
                            progress_cb,
                            "render",
                            progress,
                            f"Frame {frame_idx + 1}/{len(trajectory)}",
                        )
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

                _safe_progress(progress_cb, "render", 1.0, "Frames rendered.")
                video_bytes = output_path.read_bytes()
            finally:
                output_path.unlink(missing_ok=True)
        else:
            _safe_progress(progress_cb, "render", 1.0, "Skipped (PLY only).")

        if need_ply:
            _safe_progress(progress_cb, "ply", 0.0, "Exporting .ply…")
            ply_bytes = _gaussians_to_ply_bytes(gaussians, f_px, (height, width))
            size_mb = len(ply_bytes) / 1_000_000.0
            _safe_progress(progress_cb, "ply", 1.0, f"{size_mb:.1f} MB")

        _safe_progress(progress_cb, "finalize", 1.0, "Done.")
        if need_ply:
            return video_bytes or b"", meta, ply_bytes
        if return_meta:
            return video_bytes or b"", meta
        return video_bytes or b""

    # Fallback: use monodepth to produce depth-based parallax warp (MPS/CPU or forced).
    if device.type == "cuda":
        LOGGER.warning("Using depth-parallax fallback on CUDA (gsplat unavailable or forced).")
    else:
        LOGGER.warning("CUDA not available; using depth-parallax fallback on %s", device.type)

    video_bytes = b""
    if need_video:
        video_bytes = _render_depth_parallax_trajectory_mp4(
            image_rgb,
            f_px,
            device,
            duration_s=duration_s,
            fps=fps,
            max_disparity=max_disparity,
            wobble_scale=wobble_scale,
            trajectory_type=trajectory_t,  # type: ignore[arg-type]
            max_zoom=max_zoom,
            num_repeats=num_repeats,
            max_side=max_side,
            progress_cb=progress_cb,
        )
    else:
        _safe_progress(progress_cb, "render", 1.0, "Skipped (PLY only).")

    if need_ply:
        _safe_progress(progress_cb, "ply", 0.0, "Running SHARP inference for PLY…")
        gaussians = _predict_gaussians(image_rgb, f_px, device)
        ply_bytes = _gaussians_to_ply_bytes(gaussians, f_px, (height, width))
        size_mb = len(ply_bytes) / 1_000_000.0
        _safe_progress(progress_cb, "ply", 1.0, f"{size_mb:.1f} MB")
    _safe_progress(progress_cb, "finalize", 1.0, "Done.")
    if need_ply:
        return video_bytes, meta, ply_bytes
    if return_meta:
        return video_bytes, meta
    return video_bytes
