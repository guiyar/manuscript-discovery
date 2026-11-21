{
  lib,
  python3Packages,
  typst,
  minify,
  fonts,
}:

python3Packages.buildPythonApplication {
  pname = "manuscript-discovery";
  version = "0.1.0";
  pyproject = true;
  src = lib.cleanSource ../.;

  build-system = [ python3Packages.hatchling ];
  # `minify` runs in the wheel build hook (hatch_build.py). Without it the build would quietly ship the
  # readable source, so this build insists on it.
  nativeBuildInputs = [ minify ];
  env.MANUSCRIPT_REQUIRE_MINIFY = "1";
  dependencies = with python3Packages; [
    fastapi
    uvicorn
    pydantic-settings
    defusedxml
    pycountry
    cachetools
  ];

  # Typst and the fonts travel with the program: no reliance on the host's PATH or fontconfig.
  makeWrapperArgs = [
    "--prefix PATH : ${lib.makeBinPath [ typst ]}"
    "--set-default MANUSCRIPT_FONT_DIR ${fonts}/share/fonts"
  ];

  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    python3Packages.httpx
    typst
  ];
  # The build fails if this font set cannot draw CJK in PNG previews (see diagnostics.py).
  preCheck = ''
    export MANUSCRIPT_FONT_DIR=${fonts}/share/fonts
    export MANUSCRIPT_EXPECT_CJK=1
  '';
  pythonImportsCheck = [ "manuscript_discovery" ];
  postInstallCheck = ''
    test -s $out/${python3Packages.python.sitePackages}/manuscript_discovery/static/dist/index.html \
      || { echo "the minified UI is missing from the installed package"; exit 1; }
  '';

  meta = {
    description = "Set any passage of eBible.org texts as a clean manuscript for study";
    mainProgram = "manuscript-discovery";
  };
}
