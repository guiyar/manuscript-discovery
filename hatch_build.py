"""Wheel build hook: ship the compiled stylesheet and minified assets (see
src/manuscript_discovery/assets.py).

Without `tailwindcss` on PATH the build still works but the UI is unstyled; without `minify` it
ships the readable source (the app serves it as a fallback). MANUSCRIPT_REQUIRE_TAILWIND and
MANUSCRIPT_REQUIRE_MINIFY turn those into errors, as they are in the Nix build.
"""

import importlib.util
import os
import shutil
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class BuildAssets(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def _have(self, tool, require_var, consequence):
        if shutil.which(tool):
            return True
        if os.environ.get(require_var):
            raise RuntimeError(f"{require_var} is set but `{tool}` is not on PATH")
        self.app.display_warning(f"{tool} not found: {consequence}")
        return False

    def initialize(self, version, build_data):
        root = Path(self.root)
        pkg = root / "src" / "manuscript_discovery"
        spec = importlib.util.spec_from_file_location("md_assets", pkg / "assets.py")
        assets = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assets)

        # Generated, so gitignored: name them so the wheel includes them.
        if self._have(
            "tailwindcss", "MANUSCRIPT_REQUIRE_TAILWIND", "the UI will be unstyled"
        ):
            sheet = assets.compile_css(
                pkg / "static" / "styles.css", root / "ui" / "tailwind.css"
            )
            self.app.display_info(f"compiled {sheet.name}")
            build_data["artifacts"].append("src/manuscript_discovery/static/styles.css")
        if self._have(
            "minify", "MANUSCRIPT_REQUIRE_MINIFY", "shipping unminified assets"
        ):
            written = assets.build(pkg / "static")
            self.app.display_info(f"minified {len(written)} asset(s)")
            build_data["artifacts"].append("src/manuscript_discovery/static/dist/*")
