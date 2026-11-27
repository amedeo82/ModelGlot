"""Reject incomplete built distributions before they can be uploaded."""

import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from tests.scripts.test_version_policy import git, write

VALIDATOR = Path(__file__).resolve().parents[2] / "scripts/validate_release.py"


@pytest.fixture
def release(tmp_path: Path):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init")
    files = {
        "pyproject.toml": '[project]\nname="modelglot"\ndynamic=["version"]\n[project.scripts]\nmodelglot-server="modelglot.cli:serve"\n[project.gui-scripts]\nmodelglot-desktop="modelglot.desktop:launch"\n',
        "README.md": "readme",
        "LICENSE": "license",
        "scripts/update/modelglot-update": "#!/bin/sh\n",
        "scripts/update/modelglot-update.cmd": "@echo off\n",
        "scripts/build_macos_launcher.py": "# native build\n",
        "scripts/macos/launcher.m": "// launcher\n",
        "src/modelglot/__init__.py": "",
        "src/modelglot/cli.py": "",
        "src/modelglot/desktop.py": "",
        "src/modelglot/assets/icon.png": "icon",
        "src/modelglot/api/admin_static/index.html": "page",
    }
    for name, content in files.items():
        write(repo, name, content)
    git(repo, "add", ".")
    # Generated templates are deliberately absent from git ls-files.
    for architecture in ("arm64", "x86_64"):
        files[f"src/modelglot/assets/macos/modelglot-desktop-{architecture}"] = (
            architecture
        )
    metadata = "Name: modelglot\nVersion: 1.2.3\n"
    wheel = {
        name.removeprefix("src/"): content
        for name, content in files.items()
        if name.startswith("src/")
    }
    for name in ("modelglot-update", "modelglot-update.cmd"):
        wheel[f"modelglot-1.2.3.data/scripts/{name}"] = files[f"scripts/update/{name}"]
    wheel["modelglot-1.2.3.dist-info/METADATA"] = metadata
    wheel["modelglot-1.2.3.dist-info/entry_points.txt"] = (
        "[console_scripts]\nmodelglot-server=modelglot.cli:serve\n"
        "[gui_scripts]\nmodelglot-desktop=modelglot.desktop:launch\n"
    )
    sdist = {f"modelglot-1.2.3/{name}": body for name, body in files.items()}
    sdist["modelglot-1.2.3/PKG-INFO"] = metadata
    return repo, wheel, sdist


def validate(release: tuple[Path, dict[str, str], dict[str, str]], tmp_path: Path):
    repo, wheel, sdist = release
    dist = tmp_path / "built"
    dist.mkdir()
    (dist / ".gitignore").write_text("*")
    with zipfile.ZipFile(dist / "modelglot-1.2.3-py3-none-any.whl", "w") as archive:
        for name, body in wheel.items():
            archive.writestr(name, body)
    with tarfile.open(dist / "modelglot-1.2.3.tar.gz", "w:gz") as archive:
        for name, body in sdist.items():
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(dist), "--version", "1.2.3"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_complete_release_passes(
    release: tuple[Path, dict[str, str], dict[str, str]], tmp_path: Path
) -> None:
    result = validate(release, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("archive", [1, 2])
@pytest.mark.parametrize(
    "suffix",
    [
        "assets/icon.png",
        "scripts/modelglot-update.cmd",
        "entry_points.txt",
        "METADATA",
        "assets/macos/modelglot-desktop-arm64",
        "assets/macos/modelglot-desktop-x86_64",
    ],
)
def test_missing_wheel_or_sdist_content_fails(
    release: tuple[Path, dict[str, str], dict[str, str]],
    tmp_path: Path,
    archive: int,
    suffix: str,
) -> None:
    if archive == 2:
        suffix = {
            "scripts/modelglot-update.cmd": "scripts/update/modelglot-update.cmd",
            "entry_points.txt": "pyproject.toml",
            "METADATA": "PKG-INFO",
        }.get(suffix, suffix)
    entries = release[1] if archive == 1 else release[2]
    missing = next(name for name in entries if name.endswith(suffix))
    del entries[missing]
    result = validate(release, tmp_path)
    assert result.returncode != 0
    assert "missing" in result.stdout.lower()


def test_wrong_version_or_entrypoint_fails(
    release: tuple[Path, dict[str, str], dict[str, str]], tmp_path: Path
) -> None:
    release[1]["modelglot-1.2.3.dist-info/entry_points.txt"] = (
        "[console_scripts]\nmodelglot-server=wrong:command\n"
    )
    result = validate(release, tmp_path)
    assert result.returncode != 0
    assert "entry" in result.stdout.lower()


def test_mismatched_metadata_fails(
    release: tuple[Path, dict[str, str], dict[str, str]], tmp_path: Path
) -> None:
    release[2]["modelglot-1.2.3/PKG-INFO"] = "Name: modelglot\nVersion: 0.1.0\n"
    result = validate(release, tmp_path)
    assert result.returncode != 0
    assert "metadata" in result.stdout.lower()


def test_mismatched_native_templates_fail(
    release: tuple[Path, dict[str, str], dict[str, str]], tmp_path: Path
) -> None:
    release[1]["modelglot/assets/macos/modelglot-desktop-arm64"] = "different"
    result = validate(release, tmp_path)
    assert result.returncode != 0
    assert "template" in result.stdout.lower()


@pytest.mark.parametrize(
    "name", ["scripts/macos/launcher.m", "scripts/build_macos_launcher.py"]
)
def test_native_sources_required_in_sdist(
    release: tuple[Path, dict[str, str], dict[str, str]], tmp_path: Path, name: str
) -> None:
    del release[2][f"modelglot-1.2.3/{name}"]
    result = validate(release, tmp_path)
    assert result.returncode != 0
    assert "missing" in result.stdout.lower()
