param([switch]$Approved,[ValidateSet('Auto','Cloudflare','Pinggy')][string]$Provider='Auto')
$ErrorActionPreference='Stop'
if(-not $Approved){throw 'This starts a public upload-only HTTPS tunnel. Explicit user approval is required.'}
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
if($Provider -eq 'Pinggy' -or ($Provider -eq 'Auto' -and (Test-Path -LiteralPath 'instance/mobile_https_session.json') -and ((Get-Content -LiteralPath 'instance/mobile_https_session.json' -Raw | ConvertFrom-Json).provider -eq 'pinggy'))){
    & (Join-Path $PSScriptRoot 'start-mobile-upload-https-pinggy.ps1') -Approved
    exit
}
$python=Join-Path $root '.venv/Scripts/python.exe'
$tool=Get-Content -LiteralPath 'instance/mobile_https_tool.json' -Raw | ConvertFrom-Json
if(-not $tool.official_digest_verified -or (Get-FileHash -LiteralPath $tool.binary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $tool.sha256){throw 'The approved official tool hash is not verified.'}
$statePath=Join-Path $root 'instance/mobile_https_session.json'
function Complete-MobileSession($state){
    $url=$null;$connected=$false
    for($attempt=0;$attempt -lt 55;$attempt++){
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.tunnel_pid)"
        if(-not $process -or $process.ExecutablePath -ne $tool.binary -or $process.CommandLine -notmatch 'http://127\.0\.0\.1:5002'){throw 'The recorded tunnel process is unavailable or changed.'}
        $log=if(Test-Path -LiteralPath $state.tunnel_err){[string](Get-Content -LiteralPath $state.tunnel_err -Raw)}else{''}
        $match=[regex]::Match($log,'https://[a-z0-9-]+\.trycloudflare\.com')
        if($match.Success){$url=$match.Value;$state.public_url=$url}
        if($url -and $log -match 'Registered tunnel connection'){$connected=$true;break}
        if($log -match 'hard_fail=true' -and $log -notmatch 'Registered tunnel connection'){
            $state.phase='network_blocked';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
            throw 'Cloudflare outbound port 7844 is blocked/unreachable. Switch to an allowed network, then rerun this same command to resume; no second tunnel is needed.'
        }
        Start-Sleep -Milliseconds 800
    }
    if(-not $connected){$state.phase='waiting_for_network';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8;throw 'Tunnel address issued but edge connectivity is not ready. No app HTTPS setting was activated.'}
    $state.phase='edge_connected';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    & $python -B (Join-Path $root 'tools/mobile_https_config.py') activate $url
    if($LASTEXITCODE -ne 0){throw 'Could not save the approved mobile HTTPS configuration.'}
    & (Join-Path $root 'tools/restart-main-server.ps1')
    $publicReady=$false
    for($attempt=0;$attempt -lt 10;$attempt++){
        try{$response=Invoke-WebRequest -Uri ($url+'/mobile/payment-slip') -UseBasicParsing -TimeoutSec 8;if($response.StatusCode -eq 200){$publicReady=$true;break}}catch{}
        Start-Sleep -Milliseconds 500
    }
    if(-not $publicReady){$state.phase='public_probe_failed';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8;throw 'Public upload did not return HTTP 200. Keep this setup under review; do not claim the QR is reachable.'}
    foreach($path in @('/login','/owner/payments','/student/payments','/.env','/payments/1/slip')){
        $status=0;try{$r=Invoke-WebRequest -Uri ($url+$path) -UseBasicParsing -TimeoutSec 5;$status=[int]$r.StatusCode}catch{if($_.Exception.Response){$status=[int]$_.Exception.Response.StatusCode}}
        if($status -ne 404){throw ('Public path isolation failed for '+$path)}
    }
    $state.phase='configured';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-Output ('Upload-only HTTPS origin: '+$url)
    Write-Output 'Public upload HTTP 200; private portal paths HTTP 404. Generate a fresh QR in Student My Payments.'
}
if(Test-Path -LiteralPath $statePath){
    $old=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if($old.workspace -eq $root -and $old.tunnel_pid){
        $running=Get-CimInstance Win32_Process -Filter "ProcessId=$($old.tunnel_pid)"
        if($running -and $running.ExecutablePath -eq $tool.binary -and $running.CommandLine -match 'http://127\.0\.0\.1:5002'){Complete-MobileSession $old;exit 0}
    }
}
if(Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue){throw 'Port 5002 is occupied. Inspect it before starting another gateway.'}
$tag=[guid]::NewGuid().ToString('N')
$gatewayOut=Join-Path $root ('instance/mobile-gateway-'+$tag+'.out.log');$gatewayErr=Join-Path $root ('instance/mobile-gateway-'+$tag+'.err.log')
$tunnelOut=Join-Path $root ('instance/mobile-tunnel-'+$tag+'.out.log');$tunnelErr=Join-Path $root ('instance/mobile-tunnel-'+$tag+'.err.log')
$gateway=Start-Process -FilePath $python -ArgumentList @('-B','-u',(Join-Path $root 'tools/mobile_upload_gateway.py'),'--port','5002') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $gatewayOut -RedirectStandardError $gatewayErr -PassThru
$state=@{workspace=$root;gateway_pid=$gateway.Id;gateway_out=$gatewayOut;gateway_err=$gatewayErr;tool_binary=$tool.binary;tunnel_pid=$null;tunnel_out=$tunnelOut;tunnel_err=$tunnelErr;public_url=$null;phase='gateway_started';started_utc=[DateTime]::UtcNow.ToString('o')}
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
$ready=$false
for($attempt=0;$attempt -lt 20;$attempt++){
    try{Invoke-WebRequest -Uri 'http://127.0.0.1:5002/login' -UseBasicParsing -TimeoutSec 2 | Out-Null}catch{if($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404){$ready=$true;break}}
    Start-Sleep -Milliseconds 300
}
if(-not $ready){throw 'Local upload-only gateway did not become ready. Inspect its private logs.'}
$tunnel=Start-Process -FilePath $tool.binary -ArgumentList @('tunnel','--no-autoupdate','--url','http://127.0.0.1:5002','--protocol','http2','--metrics','127.0.0.1:0','--management-diagnostics=false','--loglevel','info') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelErr -PassThru
$state.tunnel_pid=$tunnel.Id;$state.phase='tunnel_starting';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Complete-MobileSession $state
