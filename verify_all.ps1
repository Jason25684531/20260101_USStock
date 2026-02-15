# Verify all core endpoints for USStock
Write-Host "=" -repeat 70 -ForegroundColor Cyan
Write-Host "USStock - Full Verification" -ForegroundColor Cyan
Write-Host "=" -repeat 70 -ForegroundColor Cyan
Write-Host ""

# Auth header
$pair = 'admin:admin123'
$token = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($pair))
$headers = @{Authorization = "Basic $token"}
$baseUrl = 'http://127.0.0.1:6688'

$totalTests = 0
$passedTests = 0

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = "Get",
        [hashtable]$Headers = $null,
        [scriptblock]$Validator = $null
    )

    $script:totalTests++
    Write-Host "[$script:totalTests] $Name..." -ForegroundColor Yellow -NoNewline

    try {
        $result = Invoke-RestMethod -Uri $Url -Method $Method -Headers $Headers -ErrorAction Stop
        if ($Validator) {
            $validationResult = & $Validator $result
            if (-not $validationResult) {
                throw "Validation failed"
            }
        }
        Write-Host " OK" -ForegroundColor Green
        $script:passedTests++
        return $result
    }
    catch {
        Write-Host " FAIL" -ForegroundColor Red
        Write-Host "   Error: $_" -ForegroundColor Red
        return $null
    }
}

Write-Host "Section 1: Health" -ForegroundColor Cyan
Write-Host "-" -repeat 70
Test-Endpoint -Name "Web /health" -Url "$baseUrl/health" -Validator { param($r) $r.status -eq 'healthy' }
Test-Endpoint -Name "LINE Webhook info" -Url "$baseUrl/webhook/info" -Validator { param($r) $r.channel_secret_configured -eq $true }
Test-Endpoint -Name "LINE Callback GET" -Url "$baseUrl/callback" -Validator { param($r) $r.status -eq 'ok' }

Write-Host ""
Write-Host "Section 2: Strategies" -ForegroundColor Cyan
Write-Host "-" -repeat 70
$strategies = Test-Endpoint -Name "Strategy list" -Url "$baseUrl/api/strategies" -Headers $headers -Validator { param($r) $r.Count -ge 1 }
if ($strategies) {
    Write-Host ("   Count: {0}" -f $strategies.Count) -ForegroundColor Gray
}

Write-Host ""
Write-Host "Section 3: Sectors" -ForegroundColor Cyan
Write-Host "-" -repeat 70
$sectors = Test-Endpoint -Name "Sector rankings" -Url "$baseUrl/api/sectors" -Headers $headers -Validator { param($r) $r.sectors.Count -ge 1 }
if ($sectors) {
    Write-Host ("   Sectors: {0}" -f $sectors.sectors.Count) -ForegroundColor Gray
}

Write-Host ""
Write-Host "Section 4: Macro" -ForegroundColor Cyan
Write-Host "-" -repeat 70
$macro = Test-Endpoint -Name "Macro regime" -Url "$baseUrl/api/macro" -Headers $headers -Validator { param($r) $r.regime.regime -ne $null }
if ($macro) {
    Write-Host ("   Regime: {0}" -f $macro.regime.regime) -ForegroundColor Gray
}

Write-Host ""
Write-Host "Section 5: Recommendations" -ForegroundColor Cyan
Write-Host "-" -repeat 70
$recommendations = Test-Endpoint -Name "Top 5" -Url "$baseUrl/api/recommendations?date=2026-02-14&limit=5" -Headers $headers -Validator { param($r) $r.recommendations.Count -ge 1 }
if ($recommendations) {
    Write-Host ("   Count: {0}" -f $recommendations.recommendations.Count) -ForegroundColor Gray
}

$dates = Test-Endpoint -Name "Recommendation dates" -Url "$baseUrl/api/recommendations/dates" -Headers $headers -Validator { param($r) $r.dates.Count -ge 1 }
if ($dates) {
    Write-Host ("   Dates: {0}" -f $dates.dates.Count) -ForegroundColor Gray
}

Write-Host ""
Write-Host "=" -repeat 70 -ForegroundColor Cyan
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "=" -repeat 70 -ForegroundColor Cyan
Write-Host ("Total: {0}" -f $totalTests) -ForegroundColor White
Write-Host ("Passed: {0}" -f $passedTests) -ForegroundColor Green
Write-Host ("Failed: {0}" -f ($totalTests - $passedTests)) -ForegroundColor Red
$successRate = if ($totalTests -gt 0) { [math]::Round(($passedTests / $totalTests) * 100, 1) } else { 0 }
Write-Host ("Success rate: {0}%" -f $successRate) -ForegroundColor White

