# SHARP (fork)

This is a fork of Apple’s `ml-sharp` repository.

What this fork adds:

- Apple Silicon (MPS) fallback for the included demo video generation.
- A trivial web app to upload a single image and generate a left-to-right “swipe” video.

Upstream project page: https://apple.github.io/ml-sharp/

![Basic Web UI](data/web.png)

![Sample Video output (saved as GIF)](data/sample.gif)

## Getting started

Install dependencies:

```bash
pip install -r requirements.txt -r requirements-web.txt
```

To test the installation, run

```bash
sharp --help
```

## Using the CLI

To run prediction (upstream behavior):

```bash
sharp predict -i /path/to/input/images -o /path/to/output/gaussians
```

The results will be 3D gaussian splats (3DGS) in the output folder. The 3DGS `.ply` files are compatible to various public 3DGS renderers. We follow the OpenCV coordinate convention (x right, y down, z forward). The 3DGS scene center is roughly at (0, 0, +z). When dealing with 3rdparty renderers, please scale and rotate to re-center the scene accordingly.

### Rendering trajectories (CUDA GPU only)

Additionally you can render videos with a camera trajectory.

- The CLI trajectory renderer (`sharp predict --render` / `sharp render`) uses gsplat and is CUDA-only.
- The web demo can still generate a swipe video on macOS/MPS (or CPU) via the fallback depth-parallax path.

```bash
sharp predict -i /path/to/input/images -o /path/to/output/gaussians --render

# Or from the intermediate gaussians:
sharp render -i /path/to/output/gaussians -o /path/to/output/renderings
```

## Web demo (SHARP swipe trajectory)

This repository also includes a tiny web app that accepts a single image and generates a left-to-right swipe trajectory video using SHARP.

- On CUDA: predicts 3D Gaussians and renders a true camera trajectory via gsplat.
- On macOS/MPS (or CPU): falls back to a depth-based parallax warp driven by SHARP's monodepth sub-network.

Run the server:

```bash
sharp web
```

Then open `http://127.0.0.1:8000` in your browser.

## Acknowledgements

Our codebase is built using multiple opensource contributions, please see [ACKNOWLEDGEMENTS](ACKNOWLEDGEMENTS) for more details.

## License

Please check out the repository [LICENSE](LICENSE) before using the provided code and
[LICENSE_MODEL](LICENSE_MODEL) for the released models.
