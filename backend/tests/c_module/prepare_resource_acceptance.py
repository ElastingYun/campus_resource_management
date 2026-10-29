"""Build a disposable C+B test workspace from the current C tree and pinned B v2."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

B_REVISION = "4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3"
B_PATHS = ("backend/app/modules/resources", "backend/tests/resources")


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def prepare(source: Path, output: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    source, output = source.resolve(), output.resolve()
    if output.is_relative_to(root) or output.is_relative_to(source):
        raise ValueError("Acceptance output must be outside both source trees")
    if git(source, "rev-parse", "HEAD").decode().strip() != B_REVISION:
        raise ValueError("B acceptance source is not the reviewed fixed revision")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "b_revision": B_REVISION,
        "c_revision": git(root, "rev-parse", "HEAD").decode().strip(),
        "sha256": {},
    }
    names = (
        git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        .decode()
        .split("\0")
    )
    for name in names:
        if not name.startswith(("backend/", "docs/")):
            continue
        path = root / name
        if not path.is_file() or path.is_symlink() or path.name == ".env":
            raise ValueError("Unexpected source file in acceptance projection")
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        manifest["sha256"][name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    for prefix in B_PATHS:
        existing = (output / prefix).exists()
        names = (
            git(source, "ls-tree", "-r", "--name-only", B_REVISION, "--", prefix)
            .decode()
            .splitlines()
        )
        if not names:
            raise ValueError("Missing B public module or tests")
        if existing:
            actual_names = {
                str(path.relative_to(output))
                for path in (output / prefix).rglob("*")
                if path.is_file()
            }
            if actual_names != set(names):
                raise ValueError("Installed B source differs; review the pinned contract")
        for name in names:
            expected = git(source, "show", B_REVISION + ":" + name)
            path = source / name
            if path.is_symlink() or path.read_bytes() != expected:
                raise ValueError("B source bytes changed from the pinned revision")
            destination = output / name
            if existing:
                if destination.read_bytes() != expected:
                    raise ValueError("B source must not overwrite current workspace files")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(expected)
            manifest["sha256"][name] = hashlib.sha256(expected).hexdigest()
    (output / "acceptance-source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared pinned B v2 and current C acceptance sources; manifest written")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    prepare(arguments.source, arguments.output)
