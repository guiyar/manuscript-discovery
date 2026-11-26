"""Build the web UI before it is served: compile the Tailwind stylesheet, then minify.

Deliberately standard-library only: the wheel build hook (hatch_build.py) loads this file
directly, before the package's dependencies exist. The stylesheet is compiled by the standalone
Tailwind CLI. The minifier is tdewolff/minify (the one Hugo uses): a single binary that handles
HTML with inline CSS and JS, and standalone CSS/JS/SVG.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SUFFIXES = {".html", ".css", ".js", ".svg"}

# Tailwind's input lives outside the package (it is not served); it lists index.html as a source.
TAILWIND_SOURCE = Path(__file__).resolve().parents[2] / "ui" / "tailwind.css"


def compile_css(
    output: Path, source: Path = TAILWIND_SOURCE, tailwind_bin: str = "tailwindcss"
) -> Path:
    """Compile the Tailwind stylesheet (source) to output, normally static/styles.css."""
    exe = shutil.which(tailwind_bin)
    if exe is None:
        raise FileNotFoundError(
            f"{tailwind_bin!r} not found on PATH (https://tailwindcss.com/docs/installation/tailwind-cli)"
        )
    if not source.is_file():
        raise FileNotFoundError(f"{source} not found: run this from a source checkout")
    done = subprocess.run(
        [exe, "-i", str(source), "-o", str(output)], capture_output=True, text=True
    )
    if done.returncode:
        raise RuntimeError(f"tailwindcss failed:\n{done.stderr.strip()}")
    return output


def build(static_dir: Path, minify_bin: str = "minify") -> list[Path]:
    """Minify every asset in static_dir into static_dir/dist and return the files written."""
    exe = shutil.which(minify_bin)
    if exe is None:
        raise FileNotFoundError(
            f"{minify_bin!r} not found on PATH (https://github.com/tdewolff/minify)"
        )
    dist = static_dir / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    dist.mkdir()
    written = []
    for src in sorted(
        p for p in static_dir.iterdir() if p.is_file() and p.suffix in SUFFIXES
    ):
        target = dist / src.name
        subprocess.run(
            [exe, "-o", str(target), str(src)], check=True, capture_output=True
        )
        written.append(target)
    return written


def serving_root(static_dir: Path) -> Path:
    """Where to serve from: the minified build if there is one, else the readable source."""
    dist = static_dir / "dist"
    return dist if (dist / "index.html").is_file() else static_dir
