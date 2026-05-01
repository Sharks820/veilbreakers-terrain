param(
    [string]$BlenderExe = "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    [string]$BlendPath = "output\scene_v3\VeilBreakers_Scene_v3.blend",
    [string]$RenderScript = "scripts\render_closeups_v3.py",
    [int]$BatchSize = 4,
    [int]$StartBatch = 1,
    [int]$Threads = 4,
    [int]$Samples = 96,
    [int]$CooldownSeconds = 20,
    [string]$CyclesDeviceType = "OPTIX",
    [switch]$AllowCyclesCpuDevice
)

$ErrorActionPreference = "Stop"

$labels = @(
    "01_tile_overview",
    "02_hero_establishing",
    "03_cave_portal",
    "04_cave_interior_to_exit",
    "05_waterfall_closeup",
    "06_river_bank_entry",
    "07_bridge_waterline",
    "08_bridge_approach_path",
    "09_large_water_bank_exit",
    "10_large_water_panorama",
    "11_large_water_shoreline",
    "12_cliff_face",
    "13_mountain_peak_lookdown",
    "14_forest_bridge_side"
)

if ($BatchSize -lt 1) {
    throw "BatchSize must be >= 1"
}
if ($StartBatch -lt 1) {
    throw "StartBatch must be >= 1"
}
if ($Threads -lt 1) {
    throw "Threads must be >= 1"
}
if (-not (Test-Path -LiteralPath $BlenderExe)) {
    throw "Blender executable not found: $BlenderExe"
}
if (-not (Test-Path -LiteralPath $BlendPath)) {
    throw "Blend file not found: $BlendPath"
}
if (-not (Test-Path -LiteralPath $RenderScript)) {
    throw "Render script not found: $RenderScript"
}

$logDir = Join-Path (Get-Location) "output\scene_v3\closeups\batched_render_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$previousLabels = $env:VB_CLOSEUP_LABELS
$previousSamples = $env:VB_CLOSEUP_SAMPLES
$previousCpuDevice = $env:VB_DISABLE_CYCLES_CPU_DEVICE
$previousDeviceType = $env:VB_CYCLES_DEVICE_TYPE

try {
    for ($start = 0; $start -lt $labels.Count; $start += $BatchSize) {
        $end = [Math]::Min($start + $BatchSize - 1, $labels.Count - 1)
        $batch = $labels[$start..$end]
        $batchNumber = [int]($start / $BatchSize) + 1
        if ($batchNumber -lt $StartBatch) {
            Write-Host "[closeup-batch] skipping batch $batchNumber because StartBatch=$StartBatch"
            continue
        }
        $batchSlug = "{0:D2}_{1}" -f $batchNumber, ($batch -join "__")
        $stdout = Join-Path $logDir "$batchSlug.stdout.log"
        $stderr = Join-Path $logDir "$batchSlug.stderr.log"

        $env:VB_CLOSEUP_LABELS = $batch -join ","
        $env:VB_CLOSEUP_SAMPLES = [string]$Samples
        $env:VB_DISABLE_CYCLES_CPU_DEVICE = if ($AllowCyclesCpuDevice) { "0" } else { "1" }
        $env:VB_CYCLES_DEVICE_TYPE = $CyclesDeviceType

        Write-Host "[closeup-batch] batch $batchNumber labels=$($env:VB_CLOSEUP_LABELS) threads=$Threads samples=$Samples cpu_device_disabled=$($env:VB_DISABLE_CYCLES_CPU_DEVICE)"

        $args = @(
            "--factory-startup",
            "--background", (Resolve-Path -LiteralPath $BlendPath).Path,
            "--threads", [string]$Threads,
            "--python", (Resolve-Path -LiteralPath $RenderScript).Path
        )
        $process = Start-Process `
            -FilePath $BlenderExe `
            -ArgumentList $args `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -WindowStyle Hidden `
            -PassThru

        try {
            $process.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
        } catch {
            Write-Warning "Could not set Blender process priority: $($_.Exception.Message)"
        }

        $process.WaitForExit()
        $process.Refresh()
        $exitCode = $process.ExitCode
        $stdoutText = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw } else { "" }
        $completedFromLog = $stdoutText -match "\[closeup\] DONE .*\/.* shots rendered"
        if ($null -eq $exitCode -and $completedFromLog) {
            $exitCode = 0
        }
        if ($exitCode -ne 0) {
            throw "Blender closeup batch $batchNumber failed with exit code $exitCode. See $stdout and $stderr"
        }

        Write-Host "[closeup-batch] batch $batchNumber complete"
        if ($CooldownSeconds -gt 0 -and $end -lt ($labels.Count - 1)) {
            Write-Host "[closeup-batch] cooling down for $CooldownSeconds seconds"
            Start-Sleep -Seconds $CooldownSeconds
        }
    }
} finally {
    if ($null -eq $previousLabels) { Remove-Item Env:VB_CLOSEUP_LABELS -ErrorAction SilentlyContinue } else { $env:VB_CLOSEUP_LABELS = $previousLabels }
    if ($null -eq $previousSamples) { Remove-Item Env:VB_CLOSEUP_SAMPLES -ErrorAction SilentlyContinue } else { $env:VB_CLOSEUP_SAMPLES = $previousSamples }
    if ($null -eq $previousCpuDevice) { Remove-Item Env:VB_DISABLE_CYCLES_CPU_DEVICE -ErrorAction SilentlyContinue } else { $env:VB_DISABLE_CYCLES_CPU_DEVICE = $previousCpuDevice }
    if ($null -eq $previousDeviceType) { Remove-Item Env:VB_CYCLES_DEVICE_TYPE -ErrorAction SilentlyContinue } else { $env:VB_CYCLES_DEVICE_TYPE = $previousDeviceType }
}

Write-Host "[closeup-batch] all closeup batches complete"
