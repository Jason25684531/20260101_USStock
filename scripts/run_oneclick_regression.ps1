param(
    [string]$BaseUrl = 'http://127.0.0.1:6688',
    [string]$AuthUser = 'admin',
    [string]$AuthPassword = 'admin123',
    [string]$OutputDir = 'data/reports'
)

$ErrorActionPreference = 'Stop'

function Get-LineChannelSecret {
    $secretFile = '.secrets/line_channel_secret.txt'
    if (Test-Path $secretFile) {
        $secret = (Get-Content $secretFile -Raw).Trim()
        if ($secret) { return $secret }
    }

    if ($env:LINE_CHANNEL_SECRET) {
        return $env:LINE_CHANNEL_SECRET.Trim()
    }

    if (Test-Path '.env') {
        $line = Get-Content '.env' | Where-Object { $_ -match '^\s*LINE_CHANNEL_SECRET\s*=' } | Select-Object -First 1
        if ($line) {
            $value = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
            if ($value) { return $value }
        }
    }

    throw 'LINE_CHANNEL_SECRET not found (.secrets/line_channel_secret.txt, environment variable, or .env).'
}

function New-Signature {
    param(
        [string]$Secret,
        [string]$Body
    )
    $hmac = New-Object System.Security.Cryptography.HMACSHA256
    $hmac.Key = [Text.Encoding]::UTF8.GetBytes($Secret)
    $hash = $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($Body))
    return [Convert]::ToBase64String($hash)
}

function Invoke-Test {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [scriptblock]$Validator
    )

    $start = Get-Date
    try {
        $result = & $Action
        $ok = & $Validator $result
        [PSCustomObject]@{
            name = $Name
            passed = [bool]$ok
            duration_ms = [math]::Round(((Get-Date) - $start).TotalMilliseconds, 2)
            error = if ($ok) { $null } else { 'Validation failed' }
            details = $result
        }
    }
    catch {
        [PSCustomObject]@{
            name = $Name
            passed = $false
            duration_ms = [math]::Round(((Get-Date) - $start).TotalMilliseconds, 2)
            error = $_.Exception.Message
            details = $null
        }
    }
}

Write-Host '=== One-Click Regression ===' -ForegroundColor Cyan
Write-Host "Base URL: $BaseUrl"

$pair = "$AuthUser`:$AuthPassword"
$token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$authHeaders = @{ Authorization = "Basic $token" }

$secret = Get-LineChannelSecret

$tests = @()

# 1) Health
$tests += Invoke-Test -Name 'Health /health' -Action {
    Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get
} -Validator {
    param($r)
    $r.status -eq 'healthy' -and $r.database -eq 'connected'
}

# 2) Core APIs
$tests += Invoke-Test -Name 'API /api/recommendations?limit=5' -Action {
    Invoke-RestMethod -Uri "$BaseUrl/api/recommendations?limit=5" -Method Get -Headers $authHeaders
} -Validator {
    param($r)
    $null -ne $r.recommendations -and $r.recommendations.Count -ge 1
}

$tests += Invoke-Test -Name 'API /api/macro' -Action {
    Invoke-RestMethod -Uri "$BaseUrl/api/macro" -Method Get -Headers $authHeaders
} -Validator {
    param($r)
    $null -ne $r.regime -and $null -ne $r.indicators
}

$tests += Invoke-Test -Name 'API /api/sectors' -Action {
    Invoke-RestMethod -Uri "$BaseUrl/api/sectors" -Method Get -Headers $authHeaders
} -Validator {
    param($r)
    $null -ne $r.sectors -and $r.sectors.Count -ge 1
}

# 3) Signed webhook command checks (no replyToken to avoid external reply dependency)
$commandSamples = @('/help', 'Top5', '/market', '/sector', '/status')
foreach ($cmd in $commandSamples) {
    $tests += Invoke-Test -Name "Webhook signed command: $cmd" -Action {
        $payload = @{
            events = @(
                @{
                    type = 'message'
                    message = @{ type = 'text'; id = '100001'; text = $cmd }
                    source = @{ type = 'user'; userId = 'Uregression-test' }
                    timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
                }
            )
        } | ConvertTo-Json -Depth 10 -Compress

        $signature = New-Signature -Secret $secret -Body $payload
        $headers = @{ 'X-Line-Signature' = $signature; 'Content-Type' = 'application/json' }
        Invoke-RestMethod -Uri "$BaseUrl/callback" -Method Post -Headers $headers -Body $payload
    } -Validator {
        param($r)
        $r.status -eq 'ok'
    }
}

$passed = ($tests | Where-Object { $_.passed }).Count
$total = $tests.Count
$failed = $total - $passed

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if (-not (Test-Path $OutputDir)) {
    New-Item -Path $OutputDir -ItemType Directory -Force | Out-Null
}
$reportPath = Join-Path $OutputDir "regression_$timestamp.json"

$report = [PSCustomObject]@{
    run_at = (Get-Date).ToString('s')
    base_url = $BaseUrl
    summary = [PSCustomObject]@{
        total = $total
        passed = $passed
        failed = $failed
        pass_rate = if ($total -gt 0) { [math]::Round(($passed * 100.0 / $total), 1) } else { 0 }
    }
    tests = $tests
}

$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host "Report: $reportPath" -ForegroundColor Green
Write-Host "Passed: $passed / $total" -ForegroundColor $(if ($failed -eq 0) { 'Green' } else { 'Yellow' })

if ($failed -gt 0) {
    Write-Host 'Failed tests:' -ForegroundColor Red
    $tests | Where-Object { -not $_.passed } | ForEach-Object {
        Write-Host " - $($_.name): $($_.error)" -ForegroundColor Red
    }
    exit 1
}

exit 0
