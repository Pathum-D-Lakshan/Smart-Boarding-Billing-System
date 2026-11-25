$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$path=Join-Path $root 'instance/mobile_https_session.json'
$state=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if($state.workspace -ne $root){throw 'Unexpected gateway workspace.'}
$gateway=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.gateway_pid)"
if(-not $gateway -or $gateway.ExecutablePath -ne (Join-Path $root '.venv/Scripts/python.exe') -or $gateway.CommandLine -notmatch 'SmartBoardingSystem.*mobile_upload_gateway\.py.*5002'){throw 'Gateway identity changed; no process stopped.'}
$children=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($gateway.ProcessId)" | Where-Object {$_.CommandLine -match 'mobile_upload_gateway\.py.*5002'})
foreach($child in $children){Stop-Process -Id $child.ProcessId -Force}
if(Get-Process -Id $gateway.ProcessId -ErrorAction SilentlyContinue){Stop-Process -Id $gateway.ProcessId -Force -ErrorAction SilentlyContinue}
$process=Start-Process -FilePath (Join-Path $root '.venv/Scripts/python.exe') -ArgumentList @('-B','-u',(Join-Path $root 'tools/mobile_upload_gateway.py'),'--port','5002') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $state.gateway_out -RedirectStandardError $state.gateway_err -PassThru
$state.gateway_pid=$process.Id;$state | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding UTF8
Write-Output 'Verified upload gateway restarted; same HTTPS tunnel and main app retained.'
