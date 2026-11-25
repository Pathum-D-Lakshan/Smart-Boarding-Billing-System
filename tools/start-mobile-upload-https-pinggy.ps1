param([switch]$Approved)
$ErrorActionPreference='Stop'
if(-not $Approved){throw 'Explicit approval for a limited public upload tunnel is required.'}
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$statePath=Join-Path $root 'instance/mobile_https_session.json'
if(-not(Test-Path -LiteralPath $statePath)){throw 'Start the local upload gateway first.'}
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if($state.workspace -ne $root){throw 'Unexpected workspace metadata.'}
$restartMain=Join-Path $root 'tools/restart-main-server.ps1'
& $restartMain -VerifyOnly
$ssh=(Get-Command ssh).Source
$reuse=$false
if($state.tunnel_pid){
    $old=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.tunnel_pid)"
    if($old -and $state.provider -eq 'pinggy' -and $old.ExecutablePath -eq $ssh -and $old.CommandLine -match 'http@free\.pinggy\.io' -and $old.CommandLine -match '0:127\.0\.0\.1:5002'){
        if($old.CreationDate.AddHours(1) -gt (Get-Date)){$reuse=$true}
        else{Stop-Process -Id $old.ProcessId -Force}
    }
    elseif($old -and $old.ExecutablePath -eq $state.tool_binary -and $old.CommandLine -match 'http://127\.0\.0\.1:5002'){
        Copy-Item -LiteralPath $statePath -Destination (Join-Path $root 'instance/mobile_https_cloudflare_attempt.json') -Force
        Stop-Process -Id $old.ProcessId -Force
    }elseif($old){throw 'Recorded tunnel PID belongs to a different process; nothing stopped.'}
}
$gateway=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.gateway_pid)"
if(-not $gateway){
    if(Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue){throw 'Gateway port is occupied by an unverified process.'}
    $tag=[guid]::NewGuid().ToString('N');$state.gateway_out=Join-Path $root ('instance/mobile-gateway-'+$tag+'.out.log');$state.gateway_err=Join-Path $root ('instance/mobile-gateway-'+$tag+'.err.log')
    $gateway=Start-Process -FilePath (Join-Path $root '.venv/Scripts/python.exe') -ArgumentList @('-B','-u',(Join-Path $root 'tools/mobile_upload_gateway.py'),'--port','5002') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $state.gateway_out -RedirectStandardError $state.gateway_err -PassThru
    $state.gateway_pid=$gateway.Id
}elseif($gateway.CommandLine -notmatch 'SmartBoardingSystem.*mobile_upload_gateway\.py.*5002'){throw 'Recorded local gateway process is not verified.'}
$gatewayReady=$false
for($attempt=0;$attempt -lt 20;$attempt++){
    $listener=Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue
    if($listener){
        $serving=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if($serving -and ($serving.ProcessId -eq $state.gateway_pid -or $serving.ParentProcessId -eq $state.gateway_pid) -and
            $serving.CommandLine -match 'SmartBoardingSystem.*mobile_upload_gateway\.py.*5002'){$gatewayReady=$true;break}
        throw 'Port 5002 listener is not the upload gateway.'
    }
    Start-Sleep -Milliseconds 300
}
if(-not $gatewayReady){throw 'Local upload gateway did not become ready.'}
if(-not $reuse){
    $tag=[guid]::NewGuid().ToString('N')
    $state.tunnel_out=Join-Path $root ('instance/mobile-pinggy-'+$tag+'.out.log')
    $state.tunnel_err=Join-Path $root ('instance/mobile-pinggy-'+$tag+'.err.log')
    $known=(Join-Path $root 'instance/pinggy_known_hosts').Replace('\','/')
    $identity=Join-Path $root 'instance/mobile_tunnel_ed25519'
    if(-not(Test-Path -LiteralPath $identity)){throw 'Dedicated local tunnel SSH identity is missing.'}
    $arguments=@('-T','-p','443','-i',$identity,'-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o',('UserKnownHostsFile='+$known),'-o','ForwardAgent=no','-o','IdentityAgent=none','-o','IdentitiesOnly=yes','-o','PubkeyAuthentication=yes','-o','PasswordAuthentication=no','-o','PreferredAuthentications=publickey','-o','ConnectTimeout=12','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3','-R','0:127.0.0.1:5002','http@free.pinggy.io','x:https')
    $process=Start-Process -FilePath $ssh -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $state.tunnel_out -RedirectStandardError $state.tunnel_err -PassThru
    $state.tunnel_pid=$process.Id;$state.public_url=$null;$state.phase='tunnel_starting'
    $state | Add-Member -NotePropertyName provider -NotePropertyValue 'pinggy' -Force
    $state | Add-Member -NotePropertyName tunnel_binary -NotePropertyValue $ssh -Force
    $state | Add-Member -NotePropertyName tunnel_started_utc -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}
$publicUrl=$null
for($attempt=0;$attempt -lt 40;$attempt++){
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($state.tunnel_pid)"
    if(-not $process){throw 'SSH HTTPS tunnel exited; inspect its private startup log.'}
    $output=''
    foreach($file in @($state.tunnel_out,$state.tunnel_err)){if(Test-Path -LiteralPath $file){$output += [string](Get-Content -LiteralPath $file -Raw)}}
    $match=[regex]::Match($output,'https://[a-z0-9-]+\.run\.pinggy-free\.link')
    if($match.Success){$publicUrl=$match.Value;break}
    Start-Sleep -Milliseconds 700
}
if(-not $publicUrl){throw 'No HTTPS origin was issued by the SSH tunnel.'}
$state.public_url=$publicUrl;$state.phase='url_issued';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
$python=Join-Path $root '.venv/Scripts/python.exe'
& $python -B (Join-Path $root 'tools/mobile_https_config.py') activate $publicUrl
if($LASTEXITCODE -ne 0){throw 'Could not save the approved mobile origin.'}
& $restartMain
$probeHeaders=@{'User-Agent'='SmartBoarding-HTTPS-Check';'X-Pinggy-No-Screen'='1'}
try{$response=Invoke-WebRequest -Uri ($publicUrl+'/mobile/payment-slip') -Headers $probeHeaders -UseBasicParsing -TimeoutSec 12}catch{throw 'Public upload HTTP probe failed; inspect the origin and connectivity.'}
if($response.StatusCode -ne 200 -or $response.Content -notmatch 'slip-live-camera'){throw 'Public upload page is not confirmed; do not claim readiness.'}
& $python -B -c 'import sys; from mobile_upload_health import require_available; require_available(sys.argv[1])' $publicUrl
if($LASTEXITCODE -ne 0){throw 'The public upload page does not match the configured HTTPS origin.'}
foreach($path in @('/login','/owner/payments','/student/payments','/.env','/payments/1/slip')){
    $status=0;try{$r=Invoke-WebRequest -Uri ($publicUrl+$path) -Headers $probeHeaders -UseBasicParsing -TimeoutSec 8;$status=[int]$r.StatusCode}catch{if($_.Exception.Response){$status=[int]$_.Exception.Response.StatusCode}}
    if($status -ne 404){throw ('Public isolation check failed: '+$path)}
}
$state.phase='configured';$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Output ('Working upload-only HTTPS origin: '+$publicUrl)
Write-Output 'Public upload HTTP 200; private paths HTTP 404. Create a fresh QR in Student My Payments.'
