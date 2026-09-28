{
  description = "ThGit: native Python/Git save synchronization and Wine launcher";

  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-26.05/nixexprs.tar.xz";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      python = pkgs.python3;
      wine = pkgs.wineWowPackages.stable;
      thgit = python.pkgs.buildPythonApplication {
        pname = "thgit";
        version = "0.2.0";
        pyproject = true;
        src = pkgs.lib.cleanSource ./.;
        build-system = [ python.pkgs.setuptools ];
        nativeBuildInputs = [ pkgs.makeWrapper ];
        nativeCheckInputs = [ pkgs.git ];
        checkPhase = ''
          runHook preCheck
          PYTHONPATH=src ${python.interpreter} -m unittest discover -s tests -v
          runHook postCheck
        '';
        pythonImportsCheck = [ "thgit" "thgit.cli" ];
        postFixup = ''
          wrapProgram "$out/bin/thgit" \
            --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.git pkgs.openssh wine ]}
        '';
        meta = {
          description = "Cross-platform Touhou save synchronization and launcher";
          license = pkgs.lib.licenses.mit;
          platforms = [ system ];
          mainProgram = "thgit";
        };
      };
    in {
      packages.${system}.default = thgit;
      apps.${system}.default = {
        type = "app";
        program = "${thgit}/bin/thgit";
      };
      devShells.${system}.default = pkgs.mkShell {
        packages = [ python python.pkgs.setuptools pkgs.git pkgs.openssh wine pkgs.ruff ];
      };
      checks.${system}.default = thgit;
    };
}
