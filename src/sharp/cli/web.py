"""Web demo command.

For licensing see accompanying LICENSE file.
Copyright (C) 2025 Apple Inc. All Rights Reserved.
"""

from __future__ import annotations

import click


@click.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option(
    "--public/--no-public",
    default=False,
    show_default=True,
    help="Bind to 0.0.0.0 for LAN/tunnels. Requires --password.",
)
@click.option(
    "--password",
    default=None,
    help="Password for HTTP Basic auth (avoid if you care about shell history).",
)
def web_cli(host: str, port: int, public: bool, password: str | None) -> None:
    """Run a tiny web app to generate a panning MP4 from a single image."""
    try:
        import uvicorn
    except ImportError as exc:
        raise click.ClickException(
            "uvicorn is not installed. Install web deps with: "
            "pip install -r requirements-web.txt"
        ) from exc

    from sharp.web.app import create_app

    if public and host == "127.0.0.1":
        host = "0.0.0.0"

    if public and not password:
        raise click.ClickException(
            "Refusing to run publicly without a password. Pass --password (HTTP Basic auth)."
        )

    try:
        app = create_app(password=password)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    uvicorn_kwargs: dict[str, object] = {"host": host, "port": port}
    if public:
        uvicorn_kwargs["proxy_headers"] = True
        uvicorn_kwargs["forwarded_allow_ips"] = "*"

    uvicorn.run(app, **uvicorn_kwargs)
