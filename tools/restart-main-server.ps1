param([switch]$VerifyOnly)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$python=Join-Path $root '.venv/Scripts/python.exe'
& $python -B -c "from importlib.metadata import version; assert version('waitress') == '3.0.2'"
if($LASTEXITCODE -ne 0){throw 'Approved Waitress dependency is missing; no process stopped.'}
$statePath=Join-Path $root 'instance/owner_requests_dev_server.json'
$processIds=@()
$listeners=@(Get-NetTCPConnection -State Listen | Where-Object LocalPort -EQ 5000)
if($listeners.Count){
    if($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1'){
        throw 'Expected one loopback listener on port 5000; nothing stopped.'
    }
    $listener=Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0].OwningProcess)"
    if(-not $listener){throw 'Port 5000 listener changed; nothing stopped.'}
    $launcher=$listener
    if($listener.ExecutablePath -ne $python){
        $launcher=Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.ParentProcessId)"
    }
    # Identify a manual Flask launch even when the old launcher's PID is stale.
    # Match the exact workspace interpreter and arguments before stopping it.
    $pythonPattern=[regex]::Escape($python)
    $wsgiPattern=[regex]::Escape((Join-Path $root 'tools/run_main_wsgi.py'))
    $signature='^"?'+$pythonPattern+'"?\s+(?:(?:-B|-u)\s+)*(?:-m flask --app app run(?: --host 127\.0\.0\.1 --port 5000)?|"?'+$wsgiPattern+'"?)\s*$'
    if(-not $launcher -or $launcher.ExecutablePath -ne $python -or
        $launcher.CommandLine -notmatch $signature -or $listener.CommandLine -notmatch $signature){
        throw 'Port 5000 is owned by an unverified process; nothing stopped.'
    }
    $processIds=@($listener.ProcessId,$launcher.ProcessId) | Select-Object -Unique
}
if($VerifyOnly){return}
New-Item -Path (Join-Path $root 'instance') -ItemType Directory -Force | Out-Null
foreach($processId in $processIds){
    if(Get-Process -Id $processId -ErrorAction SilentlyContinue){Stop-Process -Id $processId -Force}
}
$tag=[guid]::NewGuid().ToString('N')
$stdout=Join-Path $root ('instance/main-wsgi-'+$tag+'.out.log')
$stderr=Join-Path $root ('instance/main-wsgi-'+$tag+'.err.log')
$process=Start-Process -FilePath $python -ArgumentList @('-B','-u',(Join-Path $root 'tools/run_main_wsgi.py')) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
@{workspace=$root;port=5000;host='127.0.0.1';launcher_pid=$process.Id;entrypoint='tools/run_main_wsgi.py';stdout=$stdout;stderr=$stderr} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
$ready=$false
for($attempt=0;$attempt -lt 25;$attempt++){
    try{$response=Invoke-WebRequest -Uri 'http://127.0.0.1:5000/login' -UseBasicParsing -TimeoutSec 2;if($response.StatusCode -eq 200){$ready=$true;break}}catch{}
    Start-Sleep -Milliseconds 400
}
if(-not $ready){throw 'Main WSGI startup failed; inspect the recorded private stderr log.'}
Write-Output 'Existing main application is healthy on loopback port 5000 using Waitress; debug disabled.'
