{
  description = "Convert electronic schematics into AI-readable files (JSON + Markdown)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          schematic2ai = pkgs.callPackage ./package.nix { };
          default = self.packages.${system}.schematic2ai;
        }
      );

      overlays.default = final: prev: {
        schematic2ai = final.callPackage ./package.nix { };
      };

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            inputsFrom = [ self.packages.${system}.schematic2ai ];
            packages = with pkgs; [
              tesseract
              python3Packages.pytest
              python3Packages.pytest-benchmark
              python3Packages.pyyaml # benchmarks/ground_truth.yaml
            ];
            # src-layout: run pytest / python -m schematic2ai against the
            # working tree without pip install -e .
            shellHook = ''
              export PYTHONPATH="''${PWD}/src''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        }
      );
    };
}
