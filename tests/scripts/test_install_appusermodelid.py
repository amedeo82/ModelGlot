import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "scripts/install.ps1"
INSTALLER_TEXT = INSTALLER.read_text(encoding="utf-8")


def _function_body(declaration: str) -> str:
    start = INSTALLER_TEXT.index(declaration)
    brace_start = INSTALLER_TEXT.index("{", start)
    depth = 0
    for index, char in enumerate(INSTALLER_TEXT[brace_start:], start=brace_start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return INSTALLER_TEXT[brace_start + 1 : index]
    raise AssertionError(f"Unclosed function body for {declaration}")


def _csharp_source() -> str:
    match = re.search(
        r"Add-Type -TypeDefinition @'\n(?P<source>.*?)\n'@", INSTALLER_TEXT, re.DOTALL
    )
    assert match is not None
    return match.group("source")


def test_installer_defines_stable_appusermodelid() -> None:
    assert '$FccAppUserModelId = "io.github.alishahryar1.free-claude-code"' in (
        INSTALLER_TEXT
    )
    assert "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3" in INSTALLER_TEXT
    assert "PkeyAppUserModelIdProperty = 5" in INSTALLER_TEXT
    assert "VT_LPWSTR = 31" in INSTALLER_TEXT


def test_com_helper_uses_persistfile_and_property_store() -> None:
    source = _csharp_source()

    assert "private interface IPersistFile" in source
    assert "private interface IPropertyStore" in source
    assert "persistFile.Load(shortcutPath, 0x42)" in source
    assert "QueryInterface<IPropertyStore>(shellLink, IidPropertyStore)" in source
    assert "propertyStore.SetValue(ref key, ref value)" in source
    assert "propertyStore.Commit()" in source
    assert "persistFile.Save(shortcutPath, true)" in source
    assert "persistFile.SaveCompleted(shortcutPath)" in source
    assert source.index("propertyStore.Commit()") < source.index(
        "persistFile.Save(shortcutPath, true)"
    )


def test_both_shortcuts_receive_appusermodelid_after_save() -> None:
    body = _function_body("function Install-FccDesktopShortcuts")

    assert 'Join-Path $env:USERPROFILE "Desktop\\Free Claude Code.lnk"' in body
    assert (
        'Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\Free Claude Code.lnk"'
        in body
    )
    assert "$shortcutPaths = @($desktopShortcutPath, $startMenuShortcutPath)" in body
    assert "$shortcut.Save()" in body
    assert "Set-ShortcutAppUserModelId" in body
    assert body.index("$shortcut.Save()") < body.index("Set-ShortcutAppUserModelId")


def test_start_menu_identity_failure_is_explicit_and_desktop_is_best_effort() -> None:
    body = _function_body("function Install-FccDesktopShortcuts")

    catch_index = body.index("catch {")
    required_index = body.index("if ($shortcutPath -eq $startMenuShortcutPath)")
    throw_index = body.index('throw "Failed to set System.AppUserModel.ID', catch_index)
    warning_index = body.index("Write-Warning", catch_index)
    assert catch_index < required_index < throw_index < warning_index


@pytest.mark.skipif(os.name != "nt", reason="Windows shell links are required")
def test_com_helper_sets_appusermodelid_idempotently(tmp_path: Path) -> None:
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell is not available")

    shortcut_path = tmp_path / "Free Claude Code.lnk"
    app_user_model_id = "io.github.alishahryar1.free-claude-code"
    script_path = tmp_path / "set-aumid.ps1"
    script_path.write_text(
        f"""$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @'
{_csharp_source()}
'@
$shortcutPath = "{shortcut_path}"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\\System32\\notepad.exe"
$shortcut.Save()
[FccShortcutAppUserModelId]::SetAppUserModelId($shortcutPath, "{app_user_model_id}")
[FccShortcutAppUserModelId]::SetAppUserModelId($shortcutPath, "{app_user_model_id}")
$application = New-Object -ComObject Shell.Application
$folder = $application.NameSpace((Split-Path -Parent $shortcutPath))
$item = $folder.ParseName((Split-Path -Leaf $shortcutPath))
$actual = $item.ExtendedProperty("System.AppUserModel.ID")
if ($actual -ne "{app_user_model_id}") {{
    throw "Expected '{app_user_model_id}', found '$actual'"
}}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
