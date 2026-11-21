{
  description = "Typeset any verse range of eBible.org texts as PDF, with optional parallel columns";

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
          # The fonts are part of the environment, so output no longer depends on whatever
          # happens to be installed on the host. Libertinus Serif covers Latin and polytonic
          # Greek; Noto Serif CJK covers Chinese/Japanese/Korean.
          fonts = pkgs.symlinkJoin {
            name = "bible-typeset-fonts";
            paths = [
              pkgs.libertinus
              pkgs.noto-fonts-cjk-serif
            ];
          };
          app = pkgs.callPackage ./nix/package.nix { inherit fonts; };
        in
        {
          default = app;
          inherit fonts;
        }
        // nixpkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
          # nix build .#docker && docker load < result
          docker = pkgs.dockerTools.buildLayeredImage {
            name = "bible-typeset";
            tag = "latest";
            contents = [ app ];
            extraCommands = "mkdir -p tmp && chmod 1777 tmp";
            config = {
              Cmd = [ "${app}/bin/bible-typeset" ];
              User = "65534:65534";
              ExposedPorts."8000/tcp" = { };
              Volumes."/data" = { };
              Env = [
                "BIBLE_DATA_DIR=/data"
                "BIBLE_HOST=0.0.0.0"
                "BIBLE_PORT=8000"
              ];
            };
          };
        }
      );

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/bible-typeset";
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
                  pytest
                  httpx
                ]
              ))
              pkgs.typst
              pkgs.poppler-utils # pdftotext / pdftoppm for inspecting output
              # Development Tools
              pkgs.pyright
              pkgs.ruff
            ];
            BIBLE_FONT_DIR = "${fonts}/share/fonts";
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
              export BIBLE_DATA_DIR="''${BIBLE_DATA_DIR:-$PWD/data}"
              echo "Put eBible *_usfx.zip files in $BIBLE_DATA_DIR, then: python -m bible_typeset"
            '';
          };
        }
      );

      nixosModules.default = import ./nix/module.nix self;

      # `nix flake check` builds the package, which runs the test suite.
      checks = forAllSystems (pkgs: {
        package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      });
    };
}
