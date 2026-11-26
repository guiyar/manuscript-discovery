{
  description = "Manuscript Discovery: set any passage of eBible.org texts as a clean manuscript for study";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {

      packages = forAllSystems (pkgs: import ./nix { inherit pkgs; });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/manuscript-discovery";
        };
      });

      devShells = forAllSystems (
        pkgs:
        let
          fonts = self.packages.${pkgs.stdenv.hostPlatform.system}.fonts;
        in
        {
          default = pkgs.mkShell {
            packages = [
              (pkgs.python3.withPackages (
                ps: with ps; [
                  fastapi
                  uvicorn
                  pydantic-settings
                  defusedxml
                  pycountry
                  cachetools
                  pytest
                  httpx
                ]
              ))
              pkgs.typst
              pkgs.minify # builds the minified UI (manuscript-discovery build-assets)
              pkgs.tailwindcss_4 # compiles the UI stylesheet (ui/tailwind.css)
              pkgs.nodejs # UI tests: cd tests/ui && npm ci
              pkgs.poppler-utils # pdftotext / pdftoppm for inspecting output
              # Development Tools
              pkgs.hongdown
              pkgs.nixfmt-tree
              pkgs.pyright
              pkgs.ruff
            ];
            MANUSCRIPT_FONT_DIR = "${fonts}/share/fonts";
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
              export MANUSCRIPT_DB_PATH="''${MANUSCRIPT_DB_PATH:-$PWD/data/library.sqlite}"
              echo "1) python -m manuscript_discovery ingest <folder of *_usfx.zip>"
              echo "2) python -m manuscript_discovery build-assets   (compile Tailwind + minify; the UI is unstyled until then)"
              echo "   python -m manuscript_discovery            (serves the minified build, else the readable source)"
              echo "   tailwindcss -i ui/tailwind.css -o src/manuscript_discovery/static/styles.css --watch   (while editing the UI)"
              echo "3) pytest   (UI tests need once: cd tests/ui && npm ci)"
            '';
          };
        }
      );

      nixosModules.default = import ./nix/module.nix;

      # `nix flake check` builds the package, which runs the test suite.
      checks = forAllSystems (pkgs: {
        package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      });
    };
}
