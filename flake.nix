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
      packages = forAllSystems (
        pkgs:
        let
          packages = import ./nix { inherit pkgs; };
          app = packages.default;
        in
        packages
        // nixpkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
          docker = pkgs.dockerTools.buildLayeredImage {
            name = "manuscript-discovery";
            tag = "latest";
            contents = [ app ];
            extraCommands = "mkdir -p tmp && chmod 1777 tmp";
            config = {
              Entrypoint = [ "${app}/bin/manuscript-discovery" ];
              Cmd = [ "serve" ];
              User = "65534:65534";
              ExposedPorts."8000/tcp" = { };
              Volumes."/data" = { };
              Env = [
                "MANUSCRIPT_DB_PATH=/data/library.sqlite"
                "MANUSCRIPT_HOST=0.0.0.0"
                "MANUSCRIPT_PORT=8000"
              ];
            };
          };
        }
      );

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
              echo "2) python -m manuscript_discovery            (serves the readable UI source)"
              echo "   python -m manuscript_discovery build-assets   (then it serves the minified build)"
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
