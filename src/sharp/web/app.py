"""Minimal web app for generating a panning video from a single image.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

from .sharp_pan import generate_sharp_swipe_mp4


HTML_INDEX = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>SHARP — Swipe Trajectory</title>
  </head>
  <body>
    <main>
      <h1>SHARP swipe trajectory video</h1>
      <form action=\"/pan\" method=\"post\" enctype=\"multipart/form-data\">
        <p>
          <label>Image: <input type=\"file\" name=\"image\" accept=\"image/*\" required /></label>
        </p>
        <p>
          <label>Duration (s): <input type=\"number\" name=\"duration_s\" value=\"4.0\" step=\"0.1\" min=\"0.1\" /></label>
        </p>
        <p>
          <label>FPS: <input type=\"number\" name=\"fps\" value=\"30\" step=\"1\" min=\"1\" max=\"60\" /></label>
        </p>
        <button type=\"submit\">Generate MP4</button>
      </form>
      <p>Trajectory: linear camera swipe between computed extremes.</p>
    </main>
  </body>
</html>
"""


def create_app():
    """Create the FastAPI app.

    Split into a factory function so the module can be imported even when
    FastAPI isn't installed.
    """

    try:
        from fastapi import FastAPI, File, Form, UploadFile
        from fastapi.responses import HTMLResponse, Response
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is not installed. Install web deps with: "
            "pip install -r requirements-web.txt"
        ) from exc

    app = FastAPI(title="sharp-pan")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML_INDEX

    @app.post("/pan")
    async def pan(
        image: UploadFile = File(...),
        duration_s: float = Form(4.0),
        fps: int = Form(30),
    ):
        image_bytes = await image.read()
        video_bytes = generate_sharp_swipe_mp4(image_bytes, duration_s=duration_s, fps=fps)

        headers = {"Content-Disposition": "attachment; filename=pan.mp4"}
        return Response(content=video_bytes, media_type="video/mp4", headers=headers)

    return app


# Convenience for `uvicorn sharp.web.app:app`
app = create_app()
