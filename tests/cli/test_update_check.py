"""The updater checks published versions before authorizing installation."""

from importlib.metadata import PackageNotFoundError
from typing import Protocol

import httpx
import pytest

from free_claude_code.updater import check as update_check


class CheckRunner(Protocol):
    def __call__(
        self,
        installed: str = "1.9.0",
        payload: object | None = None,
        status: int = 200,
        error: Exception | None = None,
        body: str | bytes | None = None,
        print_version: bool = False,
        structured: bool = False,
        release_url: str = (
            "https://github.com/amedeo82/free-claude-code/releases/tag/v1.10.0"
        ),
    ) -> int | update_check.UpdateCheckResult: ...


def release(version: str = "1.10.0", *, yanked: bool = False) -> dict[str, object]:
    return {"info": {"version": version}, "urls": [{"yanked": yanked}]}


@pytest.fixture
def check(monkeypatch: pytest.MonkeyPatch) -> CheckRunner:
    original_client = httpx.Client

    def run(
        installed: str = "1.9.0",
        payload: object | None = None,
        status: int = 200,
        error: Exception | None = None,
        body: str | bytes | None = None,
        print_version: bool = False,
        structured: bool = False,
        release_url: str = (
            "https://github.com/amedeo82/free-claude-code/releases/tag/v1.10.0"
        ),
    ) -> int | update_check.UpdateCheckResult:
        def installed_version(_name: str) -> str:
            return installed

        monkeypatch.setattr(update_check, "version", installed_version)

        def respond(request: httpx.Request) -> httpx.Response:
            if error is not None:
                raise error
            if str(request.url).endswith("/releases/latest"):
                return httpx.Response(302, headers={"Location": release_url})
            if str(request.url) == release_url:
                return httpx.Response(status, text="release")
            assert (
                str(request.url) == "https://pypi.org/pypi/free-claude-code/1.10.0/json"
            )
            if body is not None:
                return httpx.Response(status, content=body)
            return httpx.Response(status, json=payload)

        def client(
            *,
            timeout: float = 10.0,
            follow_redirects: bool = True,
            max_redirects: int = 5,
        ) -> httpx.Client:
            return original_client(
                transport=httpx.MockTransport(respond),
                timeout=timeout,
                follow_redirects=follow_redirects,
                max_redirects=max_redirects,
            )

        monkeypatch.setattr(update_check.httpx, "Client", client)
        if structured:
            return update_check.check_for_updates()
        return update_check.main(["--print-version"] if print_version else [])

    return run


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ("1.9.0", 10),
        ("1.10.0", 0),
        ("1.11.0", 0),
        ("1.10.0+local", 0),
        ("1.10.0.dev1", 10),
    ],
)
def test_version_comparison(
    check: CheckRunner,
    capsys: pytest.CaptureFixture[str],
    installed: str,
    expected: int,
) -> None:
    assert check(installed, release()) == expected
    output = capsys.readouterr()
    assert installed in output.out
    assert not output.err


@pytest.mark.parametrize(
    ("installed", "expected_status", "expected_latest"),
    [
        ("1.9.0", update_check.UpdateStatus.AVAILABLE, "1.10.0"),
        ("1.10.0", update_check.UpdateStatus.UP_TO_DATE, "1.10.0"),
        ("1.11.0", update_check.UpdateStatus.LOCAL_NEWER, "1.10.0"),
    ],
)
def test_structured_update_result(
    check: CheckRunner,
    installed: str,
    expected_status: update_check.UpdateStatus,
    expected_latest: str,
) -> None:
    result = check(installed, release(), structured=True)

    assert isinstance(result, update_check.UpdateCheckResult)
    assert result.status is expected_status
    assert result.installed == installed
    assert result.latest == expected_latest
    assert installed in result.message


def test_structured_update_result_contains_failure_detail(
    check: CheckRunner,
) -> None:
    result = check("1.9.0", release("invalid"), structured=True)

    assert isinstance(result, update_check.UpdateCheckResult)
    assert result.status is update_check.UpdateStatus.FAILED
    assert result.message == "Could not check for FCC updates. Please retry."
    assert result.detail is not None
    assert "Could not check for FCC updates" in result.detail


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"info": []},
        release("invalid"),
        release("2.0rc1"),
        release("2.0.dev1"),
        release("2.0"),
        release("v2.0.0"),
        release("02.0.0"),
        release("2.0.0.post1"),
        release("2.0.0+local"),
        release("2.0.0\n3.0.0"),
        release("2.0.0/../main"),
        release(yanked=True),
        {"info": {"version": "2.0"}, "urls": []},
        {"info": {"version": "2.0"}, "urls": [{}]},
    ],
)
def test_invalid_release_does_not_authorize_installation(
    check: CheckRunner,
    capsys: pytest.CaptureFixture[str],
    payload: object,
) -> None:
    assert check(payload=payload) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("installed", ["invalid", "0+unknown"])
def test_unknown_installed_version(check: CheckRunner, installed: str) -> None:
    assert check(installed, release()) == 1


def test_missing_distribution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(update_check, "version", missing)
    assert update_check.main([]) == 1
    assert capsys.readouterr().err


def test_http_error(
    check: CheckRunner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert check(payload=release(), status=503) == 1
    assert capsys.readouterr().err


def test_timeout(
    check: CheckRunner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert check(error=httpx.ReadTimeout("timed out")) == 1
    assert capsys.readouterr().err


def test_malformed_json(
    check: CheckRunner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert check(body="not JSON") == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("installed", ["1.9.0", "1.10.0", "1.11.0"])
def test_print_version_is_only_the_authorized_release(
    check: CheckRunner,
    capsys: pytest.CaptureFixture[str],
    installed: str,
) -> None:
    expected = 10 if installed == "1.9.0" else 0
    assert check(installed, release(), print_version=True) == expected
    output = capsys.readouterr()
    assert output.out == ("1.10.0\n" if expected == 10 else "")
    assert installed in output.err


def test_failed_preflight_prints_no_release(
    check: CheckRunner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert check(payload=release("2.0.0/../main"), print_version=True) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


@pytest.mark.parametrize(
    "suffix",
    ["v1.10.0rc1", "v01.10.0", "v1.10.0?query=1", "v1.10.0#fragment", "v1.10.0/extra"],
)
def test_invalid_github_release_does_not_authorize_installation(
    check: CheckRunner,
    suffix: str,
) -> None:
    assert (
        check(
            payload=release(),
            release_url="https://github.com/amedeo82/free-claude-code/releases/tag/"
            + suffix,
        )
        == 1
    )


def test_release_from_another_repository_is_rejected(check: CheckRunner) -> None:
    assert (
        check(
            payload=release(),
            release_url="https://github.com/other/repo/releases/tag/v1.10.0",
        )
        == 1
    )


def test_pypi_metadata_must_match_selected_github_release(
    check: CheckRunner,
) -> None:
    assert check(payload=release("1.11.0")) == 1
