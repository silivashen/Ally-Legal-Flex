# Compatibility entry point. New users can double-click Start-Ally.cmd.
$launcher = Join-Path $PSScriptRoot "Start-Ally.cmd"
& $launcher @args
exit $LASTEXITCODE
