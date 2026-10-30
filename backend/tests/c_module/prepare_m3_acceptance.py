"""Project C and exact E ticket sources into a disposable runtime-test tree."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from prepare_resource_acceptance import git

E_REVISION = "820ebf7d2c1013050c45a042355c788868e2d16d"
E_MODULE = "backend/app/modules/m3_repair"
E_MIGRATIONS = {
    "backend/alembic/versions/" + name: f"backend/tests/c_module/pinned_{name[:3]}_migration.py"
    for name in ("e02_m3_tickets.py", "e03_m3_assignment.py")
}


def prepare(source: Path, output: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    source, output = source.resolve(), output.resolve()
    if output.is_relative_to(root) or output.is_relative_to(source):
        raise ValueError("Acceptance output must be outside source trees")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"e_revision": E_REVISION, "sha256": {}}
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    for name in names.decode().split("\0"):
        if not name.startswith(("backend/", "docs/", "database/")):
            continue
        path = root / name
        if not path.is_file() or path.is_symlink() or path.name == ".env":
            raise ValueError("Unexpected C source file")
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        manifest["sha256"][name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    names = git(source, "ls-tree", "-r", "--name-only", E_REVISION, "--", E_MODULE)
    if not names.strip():
        raise ValueError("Missing fixed E ticket module")
    for name in [*names.decode().splitlines(), *E_MIGRATIONS]:
        content = git(source, "show", E_REVISION + ":" + name)
        # Execute only the original E DDL in isolated test schemas, not the
        # unresolved A/C/E graph. Never add E's second head to product migrations.
        target = E_MIGRATIONS.get(name, name)
        destination = output / target
        if destination.exists() and destination.read_bytes() != content:
            raise ValueError("E source must not overwrite current project files")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        manifest["sha256"][target] = hashlib.sha256(content).hexdigest()
    (output / "m3-acceptance-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared fixed E module and unmodified migration DDL for isolated C/E runtime tests")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.output)
