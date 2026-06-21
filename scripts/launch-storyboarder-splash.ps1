<#
.SYNOPSIS
    Lightweight native starter splash for Storyboarder.

.DESCRIPTION
    Appears immediately when the user launches Storyboarder, before Python
    has a chance to import FastAPI, Pillow, or other heavy modules.

    Polls for:
      - %TEMP%\storyboarder-launch-<Token>.status  (phase string from launcher)
      - %TEMP%\storyboarder-launch-<Token>.ready   (primary close signal)
      - %TEMP%\storyboarder-launch-<Token>.failed  (fatal launcher error)

    On .failed: switches to an error state showing the status message and a
    Close button; the progress bar stops.
    On .ready:  closes immediately.
    After 120s: closes as a last resort.

.PARAMETER Token
    Unique per-launch UUID from the launcher batch file.
    If absent or invalid, splash falls back to a 120-second timeout.
#>
param(
    [string]$Token = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

# --- Token validation (restrict filesystem paths to known pattern) ---
$HasToken = $Token.Length -gt 0 -and ($Token -match '^[a-zA-Z0-9_-]{1,64}$')
$ReadyMarkerPath  = if ($HasToken) { Join-Path $env:TEMP "storyboarder-launch-$Token.ready"  } else { '' }
$StatusMarkerPath = if ($HasToken) { Join-Path $env:TEMP "storyboarder-launch-$Token.status" } else { '' }
$FailedMarkerPath = if ($HasToken) { Join-Path $env:TEMP "storyboarder-launch-$Token.failed" } else { '' }

# --- WinForms assembly ---
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# -----------------------------------------------------------------------
# Form
# -----------------------------------------------------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text          = 'Storyboarder'
$form.Size          = New-Object System.Drawing.Size(460, 280)
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.BackColor     = [System.Drawing.Color]::FromArgb(24, 24, 28)
$form.ForeColor     = [System.Drawing.Color]::FromArgb(230, 230, 235)
$form.TopMost       = $true
$form.KeyPreview    = $true

# Borderless dragging
$script:_drag_origin = [System.Drawing.Point]::Empty
$script:_dragging    = $false
$form.Add_MouseDown({
    if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $script:_drag_origin = $_.Location
        $script:_dragging    = $true
    }
})
$form.Add_MouseMove({
    if ($script:_dragging) {
        $delta = [System.Drawing.Size]::new($_.X - $script:_drag_origin.X, $_.Y - $script:_drag_origin.Y)
        $form.Location = [System.Drawing.Point]::Add($form.Location, $delta)
    }
})
$form.Add_MouseUp({ $script:_dragging = $false })

# Escape = always close
$form.Add_KeyDown({
    if ($_.KeyCode -eq [System.Windows.Forms.Keys]::Escape) { $form.Close() }
})

# Icon (best-effort)
$iconPath = Join-Path $PSScriptRoot '..\storyboard_tool\assets\icon.ico'
if (Test-Path $iconPath) {
    try { $form.Icon = [System.Drawing.Icon]::new($iconPath) } catch {}
}

# -----------------------------------------------------------------------
# Controls
# -----------------------------------------------------------------------
$titleFont  = New-Object System.Drawing.Font('Segoe UI', 22, [System.Drawing.FontStyle]::Bold)
$statusFont = New-Object System.Drawing.Font('Segoe UI', 10)
$btnFont    = New-Object System.Drawing.Font('Segoe UI', 10)

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text      = 'Storyboarder'
$titleLabel.Font      = $titleFont
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(230, 230, 235)
$titleLabel.AutoSize  = $true
$titleLabel.Location  = New-Object System.Drawing.Point(40, 58)
$form.Controls.Add($titleLabel)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text      = 'Starting Storyboarder…'
$statusLabel.Font      = $statusFont
$statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(155, 155, 168)
$statusLabel.Size      = New-Object System.Drawing.Size(380, 44)
$statusLabel.Location  = New-Object System.Drawing.Point(40, 142)
$statusLabel.WordWrap  = $true
$form.Controls.Add($statusLabel)

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Style                 = [System.Windows.Forms.ProgressBarStyle]::Marquee
$progressBar.MarqueeAnimationSpeed = 28
$progressBar.Location              = New-Object System.Drawing.Point(40, 198)
$progressBar.Size                  = New-Object System.Drawing.Size(380, 8)
$form.Controls.Add($progressBar)

