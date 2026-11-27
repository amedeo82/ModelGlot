import re
import subprocess
import sys
import tomllib
from pathlib import Path

from tests.wire_payload import object_payload


def test_pyproject_first_party_packages_match_packaged_roots() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"known-first-party = \[(?P<items>[^\]]+)\]", pyproject)

    assert match is not None
    configured = {
        item.strip().strip('"')
        for item in match.group("items").split(",")
        if item.strip()
    }
    expected = {"modelglot", "smoke"}
    assert configured == expected


def test_pyproject_packages_the_modelglot_source_tree() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    project = object_payload(
        tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    )
    tool = object_payload(project["tool"])
    hatch = object_payload(tool["hatch"])
    build = object_payload(hatch["build"])
    targets = object_payload(build["targets"])
    wheel = object_payload(targets["wheel"])
    metadata = object_payload(project["project"])
    scripts = object_payload(metadata["scripts"])
    gui_scripts = object_payload(metadata["gui-scripts"])

    assert wheel["packages"] == ["src/modelglot"]
    assert all(
        isinstance(target, str) and target.startswith("modelglot.")
        for target in scripts.values()
    )
    assert all(
        isinstance(target, str) and target.startswith("modelglot.")
        for target in gui_scripts.values()
    )


def test_standard_install_can_load_nim_transcription_client() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from riva.client import Auth, ASRService, RecognitionConfig; "
            "RecognitionConfig(language_code='en-US', max_alternatives=1)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
