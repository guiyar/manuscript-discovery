# Static (non-variable) Noto Serif CJK, pinned to the upstream release tag.
#
# nixpkgs' noto-fonts-cjk-serif is the *variable* build. Typst before 0.15 draws that font as empty
# boxes in PNG export (the PDF is fine), and the preview is PNG. Keeping the static build in the font
# closure works on every Typst version tested (0.12 to 0.15). One file holds the SC, TC, JP, KR and HK
# families, which is what typography.py asks for.
{ stdenvNoCC, fetchurl }:

stdenvNoCC.mkDerivation {
  pname = "noto-serif-cjk-static";
  version = "2.003";

  src = fetchurl {
    url = "https://github.com/notofonts/noto-cjk/raw/Serif2.003/Serif/OTC/NotoSerifCJK-Regular.ttc";
    hash = "sha256-XZwxoFlgAZPJ15aKmYveiGzNx36TQAatJDtBeUxJan0=";
  };

  dontUnpack = true;
  installPhase = ''
    runHook preInstall
    install -Dm444 $src $out/share/fonts/opentype/noto-cjk/NotoSerifCJK-Regular.ttc
    runHook postInstall
  '';
}
