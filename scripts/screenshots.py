# SPDX-License-Identifier: GPL-3.0-or-later
"""README screenshots of the app on a fictional journal (#80, D-034): headless Firefox.

    make build
    uv run python scripts/demo_journal.py build/demo/journal.xlsx
    uv run python scripts/screenshots.py build/demo/config.toml docs/screenshots

build/demo/config.toml is written by hand (the demo script writes only the workbook):

    [modules.journal]
    definition = "/abs/path/to/climb-log/modules/journal.yaml"
    workbook = "/abs/path/to/climb-log/build/demo/journal.xlsx"

Serves the built app on the given app config (a fictional journal only), then captures each
page with `firefox --headless --screenshot`. Firefox takes its picture at the page's load
event, before the app has fetched its data, so each page is shown in a frame by a small local
page whose load event waits a few seconds (a slow image). Run from the repository root; Firefox
gets a throwaway profile under `build/`, so a running Firefox is not disturbed.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DAY = "2026-10-30"  # the day the pages show (the demo journal ends there)
PAGES = {  # file → (path, height)
    "today.png": (f"/?date={DAY}", 1100),
    "dashboard.png": (f"/dashboards/journal?date={DAY}", 2100),
}
WIDTH = 1400
PIXEL = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


class _Frames(BaseHTTPRequestHandler):
    """`/?url=…&h=…`: the url in a frame, and an image that answers after `wait` seconds."""

    wait = 6.0

    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/slow.gif":
            time.sleep(self.wait)
            self._send("image/gif", PIXEL)
            return
        target = query.get("url", [""])[0]
        height = query.get("h", ["1000"])[0]
        page = (
            '<html><body style="margin:0">'
            f'<iframe src="{target}" style="border:0;width:{WIDTH}px;height:{height}px"></iframe>'
            '<img src="/slow.gif" style="position:absolute;width:1px;height:1px">'
            "</body></html>"
        )
        self._send("text/html", page.encode())

    def _send(self, kind: str, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


def _wait_for(url: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2).close()
            return
        except OSError:
            time.sleep(0.5)
    sys.exit(f"{url} did not answer")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("config", type=Path, help="an app config with a fictional journal")
    parser.add_argument("out", type=Path, help="the folder for the PNG files")
    parser.add_argument("--port", type=int, default=8031)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "CLIMBLOG_CONFIG": str(args.config.resolve())}
    app = subprocess.Popen(
        [str(Path(sys.executable).parent / "climblog"), "serve", "--port", str(args.port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    frames = ThreadingHTTPServer(("127.0.0.1", 0), _Frames)
    threading.Thread(target=frames.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{args.port}"
        _wait_for(f"{base}/api/health")
        Path("build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="build") as profile:
            for name, (path, height) in PAGES.items():
                target = urllib.parse.quote(base + path, safe="")
                url = f"http://127.0.0.1:{frames.server_port}/?url={target}&h={height}"
                shot = (args.out / name).resolve()
                subprocess.run(
                    [
                        "firefox",
                        "--headless",
                        "--no-remote",
                        "--profile",
                        str(Path(profile).resolve()),
                        f"--window-size={WIDTH},{height}",
                        "--screenshot",
                        str(shot),
                        url,
                    ],
                    check=True,
                    timeout=120,
                    capture_output=True,
                )
                print(f"{shot}: {path}")
    finally:
        frames.shutdown()
        app.terminate()
        app.wait(timeout=10)


if __name__ == "__main__":
    main()
