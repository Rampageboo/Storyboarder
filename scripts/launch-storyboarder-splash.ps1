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
    Close button; the progress bar stops. The window does NOT auto-fade on error.
    On .ready:  transitions to a brief Ready state, then fades out and closes.
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

# ── Timing constants ─────────────────────────────────────────────────────────
# Splash stays visible at least this long regardless of how fast startup is.
$MinimumVisibleMs = 1000
# Extra hold in the Ready state before the fade begins.
$ReadyHoldMs      = 180
# Total fade-out duration.
$FadeDurationMs   = 160
# Fade timer tick (≈60 fps).
$FadeStepMs       = 16

# ── Token validation (restrict filesystem paths to known pattern) ─────────────
$HasToken = $Token.Length -gt 0 -and ($Token -match '^[a-zA-Z0-9_-]{1,64}$')
$ReadyMarkerPath  = if ($HasToken) { Join-Path $env:TEMP "storyboarder-launch-$Token.ready"  } else { '' }
$StatusMarkerPath = if ($HasToken) { Join-Path $env:TEMP "storyboarder-launch-$Token.status" } else { '' }
$FailedMarkerPath = if ($HasToken) { Join-Path $env:TEMP "storyboarder-launch-$Token.failed" } else { '' }

# ── WinForms assembly ─────────────────────────────────────────────────────────
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ── Form ─────────────────────────────────────────────────────────────────────
$form = New-Object System.Windows.Forms.Form
$form.Text            = 'Storyboarder'
$form.Size            = New-Object System.Drawing.Size(460, 208)
$form.StartPosition   = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.BackColor       = [System.Drawing.Color]::FromArgb(24, 24, 28)
$form.ForeColor       = [System.Drawing.Color]::FromArgb(230, 230, 235)
$form.TopMost         = $true
$form.KeyPreview      = $true

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

# Escape = always close (stops all timers via FormClosing)
$form.Add_KeyDown({
    if ($_.KeyCode -eq [System.Windows.Forms.Keys]::Escape) { $form.Close() }
})

# Stop all timers when the form closes to avoid double-dispose
$form.Add_FormClosing({
    $timer.Stop()
    $script:_fadeTimer.Stop()
})

# Window icon (taskbar)
$iconPath = Join-Path $PSScriptRoot '..\storyboard_tool\assets\icon.ico'
if (Test-Path $iconPath) {
    try { $form.Icon = [System.Drawing.Icon]::new($iconPath) } catch {}
}

# ── Controls ──────────────────────────────────────────────────────────────────
$titleFont    = New-Object System.Drawing.Font('Segoe UI', 22, [System.Drawing.FontStyle]::Bold)
$subtitleFont = New-Object System.Drawing.Font('Segoe UI', 9)
$statusFont   = New-Object System.Drawing.Font('Segoe UI', 10)
$btnFont      = New-Object System.Drawing.Font('Segoe UI', 10)

# Application icon displayed inside the splash (48×48 next to title)
$iconBox = New-Object System.Windows.Forms.PictureBox
$iconBox.Size     = New-Object System.Drawing.Size(52, 52)
$iconBox.Location = New-Object System.Drawing.Point(28, 20)
$iconBox.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
$iconBox.BackColor = [System.Drawing.Color]::Transparent
if (Test-Path $iconPath) {
    try {
        $ico = [System.Drawing.Icon]::new($iconPath, 48, 48)
        $iconBox.Image = $ico.ToBitmap()
    } catch {}
}
$form.Controls.Add($iconBox)

# Title — vertically aligned with the icon
$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text      = 'Storyboarder'
$titleLabel.Font      = $titleFont
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(230, 230, 235)
$titleLabel.AutoSize  = $true
$titleLabel.Location  = New-Object System.Drawing.Point(92, 20)
$form.Controls.Add($titleLabel)

# Subtitle — below title, muted
$subtitleLabel = New-Object System.Windows.Forms.Label
$subtitleLabel.Text      = 'Local storyboard workspace'
$subtitleLabel.Font      = $subtitleFont
$subtitleLabel.ForeColor = [System.Drawing.Color]::FromArgb(108, 108, 120)
$subtitleLabel.AutoSize  = $true
$subtitleLabel.Location  = New-Object System.Drawing.Point(92, 60)
$form.Controls.Add($subtitleLabel)

# Status text
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text      = 'Starting Storyboarder…'
$statusLabel.Font      = $statusFont
$statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(148, 148, 162)
$statusLabel.Size      = New-Object System.Drawing.Size(404, 36)
$statusLabel.Location  = New-Object System.Drawing.Point(28, 106)
$statusLabel.WordWrap  = $true
$form.Controls.Add($statusLabel)

# Progress bar — subtle marquee during startup
$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Style                 = [System.Windows.Forms.ProgressBarStyle]::Marquee
$progressBar.MarqueeAnimationSpeed = 28
$progressBar.Location              = New-Object System.Drawing.Point(28, 158)
$progressBar.Size                  = New-Object System.Drawing.Size(404, 6)
$form.Controls.Add($progressBar)

