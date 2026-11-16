@echo off
setlocal
rem The installer replaces this file, so cmd must parse the whole block first.
(
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $env:FCC_INSTALL_REF = 'custom/main'; & ([scriptblock]::Create((Invoke-RestMethod 'https://raw.githubusercontent.com/amedeo82/free-claude-code/custom/main/scripts/install.ps1'))) -Update" %*
  call exit /b %%errorlevel%%
)
