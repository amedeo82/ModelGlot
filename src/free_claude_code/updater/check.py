"""Standalone version preflight for the native update launchers."""

import argparse
import re
import sys
from dataclasses import dataclass
from enum import Enum
from importlib.metadata import PackageNotFoundError, version

import httpx
from packaging.version import Version

RELEASE_URL = "https://github.com/amedeo82/ModelGlot/releases/"
PYPI_URL = "https://pypi.org/pypi/modelglot/{version}/json"
UPDATE_AVAILABLE = 10


class UpdateStatus(Enum):
    """Outcome of a published-version check."""

    AVAILABLE = "available"
    UP_TO_DATE = "up_to_date"
    LOCAL_NEWER = "local_newer"
    FAILED = "failed"


@dataclass(frozen=True)
class UpdateCheckResult:
    """Structured result returned to callers that only need version status."""

    status: UpdateStatus
    installed: str | None = None
    latest: str | None = None
    message: str = ""
    detail: str | None = None


def check_for_updates() -> UpdateCheckResult:
    """Check the installed version against the latest stable published release."""

    installed = None
    try:
        installed = version("modelglot")
        installed_version = Version(installed)
        if str(installed_version) == "0+unknown":
            raise ValueError("installed ModelGlot version is unknown")
        latest_version = _latest_stable_version()
    except (
        PackageNotFoundError,
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        return UpdateCheckResult(
            status=UpdateStatus.FAILED,
            installed=installed,
            message="Could not check for ModelGlot updates. Please retry.",
            detail=f"Could not check for ModelGlot updates: {exc}. Please retry.",
        )

    latest = str(latest_version)
    if installed_version == latest_version:
        return UpdateCheckResult(
            status=UpdateStatus.UP_TO_DATE,
            installed=installed,
            latest=latest,
            message=f"ModelGlot {installed} is already up to date.",
        )
    if installed_version > latest_version:
        return UpdateCheckResult(
            status=UpdateStatus.LOCAL_NEWER,
            installed=installed,
            latest=latest,
            message=(
                f"ModelGlot {installed} is newer than the published version {latest}. "
                "No update needed."
            ),
        )
    return UpdateCheckResult(
        status=UpdateStatus.AVAILABLE,
        installed=installed,
        latest=latest,
        message=f"ModelGlot update available: {installed} to {latest}.",
    )


def _latest_stable_version() -> Version:
    """Resolve and validate the latest stable GitHub and PyPI release."""

    with httpx.Client(timeout=10.0, follow_redirects=True, max_redirects=5) as client:
        response = client.get(RELEASE_URL + "latest")
        response.raise_for_status()
        selected = re.fullmatch(
            re.escape(RELEASE_URL)
            + r"tag/v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))",
            str(response.url),
        )
        if selected is None:
            raise ValueError("GitHub did not return a canonical ModelGlot release URL")
        published = selected[1]
        response = client.get(PYPI_URL.format(version=published))
        response.raise_for_status()
        metadata: dict[str, object] = response.json()
    info = metadata["info"]
    if not isinstance(info, dict):
        raise TypeError("PyPI metadata info is not an object")
    if info["version"] != published:
        raise ValueError("PyPI metadata does not match the selected ModelGlot release")
    latest = Version(published)
    files = metadata["urls"]
    if not isinstance(files, list) or not any(
        isinstance(file, dict) and file.get("yanked") is False for file in files
    ):
        raise ValueError("PyPI did not return an available stable ModelGlot release")
    return latest


class _Arguments(argparse.Namespace):
    print_version: bool = False


def main(argv: list[str] | None = None) -> int:
    """Return 10 to authorize installation, 0 to skip, or 1 on check failure."""

    parser = argparse.ArgumentParser(prog="_fcc-update-check")
    parser.add_argument("--print-version", action="store_true")
    arguments = _Arguments()
    parser.parse_args(argv, namespace=arguments)
    print_version = arguments.print_version
    result = check_for_updates()
    if result.status is UpdateStatus.FAILED:
        print(result.detail or result.message, file=sys.stderr)
        return 1

    output = sys.stderr if print_version else sys.stdout
    if result.status is UpdateStatus.AVAILABLE:
        print(
            f"ModelGlot update available: {result.installed} to {result.latest}. "
            "Running the installer.",
            file=output,
        )
        if print_version:
            print(result.latest)
        return UPDATE_AVAILABLE
    print(result.message, file=output)
    return 0