# Close button — hidden until an error occurs
$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text      = 'Close'
$closeButton.Font      = $btnFont
$closeButton.Size      = New-Object System.Drawing.Size(90, 30)
$closeButton.Location  = New-Object System.Drawing.Point(28, 158)
$closeButton.Visible   = $false
$closeButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$closeButton.BackColor = [System.Drawing.Color]::FromArgb(60, 60, 68)
$closeButton.ForeColor = [System.Drawing.Color]::FromArgb(220, 220, 225)
$closeButton.Add_Click({ $form.Close() })
$form.Controls.Add($closeButton)

# ── State ────────────────────────────────────────────────────────────────────
# Phase: "starting" → "ready" → "fading" | "error"
$script:_phase        = "starting"
$script:_readyAt      = 0.0      # elapsed Ms when ready marker appeared
$script:_fadeOpacity  = 1.0
$script:_inErrorState = $false
$script:_warned       = $false
$script:_msgIdx       = 0

$msgs = @(
    'Starting Storyboarder…',
    'Starting local service…',
    'Loading project…',
    'Preparing workspace…'
)

# ── Fade timer ────────────────────────────────────────────────────────────────
# Runs only during the "fading" phase. Decrements form opacity until 0 then closes.
$script:_fadeTimer = New-Object System.Windows.Forms.Timer
$script:_fadeTimer.Interval = $FadeStepMs
$script:_fadeTimer.Add_Tick({
    $script:_fadeOpacity -= [double]$FadeStepMs / [double]$FadeDurationMs
    if ($script:_fadeOpacity -le 0.0) {
        $script:_fadeTimer.Stop()
        $form.Close()
    } else {
        $form.Opacity = $script:_fadeOpacity
    }
})

# ── Error-state helper ────────────────────────────────────────────────────────
$script:_enterErrorState = {
    if ($script:_inErrorState) { return }
    $script:_inErrorState = $true
    $script:_phase        = "error"
    $timer.Stop()
    $script:_fadeTimer.Stop()
    $progressBar.Visible = $false
    $titleLabel.Text     = 'Storyboarder could not start'
    $titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(210, 80, 80)
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

# ── Polling timer ────────────────────────────────────────────────────────────
$script:_start = [System.Diagnostics.Stopwatch]::StartNew()

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 100   # poll every 100 ms (tighter than before for snappier ready response)

$timer.Add_Tick({
    $elapsedMs  = $script:_start.Elapsed.TotalMilliseconds
    $elapsedSec = $elapsedMs / 1000.0

    # ── Phase: starting ───────────────────────────────────────────────────────
    if ($script:_phase -eq "starting") {

        # Fatal failure
        if ($HasToken -and $FailedMarkerPath -ne '' -and (Test-Path $FailedMarkerPath)) {
            & $script:_enterErrorState
            return
        }

        # Ready marker → transition to "ready" phase (do not close immediately)
        if ($HasToken -and $ReadyMarkerPath -ne '' -and (Test-Path $ReadyMarkerPath)) {
            try { Remove-Item $ReadyMarkerPath -Force -ErrorAction SilentlyContinue } catch {}
            $script:_phase   = "ready"
            $script:_readyAt = $elapsedMs
            $statusLabel.Text      = 'Ready'
            $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(96, 188, 120)
            $progressBar.Style     = [System.Windows.Forms.ProgressBarStyle]::Continuous
            $progressBar.Value     = 100
            # Fall through to "ready" check below for fast startups.
        } else {
            # Update status text while waiting
            $statusSet = $false
            if ($HasToken -and $StatusMarkerPath -ne '' -and (Test-Path $StatusMarkerPath)) {
                try {
                    $raw = Get-Content $StatusMarkerPath -Raw -ErrorAction SilentlyContinue
                    if ($null -ne $raw) {
                        $content = $raw.Trim()
                        if ($content -and $content -ne $statusLabel.Text) {
                            $statusLabel.Text      = $content
                            $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(148, 148, 162)
                        }
                        $statusSet = $true
                    }
                } catch {}
            }
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
        }
    }

    # ── Phase: ready (may have just entered above) ────────────────────────────
    if ($script:_phase -eq "ready") {
        $holdElapsed = $elapsedMs - $script:_readyAt
        if ($elapsedMs -ge $MinimumVisibleMs -and $holdElapsed -ge $ReadyHoldMs) {
            $script:_phase = "fading"
            $timer.Stop()
            $script:_fadeTimer.Start()
        }
    }

    # Last-resort timeout (120 s) — fires even if ready/fading logic stalled
    if ($elapsedSec -ge 120) {
        $timer.Stop()
        $script:_fadeTimer.Stop()
        $form.Close()
    }
})

$timer.Start()
[void]$form.ShowDialog()
$timer.Stop()
$script:_fadeTimer.Stop()
$timer.Dispose()
$script:_fadeTimer.Dispose()
$form.Dispose()
