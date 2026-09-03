{
  lib,
  python3Packages,
  tesseract,
}:

let
  pyproject = lib.importTOML ./pyproject.toml;
in
python3Packages.buildPythonApplication {
  pname = pyproject.project.name;
  inherit (pyproject.project) version;
  pyproject = true;

  src = lib.cleanSource ./.;

  build-system = with python3Packages; [
    setuptools
    wheel
  ];

  dependencies = with python3Packages; [
    # PDF + image processing
    pdfplumber
    pypdfium2
    pillow
    # OCR (pytesseract shells out to the tesseract binary — see makeWrapperArgs)
    pytesseract
    # KiCad / Altium / EAGLE parsing
    sexpdata
    lxml
    # CLI
    click
    rich
  ];

  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    # Not strictly needed for the default run (pyproject addopts already
    # deselects -m benchmark), but present so collection of
    # tests/benchmarks/ can't fail on a missing plugin/fixture.
    python3Packages.pytest-benchmark
    tesseract
  ];

  # Applies to all three entry points (sch2ai, schtoai, schematic2ai).
  makeWrapperArgs = [ "--prefix" "PATH" ":" (lib.makeBinPath [ tesseract ]) ];

  meta = {
    description = "Convert schematics (PDF, images, KiCad, Altium, EAGLE, SPICE, Gerber) into AI-readable JSON + Markdown";
    homepage = "https://github.com/janbajc/schematic2ai";
    license = lib.licenses.mit;
    mainProgram = "sch2ai";
  };
}
