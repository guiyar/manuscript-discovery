{
  lib,
  python3Packages,
  typst,
  fonts,
}:

python3Packages.buildPythonApplication {
  pname = "bible-typeset";
  version = "0.1.0";
  pyproject = true;
  src = lib.cleanSource ../.;

  build-system = [ python3Packages.hatchling ];
  dependencies = with python3Packages; [
    fastapi
    uvicorn
    pydantic-settings
    defusedxml
  ];

  # Typst and the fonts travel with the program: no reliance on the host's PATH or fontconfig.
  makeWrapperArgs = [
    "--prefix PATH : ${lib.makeBinPath [ typst ]}"
    "--set-default BIBLE_FONT_DIR ${fonts}/share/fonts"
  ];

  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    python3Packages.httpx
    typst
  ];
  preCheck = "export BIBLE_FONT_DIR=${fonts}/share/fonts";
  pythonImportsCheck = [ "bible_typeset" ];

  meta = {
    description = "Typeset verse ranges of eBible.org texts as PDF";
    mainProgram = "bible-typeset";
  };
}
