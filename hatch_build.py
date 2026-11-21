"""Wheel build hook: ship minified assets (see src/manuscript_discovery/assets.py).

Without `minify` on PATH the build still works and ships the readable source (the app serves it
as a fallback), unless MANUSCRIPT_REQUIRE_MINIFY is set, as it is in the Nix build.
"""

import importlib.util
import os
import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class MinifyAssets(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        root = Path(self.root) / "src" / "manuscript_discovery"
        if shutil.which("minify") is None:
            if os.environ.get("MANUSCRIPT_REQUIRE_MINIFY"):
                raise RuntimeError(
                    "MANUSCRIPT_REQUIRE_MINIFY is set but `minify` is not on PATH"
                )
            self.app.display_warning("minify not found: shipping unminified assets")
            return
        spec = importlib.util.spec_from_file_location("md_assets", root / "assets.py")
        assets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assets)
        written = assets.build(root / "static")
        self.app.display_info(f"minified {len(written)} asset(s)")
        build_data["artifacts"].append(
            "src/manuscript_discovery/static/dist/*"
        )  # generated, so gitignored
