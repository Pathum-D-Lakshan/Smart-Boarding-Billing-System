$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$statePath=Join-Path $root 'instance/mobile_https_session.json'
if(-not(Test-Path -LiteralPath $statePath)){Write-Output 'No recorded mobile tunnel session.';exit}
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if($state.workspace -ne $root){throw 'Unexpected tunnel workspace; nothing stopped.'}
if($state.tunnel_pid){
    $tunnel=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.tunnel_pid)"
    if($tunnel){
        $expected=if($state.provider -eq 'pinggy'){$state.tunnel_binary}else{$state.tool_binary}
        if($tunnel.ExecutablePath -ne $expected -or $tunnel.CommandLine -notmatch '5002'){throw 'Recorded tunnel identity changed; nothing stopped.'}
        Stop-Process -Id $tunnel.ProcessId -Force
    }
}
if($state.gateway_pid){
    $gateway=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.gateway_pid)"
    if($gateway){
        if($gateway.ExecutablePath -ne (Join-Path $root '.venv/Scripts/python.exe') -or $gateway.CommandLine -notmatch 'SmartBoardingSystem.*mobile_upload_gateway\.py.*5002'){throw 'Gateway identity changed; inspect before stopping.'}
        $children=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($gateway.ProcessId)" | Where-Object {$_.CommandLine -match 'SmartBoardingSystem.*mobile_upload_gateway\.py.*5002'})
        foreach($child in $children){Stop-Process -Id $child.ProcessId -Force}
        if(Get-Process -Id $gateway.ProcessId -ErrorAction SilentlyContinue){Stop-Process -Id $gateway.ProcessId -Force -ErrorAction SilentlyContinue}
    }
}
if(Test-Path -LiteralPath 'instance/mobile_https_previous_config.json'){
    & (Join-Path $root '.venv/Scripts/python.exe') -B (Join-Path $root 'tools/mobile_https_config.py') restore
    if($LASTEXITCODE -ne 0){throw 'Could not restore previous mobile settings.'}
    & (Join-Path $root 'tools/restart-main-server.ps1')
}
$state.phase='stopped';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output 'Recorded public tunnel/gateway stopped; main portals remain local and previous mobile settings restored.'
