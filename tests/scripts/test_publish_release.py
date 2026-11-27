"""Release ordering and interrupted publication use real Git history."""

import hashlib
import json
import shutil
from itertools import pairwise
from pathlib import Path
from typing import TypedDict

import pytest

from scripts import publish_release as publishing
from scripts.check_version_policy import next_version
from tests.scripts.test_version_policy import commit, git, write


@pytest.mark.parametrize(
    "kind,expected", [("patch", "6.2.67"), ("minor", "6.3.0"), ("major", "7.0.0")]
)
def test_one_increment(kind: str, expected: str) -> None:
    assert next_version("6.2.66", kind) == expected


@pytest.fixture(scope="session")
def releases_template(tmp_path_factory: pytest.TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("publish-release-template")
    git(tmp_path, "init", "--template=", "-b", "main")
    write(tmp_path, "src/file.py", "base")
    write(tmp_path, "scripts/build_macos_launcher.py", "# target builder")
    write(tmp_path, "scripts/validate_release.py", "# target validator")
    base = commit(tmp_path)
    git(tmp_path, "tag", "v1.2.3")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", base)
    return tmp_path


@pytest.fixture
def releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, releases_template: Path):
    shutil.copytree(releases_template, tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    state = FakeRemote(tmp_path)
    monkeypatch.setattr(publishing, "command", state.command)
    return tmp_path, state


class Asset(TypedDict):
    name: str
    state: str
    size: int
    digest: str


class Release(TypedDict):
    id: int
    tag_name: str
    draft: bool
    prerelease: bool
    assets: list[Asset]


class FakeRemote:
    def __init__(self, repo: Path):
        self.repo = repo
        self.releases: dict[str, Release] = {
            "v1.2.3": {
                "id": 1,
                "tag_name": "v1.2.3",
                "draft": False,
                "prerelease": False,
                "assets": [],
            }
        }
        self.files = {}
        self.calls = []
        self.fail: str | None = None
        self.builds = 0
        self.native_builds = []
        self.uploaded = {}
        self.note_requests = []
        self.real_command = publishing.command

    def command(self, args: list[str], *, cwd: Path | None = None):
        if "--repo" in args:
            args = args[: args.index("--repo")]
        self.calls.append(args)
        if args[0] == "git":
            if args[1] in {"fetch", "push"}:
                return ""
            return git(Path(cwd or self.repo), *args[1:])
        if args[:2] == ["gh", "api"]:
            endpoint = next(arg for arg in args if arg.startswith("repos/"))
            fields = dict(
                field.split("=", 1)
                for flag, field in pairwise(args)
                if flag in {"-f", "-F"}
            )
            if endpoint.endswith("?per_page=100"):
                return json.dumps([list(self.releases.values())])
            if endpoint.endswith("/generate-notes"):
                self.note_requests.append(fields)
                if "previous_tag_name" in fields:
                    assert fields["previous_tag_name"] in self.releases
                return json.dumps({"body": "Generated release notes"})
            if endpoint.endswith("/releases"):
                assert fields["draft"] == "true"
                assert fields["body"] == "Generated release notes"
                tag = fields["tag_name"]
                self.releases[tag] = {
                    "id": len(self.releases) + 1,
                    "tag_name": tag,
                    "draft": True,
                    "prerelease": False,
                    "assets": [],
                }
                return json.dumps(self.releases[tag])
            release_id = int(endpoint.rsplit("/", 1)[1])
            return json.dumps(
                next(r for r in self.releases.values() if r["id"] == release_id)
            )
        if args[:3] == ["gh", "release", "upload"]:
            tag = args[3]
            for filename in args[4:]:
                file = Path(filename)
                data = file.read_bytes()
                self.files[tag, file.name] = data
                self.releases[tag]["assets"].append(
                    {
                        "name": file.name,
                        "state": "uploaded",
                        "size": len(data),
                        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                    }
                )
                if self.fail == "stage":
                    self.fail: str | None = None
                    raise RuntimeError("interrupted staging")
        elif args[:3] == ["gh", "release", "delete-asset"]:
            tag, name = args[3:5]
            self.releases[tag]["assets"] = [
                a for a in self.releases[tag]["assets"] if a["name"] != name
            ]
            self.files.pop((tag, name), None)
        elif args[:3] == ["gh", "release", "download"]:
            tag = args[3]
            dest = Path(args[args.index("--dir") + 1])
            for asset in self.releases[tag]["assets"]:
                (dest / asset["name"]).write_bytes(self.files[tag, asset["name"]])
        elif args[:3] == ["gh", "release", "edit"]:
            if self.fail == "finalize":
                self.fail: str | None = None
                raise RuntimeError("interrupted finalization")
            self.releases[args[3]]["draft"] = False
        elif args[:2] == ["uv", "build"]:
            self.builds += 1
            assert cwd is not None
            if (Path(cwd) / "scripts/build_macos_launcher.py").is_file():
                assert self.native_builds[-1] == git(Path(cwd), "rev-parse", "HEAD")
            version = git(Path(cwd), "describe", "--tags", "--exact-match")[1:]
            out = Path(args[args.index("--out-dir") + 1])
            for name in publishing.distribution_names(version):
                (out / name).write_bytes(f"build {self.builds}: {name}".encode())
        elif args[:2] == ["uv", "publish"]:
            for file in map(Path, args[4:]):
                data = file.read_bytes()
                if file.name in self.uploaded:
                    assert self.uploaded[file.name] == data
                self.uploaded[file.name] = data
                if self.fail == "publish":
                    self.fail: str | None = None
                    raise RuntimeError("interrupted publication")
        elif args[0] == publishing.sys.executable:
            assert cwd is not None
            assert Path(args[1]).parent == Path(cwd) / "scripts"
            if Path(args[1]).name == "build_macos_launcher.py":
                assert Path(args[1]).read_text() == "# target builder"
                self.native_builds.append(git(Path(cwd), "rev-parse", "HEAD"))
            # Archive validation is exercised separately using real archives.
        else:
            raise AssertionError(args)
        return ""

    def advance(self, title: str = "patch: Change", path: str = "src/file.py"):
        write(self.repo, path, title)
        head = commit(self.repo, title)
        git(self.repo, "update-ref", "refs/remotes/origin/main", head)
        return head

    def publisher(self):
        return publishing.Publisher("owner/repo")


def modelglot_major(remote: FakeRemote, title: str = "major: Migrate to ModelGlot"):
    write(
        remote.repo,
        "pyproject.toml",
        '[project]\nname="modelglot"\ndynamic=["version"]\n',
    )
    write(
        remote.repo,
        "uv.lock",
        '[[package]]\nname="modelglot"\nsource={editable="."}\n',
    )
    return remote.advance(title)


def test_nonrelease_never_allocates_or_builds(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    head = remote.advance("Explain usage", "README.md")
    remote.publisher().publish(head)
    assert remote.builds == 0
    assert not any(c[:2] == ["git", "push"] for c in remote.calls)


def test_native_preparation_uses_release_commit_despite_dirty_current_checkout(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    head = remote.advance()
    write(
        repo, "scripts/build_macos_launcher.py", "# unrelated work in current checkout"
    )
    remote.publisher().publish(head)
    assert remote.native_builds == [head]
    assert (
        repo / "scripts/build_macos_launcher.py"
    ).read_text() == "# unrelated work in current checkout"


def test_historical_release_without_native_builder_can_resume(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    git(repo, "rm", "scripts/build_macos_launcher.py")
    head = remote.advance()
    remote.fail = "publish"
    with pytest.raises(RuntimeError, match="interrupted publication"):
        remote.publisher().publish(head)
    remote.publisher().publish(head)
    assert remote.native_builds == []
    assert remote.builds == 1


@pytest.mark.parametrize("existing_draft", [False, True])
def test_stale_release_list_does_not_block_staging(
    releases: tuple[Path, FakeRemote],
    monkeypatch: pytest.MonkeyPatch,
    existing_draft: bool,
) -> None:
    _, remote = releases
    head = remote.advance()
    if existing_draft:
        remote.fail = "stage"
        with pytest.raises(RuntimeError, match="interrupted staging"):
            remote.publisher().publish(head)
    listed = json.dumps([list(remote.releases.values())])

    def stale_listing(args: list[str], *, cwd: Path | None = None):
        if args[:2] == ["gh", "api"] and any(
            arg.endswith("/releases?per_page=100") for arg in args
        ):
            return listed
        return remote.command(args, cwd=cwd)

    monkeypatch.setattr(publishing, "command", stale_listing)
    remote.publisher().publish(head)
    assert not remote.releases["v1.2.4"]["draft"]
    assert set(remote.uploaded) == set(publishing.distribution_names("1.2.4"))


@pytest.mark.parametrize("failure", ["stage", "publish", "finalize"])
def test_retries_keep_version_and_published_bytes(
    releases: tuple[Path, FakeRemote], failure: str
) -> None:
    repo, remote = releases
    head = remote.advance()
    remote.fail = failure
    with pytest.raises(RuntimeError):
        remote.publisher().publish(head)
    first_uploaded = dict(remote.uploaded)
    assert remote.releases["v1.2.4"]["draft"]
    remote.publisher().publish(head)
    assert not remote.releases["v1.2.4"]["draft"]
    assert git(repo, "rev-parse", "v1.2.4") == head
    assert remote.builds == (2 if failure == "stage" else 1)
    assert remote.native_builds == [head] * remote.builds
    assert all(remote.uploaded[name] == value for name, value in first_uploaded.items())
    builds = remote.builds
    remote.publisher().publish(head)
    assert remote.builds == builds


def test_later_commit_waits_even_if_previous_failed_before_tag(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    first = remote.advance()
    second = remote.advance("minor: Second")
    with pytest.raises(ValueError, match=first):
        remote.publisher().publish(second)
    remote.publisher().publish(first)
    remote.publisher().publish(second)
    assert not remote.releases["v1.3.0"]["draft"]


def test_later_commit_waits_for_draft_and_old_retry_is_noop(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    first = remote.advance()
    remote.fail = "publish"
    with pytest.raises(RuntimeError):
        remote.publisher().publish(first)
    second = remote.advance("major: Second")
    with pytest.raises(ValueError, match=r"v1\.2\.4"):
        remote.publisher().publish(second)
    remote.publisher().publish(first)
    remote.publisher().publish(second)
    calls = len(remote.calls)
    remote.publisher().publish(first)
    assert not any(c[:3] == ["gh", "release", "edit"] for c in remote.calls[calls:])


def test_publish_after_withdrawn_draft_and_reject_its_retry(
    releases: tuple[Path, FakeRemote], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, remote = releases
    withdrawn = remote.advance("patch: Withdrawn change")
    git(repo, "tag", "v1.2.4", withdrawn)
    withdrawn_release: Release = {
        "id": 2,
        "tag_name": "v1.2.4",
        "draft": True,
        "prerelease": False,
        "assets": [],
    }
    remote.releases["v1.2.4"] = withdrawn_release
    monkeypatch.setattr(publishing, "WITHDRAWN_RELEASE", ("v1.2.4", withdrawn))
    restored = remote.advance("patch: Restore publishing")

    remote.publisher().publish(restored)
    assert git(repo, "rev-parse", "v1.2.5") == restored
    assert not remote.releases["v1.2.5"]["draft"]

    with pytest.raises(ValueError, match="was withdrawn"):
        remote.publisher().publish(withdrawn)
    assert git(repo, "rev-parse", "v1.2.4") == withdrawn
    assert remote.releases["v1.2.4"]["draft"]
    assert set(remote.uploaded) == set(publishing.distribution_names("1.2.5"))


def test_tag_collision_and_extra_target_tag_are_rejected(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    head = remote.advance()
    git(repo, "tag", "v1.2.4", "v1.2.3")
    with pytest.raises(ValueError):
        remote.publisher().publish(head)
    git(repo, "tag", "-d", "v1.2.4")
    git(repo, "tag", "v9.0.0", head)
    with pytest.raises(ValueError, match="another version"):
        remote.publisher().publish(head)


def test_target_must_be_main_ancestor(releases: tuple[Path, FakeRemote]) -> None:
    repo, remote = releases
    git(repo, "checkout", "-b", "other")
    write(repo, "src/other.py", "other")
    head = commit(repo, "patch: Other")
    with pytest.raises(ValueError, match="main"):
        remote.publisher().publish(head)


def test_malformed_or_bypassed_title_cannot_publish(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    head = remote.advance("Oops")
    with pytest.raises(ValueError, match="require"):
        remote.publisher().publish(head)


def test_reserved_tag_and_missing_draft_can_resume(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    head = remote.advance()
    git(repo, "tag", "v1.2.4", head)
    remote.publisher().publish(head)
    assert remote.builds == 1
    assert not remote.releases["v1.2.4"]["draft"]


def test_staged_bytes_are_verified_before_any_retry_upload(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    head = remote.advance()
    remote.fail = "publish"
    with pytest.raises(RuntimeError):
        remote.publisher().publish(head)
    name = publishing.distribution_names("1.2.4")[0]
    remote.files["v1.2.4", name] = b"corrupted"
    before = len(remote.calls)
    with pytest.raises(ValueError, match="verification"):
        remote.publisher().publish(head)
    assert not any(c[:2] == ["uv", "publish"] for c in remote.calls[before:])


def test_no_release_does_not_wait_for_an_unfinished_release(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    first = remote.advance()
    remote.fail = "publish"
    with pytest.raises(RuntimeError):
        remote.publisher().publish(first)
    docs = remote.advance("Explain the release", "README.md")
    before = remote.builds
    remote.publisher().publish(docs)
    assert remote.builds == before


def test_bootstrap_skips_legacy_history_and_publishes_modelglot(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    legacy = remote.advance("patch: Unpublished legacy change")
    head = modelglot_major(remote)

    with pytest.raises(ValueError, match=legacy):
        remote.publisher().publish(head)

    remote.publisher().publish(head, bootstrap_version="7.0.0")

    assert git(repo, "rev-parse", "v7.0.0") == head
    assert not remote.releases["v7.0.0"]["draft"]
    assert set(remote.uploaded) == set(publishing.distribution_names("7.0.0"))
    assert remote.note_requests[-1] == {"tag_name": "v7.0.0"}


@pytest.mark.parametrize("title", ["patch: ModelGlot", "minor: ModelGlot"])
def test_bootstrap_requires_a_major_release(
    releases: tuple[Path, FakeRemote], title: str
) -> None:
    _, remote = releases
    head = modelglot_major(remote, title)

    with pytest.raises(ValueError, match="requires a major release"):
        remote.publisher().publish(head, bootstrap_version="7.0.0")
    assert remote.builds == 0


def test_bootstrap_rejects_any_other_version(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    head = modelglot_major(remote)

    with pytest.raises(ValueError, match=r"must be 7\.0\.0"):
        remote.publisher().publish(head, bootstrap_version="7.0.1")
    assert remote.builds == 0


def test_bootstrap_requires_modelglot_packaging(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    write(
        repo,
        "pyproject.toml",
        '[project]\nname="other-package"\ndynamic=["version"]\n',
    )
    write(
        repo,
        "uv.lock",
        '[[package]]\nname="other-package"\nsource={editable="."}\n',
    )
    head = remote.advance("major: Incorrect package identity")

    with pytest.raises(ValueError, match="ModelGlot"):
        remote.publisher().publish(head, bootstrap_version="7.0.0")
    assert remote.builds == 0


def test_bootstrap_resumes_an_existing_matching_tag(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    head = modelglot_major(remote)
    git(repo, "tag", "v7.0.0", head)

    remote.publisher().publish(head, bootstrap_version="7.0.0")

    assert git(repo, "rev-parse", "v7.0.0") == head
    assert not remote.releases["v7.0.0"]["draft"]
    assert set(remote.uploaded) == set(publishing.distribution_names("7.0.0"))


def test_bootstrap_resumes_an_existing_matching_draft(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    head = modelglot_major(remote)
    git(repo, "tag", "v7.0.0", head)
    existing: Release = {
        "id": 2,
        "tag_name": "v7.0.0",
        "draft": True,
        "prerelease": False,
        "assets": [],
    }
    remote.releases["v7.0.0"] = existing

    remote.publisher().publish(head, bootstrap_version="7.0.0")

    assert not remote.releases["v7.0.0"]["draft"]
    assert set(remote.uploaded) == set(publishing.distribution_names("7.0.0"))


def test_bootstrap_rejects_a_release_without_a_matching_tag(
    releases: tuple[Path, FakeRemote],
) -> None:
    _, remote = releases
    head = modelglot_major(remote)
    existing: Release = {
        "id": 2,
        "tag_name": "v7.0.0",
        "draft": True,
        "prerelease": False,
        "assets": [],
    }
    remote.releases["v7.0.0"] = existing

    with pytest.raises(ValueError, match="no matching remote tag"):
        remote.publisher().publish(head, bootstrap_version="7.0.0")
    assert remote.builds == 0


def test_bootstrap_is_a_noop_for_a_published_matching_release(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    head = modelglot_major(remote)
    git(repo, "tag", "v7.0.0", head)
    existing: Release = {
        "id": 2,
        "tag_name": "v7.0.0",
        "draft": False,
        "prerelease": False,
        "assets": [],
    }
    remote.releases["v7.0.0"] = existing

    remote.publisher().publish(head, bootstrap_version="7.0.0")

    assert remote.builds == 0
    assert not remote.uploaded


def test_bootstrap_rejects_an_existing_tag_for_another_commit(
    releases: tuple[Path, FakeRemote],
) -> None:
    repo, remote = releases
    head = modelglot_major(remote)
    base = git(repo, "rev-parse", "HEAD^")
    git(repo, "tag", "v7.0.0", base)

    with pytest.raises(ValueError, match="different commit"):
        remote.publisher().publish(head, bootstrap_version="7.0.0")
    assert remote.builds == 0
