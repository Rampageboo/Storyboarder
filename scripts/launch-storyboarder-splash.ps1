<#
.SYNOPSIS
    Lightweight native starter splash for Storyboarder.

.DESCRIPTION
    Appears immediately when the user launches Storyboarder, before Python
    has a chance to import FastAPI, Pillow, or other heavy modules.

    Polls for a per-launch ready marker (%TEMP%\storyboarder-launch-<Token>.ready)
    and closes the moment the marker is found, or when the user presses Escape.

    Requires no elevated privileges. Falls back gracefully if the token is
    absent or malformed (timeout safety closes the window).

.PARAMETER Token
    Unique per-launch UUID from the launcher batch file.
    If absent or invalid, splash falls back to a 120-second timeout.
#>
param(
    [string]$Token = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

# --- Token validation (restrict filesystem writes to known pattern) ---
$HasToken = $Token.Length -gt 0 -and ($Token -match '^[a-zA-Z0-9_-]{1,64}$')
$ReadyMarkerPath = if ($HasToken) { Join-Path $env:TEMP "storyboarder-launch-$Token.ready" } else { '' }

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

# Make borderless form draggable
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

# Escape = emergency close
$form.Add_KeyDown({
    if ($_.KeyCode -eq [System.Windows.Forms.Keys]::Escape) { $form.Close() }
})

# --- Icon (best-effort) ---
$iconPath = Join-Path $PSScriptRoot '..\storyboard_tool\assets\icon.ico'
if (Test-Path $iconPath) {
    try { $form.Icon = [System.Drawing.Icon]::new($iconPath) } catch {}
}

# -----------------------------------------------------------------------
# Controls
# -----------------------------------------------------------------------
$titleFont  = New-Object System.Drawing.Font('Segoe UI', 22, [System.Drawing.FontStyle]::Bold)
$statusFont = New-Object System.Drawing.Font('Segoe UI', 10)

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
$statusLabel.AutoSize  = $true
$statusLabel.Location  = New-Object System.Drawing.Point(40, 142)
$form.Controls.Add($statusLabel)

$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Style                  = [System.Windows.Forms.ProgressBarStyle]::Marquee
$progressBar.MarqueeAnimationSpeed  = 28
$progressBar.Location               = New-Object System.Drawing.Point(40, 178)
$progressBar.Size                   = New-Object System.Drawing.Size(380, 8)
$form.Controls.Add($progressBar)

# -----------------------------------------------------------------------
# Polling timer
# -----------------------------------------------------------------------
$script:_start        = [System.Diagnostics.Stopwatch]::StartNew()
$script:_warned       = $false
$script:_msgIdx       = 0

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

    # Rotate status message every ~4 seconds
    $idx = [int][Math]::Min([Math]::Floor($elapsedSec / 4.0), $msgs.Count - 1)
    if ($idx -ne $script:_msgIdx) {
        $script:_msgIdx = $idx
        $statusLabel.Text = $msgs[$idx]
    }

    # 30-second "taking longer than expected" notice
    if ($elapsedSec -ge 30 -and -not $script:_warned) {
        $script:_warned         = $true
        $statusLabel.Text       = 'Startup is taking longer than expected…'
        $statusLabel.ForeColor  = [System.Drawing.Color]::FromArgb(210, 170, 80)
    }

    # Primary close signal: ready-marker file
    if ($script:HasToken -and ($script:ReadyMarkerPath -ne '') -and (Test-Path $script:ReadyMarkerPath)) {
        try { Remove-Item $script:ReadyMarkerPath -Force } catch {}
        $timer.Stop()
        $form.Close()
        return
    }

    # Safety timeout at 120 seconds (do not trap the desktop)
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