# Close button — hidden until an error occurs
$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text     = 'Close'
$closeButton.Font     = $btnFont
$closeButton.Size     = New-Object System.Drawing.Size(90, 30)
$closeButton.Location = New-Object System.Drawing.Point(40, 210)
$closeButton.Visible  = $false
$closeButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$closeButton.BackColor = [System.Drawing.Color]::FromArgb(60, 60, 68)
$closeButton.ForeColor = [System.Drawing.Color]::FromArgb(220, 220, 225)
$closeButton.Add_Click({ $form.Close() })
$form.Controls.Add($closeButton)

# -----------------------------------------------------------------------
# Error-state helper
# -----------------------------------------------------------------------
$script:_inErrorState = $false

$script:_enterErrorState = {
    if ($script:_inErrorState) { return }
    $script:_inErrorState = $true
    $timer.Stop()
    $progressBar.Visible = $false
    $titleLabel.Text     = 'Storyboarder could not start'
    $titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(210, 80, 80)
    # Read failure message from status file
    $msg = ''
    if ($HasToken -and $StatusMarkerPath -ne '' -and (Test-Path $StatusMarkerPath)) {
        try {
            $raw = Get-Content $StatusMarkerPath -Raw -ErrorAction SilentlyContinue
            if ($null -ne $raw) { $msg = $raw.Trim() }
        } catch {}
    }
    if (-not $msg) { $msg = 'Startup failed. Check logs/desktop.log for details.' }
    $statusLabel.Text     = $msg
    $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(210, 110, 110)
    $closeButton.Visible  = $true
    $closeButton.Focus()
}

# -----------------------------------------------------------------------
# Polling timer
# -----------------------------------------------------------------------
$script:_start   = [System.Diagnostics.Stopwatch]::StartNew()
$script:_warned  = $false
$script:_msgIdx  = 0

$msgs = @(
    'Starting Storyboarder…',
    'Starting local service…',
    'Loading project…',
    'Preparing workspace…'
)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 200   # poll every 200 ms

$timer.Add_Tick({
    $elapsedSec = $script:_start.Elapsed.TotalSeconds

    # Fatal failure marker — switch to error state immediately
    if ($HasToken -and $FailedMarkerPath -ne '' -and (Test-Path $FailedMarkerPath)) {
        & $script:_enterErrorState
        return
    }

    # Primary close signal: ready marker
    if ($HasToken -and $ReadyMarkerPath -ne '' -and (Test-Path $ReadyMarkerPath)) {
        try { Remove-Item $ReadyMarkerPath -Force -ErrorAction SilentlyContinue } catch {}
        $timer.Stop()
        $form.Close()
        return
    }

    # Status file overrides time-based fallback messages
    $statusSet = $false
    if ($HasToken -and $StatusMarkerPath -ne '' -and (Test-Path $StatusMarkerPath)) {
        try {
            $raw = Get-Content $StatusMarkerPath -Raw -ErrorAction SilentlyContinue
            if ($null -ne $raw) {
                $content = $raw.Trim()
                if ($content -and $content -ne $statusLabel.Text) {
                    $statusLabel.Text      = $content
                    $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(155, 155, 168)
                }
                $statusSet = $true
            }
        } catch {}
    }

    # Time-based fallback when no status file is present
    if (-not $statusSet) {
        $idx = [int][Math]::Min([Math]::Floor($elapsedSec / 4.0), $msgs.Count - 1)
        if ($idx -ne $script:_msgIdx) {
            $script:_msgIdx   = $idx
            $statusLabel.Text = $msgs[$idx]
        }
        if ($elapsedSec -ge 30 -and -not $script:_warned) {
            $script:_warned         = $true
            $statusLabel.Text       = 'Startup is taking longer than expected…'
            $statusLabel.ForeColor  = [System.Drawing.Color]::FromArgb(210, 170, 80)
        }
    }

    # Last-resort timeout (120 s)
    if ($elapsedSec -ge 120) {
        $timer.Stop()
        $form.Close()
    }
})

$timer.Start()
[void]$form.ShowDialog()
$timer.Stop()
$timer.Dispose()
$form.Dispose()
