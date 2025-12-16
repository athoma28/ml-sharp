"""Web demo command.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

from __future__ import annotations

import click


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
def web_cli(host: str, port: int) -> None:
    """Run a tiny web app to generate a panning MP4 from a single image."""
    try:
        import uvicorn
    except ImportError as exc:
        raise click.ClickException(
            "uvicorn is not installed. Install web deps with: "
            "pip install -r requirements-web.txt"
        ) from exc

    uvicorn.run("sharp.web.app:app", host=host, port=port)
