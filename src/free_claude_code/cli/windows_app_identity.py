"""Windows application identity required for branded native toast notifications."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from free_claude_code.cli.desktop_assets import export_app_icon
from free_claude_code.config.paths import config_dir_path

APP_DISPLAY_NAME = "ModelGlot"
_SHORTCUT_FILE_NAME = "ModelGlot.lnk"
_SHORTCUT_TIMEOUT_SECONDS = 30.0
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_SHORTCUT_SCRIPT = r"""
param(
    [Parameter(Mandatory = $true)][string] $TargetPath,
    [Parameter(Mandatory = $true)][string] $IconPath,
    [Parameter(Mandatory = $true)][string] $AppUserModelId
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ModelGlotShortcutAppUserModelId
{
    private const uint CLSCTX_INPROC_SERVER = 1;
    private const ushort VT_LPWSTR = 31;

    private static readonly Guid ClsidShellLink = new Guid("00021401-0000-0000-C000-000000000046");
    private static readonly Guid IidShellLinkW = new Guid("000214F9-0000-0000-C000-000000000046");
    private static readonly Guid IidPersistFile = new Guid("0000010B-0000-0000-C000-000000000046");
    private static readonly Guid IidPropertyStore = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
    private static readonly Guid PkeyAppUserModelIdFormat = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
    private const uint PkeyAppUserModelIdProperty = 5;

    [DllImport("ole32.dll")]
    private static extern int CoCreateInstance(
        ref Guid classId, IntPtr outer, uint context, ref Guid interfaceId, out IntPtr instance);

    [ComImport]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW
    {
        [PreserveSig]
        int QueryInterface(ref Guid interfaceId, out IntPtr instance);

        [PreserveSig]
        uint AddRef();

        [PreserveSig]
        uint Release();
    }

    [ComImport]
    [Guid("0000010B-0000-0000-C000-000000000046")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPersistFile
    {
        [PreserveSig]
        int GetClassID(out Guid classId);

        [PreserveSig]
        int IsDirty();

        [PreserveSig]
        int Load([MarshalAs(UnmanagedType.LPWStr)] string fileName, uint mode);

        [PreserveSig]
        int Save([MarshalAs(UnmanagedType.LPWStr)] string fileName, [MarshalAs(UnmanagedType.Bool)] bool remember);

        [PreserveSig]
        int SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string fileName);

        [PreserveSig]
        int GetCurFile(IntPtr fileName, uint fileNameLength, out uint flags);
    }

    [ComImport]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore
    {
        [PreserveSig]
        int GetCount(out uint count);

        [PreserveSig]
        int GetAt(uint index, out PropertyKey key);

        [PreserveSig]
        int GetValue(ref PropertyKey key, out PropVariant value);

        [PreserveSig]
        int SetValue(ref PropertyKey key, ref PropVariant value);

        [PreserveSig]
        int Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct PropertyKey
    {
        public Guid FormatId;
        public uint PropertyId;
    }

    [StructLayout(LayoutKind.Explicit, Size = 24)]
    private struct PropVariant
    {
        [FieldOffset(0)] public ushort ValueType;
        [FieldOffset(8)] public IntPtr Value;
    }

    public static void SetAppUserModelId(string shortcutPath, string appUserModelId)
    {
        IntPtr shellLinkPointer = IntPtr.Zero;
        try
        {
            Guid classId = ClsidShellLink;
            Guid interfaceId = IidShellLinkW;
            Check(
                CoCreateInstance(ref classId, IntPtr.Zero, CLSCTX_INPROC_SERVER, ref interfaceId, out shellLinkPointer),
                "Could not create the Windows shell link");
            IShellLinkW shellLink = (IShellLinkW)Marshal.GetObjectForIUnknown(shellLinkPointer);
            IPersistFile persistFile = QueryInterface<IPersistFile>(shellLink, IidPersistFile);
            Check(persistFile.Load(shortcutPath, 0x42), "Could not load the shortcut '" + shortcutPath + "'");
            IPropertyStore propertyStore = QueryInterface<IPropertyStore>(shellLink, IidPropertyStore);
            PropertyKey key = new PropertyKey
            {
                FormatId = PkeyAppUserModelIdFormat,
                PropertyId = PkeyAppUserModelIdProperty
            };
            PropVariant value = new PropVariant();
            value.ValueType = VT_LPWSTR;
            value.Value = Marshal.StringToCoTaskMemUni(appUserModelId);
            try
            {
                Check(propertyStore.SetValue(ref key, ref value), "Could not set System.AppUserModel.ID on the shortcut '" + shortcutPath + "'");
                Check(propertyStore.Commit(), "Could not commit System.AppUserModel.ID on the shortcut '" + shortcutPath + "'");
            }
            finally
            {
                Marshal.FreeCoTaskMem(value.Value);
            }
            Check(persistFile.Save(shortcutPath, true), "Could not save the shortcut '" + shortcutPath + "'");
            Check(persistFile.SaveCompleted(shortcutPath), "Could not finish saving the shortcut '" + shortcutPath + "'");
        }
        finally
        {
            if (shellLinkPointer != IntPtr.Zero)
            {
                Marshal.Release(shellLinkPointer);
            }
        }
    }

    private static T QueryInterface<T>(IShellLinkW shellLink, Guid interfaceId)
    {
        IntPtr instance = IntPtr.Zero;
        Guid iid = interfaceId;
        Check(shellLink.QueryInterface(ref iid, out instance), "Could not query the shell link interface");
        try
        {
            return (T)Marshal.GetObjectForIUnknown(instance);
        }
        finally
        {
            Marshal.Release(instance);
        }
    }

    private static void Check(int result, string message)
    {
        if (result < 0)
        {
            throw new COMException(message + " (HRESULT 0x" + result.ToString("X8") + ").", result);
        }
    }
}
'@

$shortcutPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ModelGlot.lnk"
$shortcutDirectory = Split-Path -Parent $shortcutPath
New-Item -ItemType Directory -Force -Path $shortcutDirectory | Out-Null

$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
    $existing = $shell.CreateShortcut($shortcutPath)
    $existingTarget = [string] $existing.TargetPath
    if (-not [string]::IsNullOrWhiteSpace($existingTarget) -and
        -not $existingTarget.Equals($TargetPath, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Output "shortcut-owned-by-another-application"
        exit 2
    }
}

$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $TargetPath
$shortcut.WorkingDirectory = Split-Path -Parent $TargetPath
$shortcut.IconLocation = "$IconPath,0"
$shortcut.Description = "Run ModelGlot in the background"
$shortcut.Save()

[ModelGlotShortcutAppUserModelId]::SetAppUserModelId($shortcutPath, $AppUserModelId)
Write-Output $shortcutPath
exit 0
"""


def app_icon_paths() -> tuple[Path, Path]:
    """Return the exported PNG and ICO paths used by the Windows identity."""

    config_dir = config_dir_path()
    return config_dir / "app-icon.png", config_dir / "app-icon.ico"


def ensure_windows_app_identity(app_user_model_id: str) -> bool:
    """Register the identity Windows needs to show branded native toasts.

    Windows drops toasts from unpackaged apps unless the AppUserModelID is
    registered in the registry and exposed through a Start Menu shortcut that
    carries the same identity. The installer creates that shortcut, but the
    desktop shell repairs it at runtime so notifications keep working after
    updates, portable launches, or a removed shortcut.
    """

    png_path, ico_path = app_icon_paths()
    try:
        export_app_icon(png_path)
        export_app_icon(ico_path)
    except OSError:
        return False
    if not register_app_user_model_id(app_user_model_id, ico_path):
        return False
    return ensure_start_menu_shortcut(app_user_model_id, ico_path)


def register_app_user_model_id(app_user_model_id: str, icon_path: Path) -> bool:
    """Write the registry identity Windows resolves for native toasts."""

    import winreg

    key_path = rf"Software\Classes\AppUserModelId\{app_user_model_id}"
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_WRITE,
        ) as key:
            winreg.SetValueEx(
                key,
                "DisplayName",
                0,
                winreg.REG_SZ,
                APP_DISPLAY_NAME,
            )
            winreg.SetValueEx(
                key,
                "IconUri",
                0,
                winreg.REG_SZ,
                str(icon_path),
            )
            winreg.SetValueEx(
                key,
                "IconBackgroundColor",
                0,
                winreg.REG_SZ,
                "FF000000",
            )
    except OSError:
        return False
    return True


def ensure_start_menu_shortcut(app_user_model_id: str, icon_path: Path) -> bool:
    """Create or refresh the Start Menu shortcut carrying the app identity."""

    powershell = _powershell_executable()
    if powershell is None:
        return False
    target = desktop_launcher_path()
    with tempfile.TemporaryDirectory(prefix="modelglot-app-identity-") as temp_dir:
        script_path = Path(temp_dir) / "ensure_app_identity.ps1"
        script_path.write_text(_SHORTCUT_SCRIPT, encoding="utf-8")
        try:
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                    "-TargetPath",
                    str(target),
                    "-IconPath",
                    str(icon_path),
                    "-AppUserModelId",
                    app_user_model_id,
                ],
                capture_output=True,
                text=True,
                timeout=_SHORTCUT_TIMEOUT_SECONDS,
                check=False,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError, subprocess.SubprocessError:
            return False
    return result.returncode == 0


def desktop_launcher_path() -> Path:
    """Return the command that starts the ModelGlot desktop shell."""

    candidates = []
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None:
        candidates.append(argv0)
        candidates.append(argv0.with_name("modelglot-desktop.exe"))
    candidates.append(Path(sys.executable).with_name("modelglot-desktop.exe"))
    candidates.append(Path(sys.executable).with_name("modelglot-desktop"))
    for candidate in candidates:
        if candidate.exists() and candidate.name.lower().startswith(
            "modelglot-desktop"
        ):
            return candidate
    return Path(sys.executable)


def _powershell_executable() -> str | None:
    candidates = [
        shutil.which("powershell.exe"),
        shutil.which("pwsh.exe"),
        shutil.which("pwsh"),
        os.path.join(
            os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None
