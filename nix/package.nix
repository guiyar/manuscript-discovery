{
  lib,
  python3Packages,
  typst,
  minify,
  tailwindcss_4,
  fonts,
}:

python3Packages.buildPythonApplication {
  pname = "manuscript-discovery";
  version = "0.1.0";
  pyproject = true;
  src = lib.cleanSource ../.;

  build-system = [ python3Packages.hatchling ];
  # `tailwindcss` and `minify` run in the wheel build hook (hatch_build.py). Without them the build
  # would quietly ship an unstyled, unminified UI, so this build insists on both.
  nativeBuildInputs = [
    minify
    tailwindcss_4
  ];
  env.MANUSCRIPT_REQUIRE_MINIFY = "1";
  env.MANUSCRIPT_REQUIRE_TAILWIND = "1";
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
    for f in index.html styles.css; do
      test -s $out/${python3Packages.python.sitePackages}/manuscript_discovery/static/dist/$f \
        || { echo "the built UI ($f) is missing from the installed package"; exit 1; }
    done
  '';

  meta = {
    description = "Set any passage of eBible.org texts as a clean manuscript for study";
    mainProgram = "manuscript-discovery";
  };
}
