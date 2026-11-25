{
  pkgs ? import <nixpkgs> { },
}:

let
  # Fonts are part of the environment, so output never depends on what the host has
  # installed. Libertinus Serif covers Latin, Greek and Cyrillic; the STATIC Noto Serif CJK
  # covers Chinese/Japanese/Korean (not nixpkgs' variable build: see nix/cjk-font.nix);
  # Noto supplies per-glyph fallback for other scripts.
  fonts = pkgs.symlinkJoin {
    name = "manuscript-discovery-fonts";
    paths = [
      pkgs.libertinus
      pkgs.noto-fonts
      (pkgs.callPackage ./cjk-font.nix { })
    ];
  };

  app = pkgs.callPackage ./package.nix {
    inherit fonts;
  };
in
{
  default = app;
  inherit fonts;
}
