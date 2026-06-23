// Hide the console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::{Mutex, OnceLock};
use tauri::Manager;

// Sidecar child is stored here to keep the process alive for the app's lifetime.
struct SidecarGuard(Mutex<Option<std::process::Child>>);

// Resolved FastAPI port; set once during setup, read by the `api_port` command.
static API_PORT: OnceLock<u16> = OnceLock::new();

#[tauri::command]
fn api_port() -> u16 {
    *API_PORT.get().unwrap_or(&0)
}

fn main() {
    tauri::Builder::default()
        .manage(SidecarGuard(Mutex::new(None)))
        .setup(|app| {
            let port = resolve_api_port(app)?;
            API_PORT.set(port).ok();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_port])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn resolve_api_port(app: &mut tauri::App) -> Result<u16, Box<dyn std::error::Error>> {
    // --- release: spawn storyboard-backend.exe from the same directory as this exe ---
    #[cfg(not(debug_assertions))]
    {
        use std::io::BufRead;

        let exe_dir = std::env::current_exe()?
            .parent()
            .ok_or("cannot resolve exe directory")?
            .to_path_buf();
        let sidecar = exe_dir.join("storyboard-backend.exe");

        let mut child = std::process::Command::new(&sidecar)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("failed to spawn {}: {e}", sidecar.display()))?;

        // Read PORT:<n> synchronously from sidecar stdout.
        let stdout = child.stdout.take().ok_or("sidecar stdout unavailable")?;
        let mut port: u16 = 0;
        for line in std::io::BufReader::new(stdout).lines() {
            let line = line?;
            if let Some(p) = line.trim().strip_prefix("PORT:") {
                if let Ok(n) = p.trim().parse::<u16>() {
                    port = n;
                    break;
                }
            }
        }

        if port == 0 {
            return Err("sidecar did not report a port".into());
        }

        // Keep child alive; drop = process killed.
        *app.state::<SidecarGuard>().0.lock().unwrap() = Some(child);

        return Ok(port);
    }

    // --- debug: auto-discover port from the bridge file Python writes on startup ---
    #[cfg(debug_assertions)]
    {
        // Honour an explicit override first.
        if let Some(port) = std::env::var("STORYBOARD_DEV_PORT")
            .ok()
            .and_then(|s| s.parse::<u16>().ok())
        {
            eprintln!("[dev] Using Python backend on port {port} (STORYBOARD_DEV_PORT)");
            return Ok(port);
        }

        // Otherwise, poll the bridge JSON file that Python writes at startup.
        // Path: %LOCALAPPDATA%\StoryboardTool\storyboard_live_bridge.json
        let bridge_path = {
            let local_app_data = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| {
                format!(
                    "{}\\AppData\\Local",
                    std::env::var("USERPROFILE").unwrap_or_default()
                )
            });
            std::path::PathBuf::from(local_app_data)
                .join("StoryboardTool")
                .join("storyboard_live_bridge.json")
        };

        eprintln!("[dev] Waiting for Python backend (reading {})…", bridge_path.display());

        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
        loop {
            if let Ok(text) = std::fs::read_to_string(&bridge_path) {
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) {
                    if let Some(port) = json.get("port").and_then(|p| p.as_u64()) {
                        let port = port as u16;
                        eprintln!("[dev] Python backend found on port {port}");
                        return Ok(port);
                    }
                }
            }
            if std::time::Instant::now() >= deadline {
                return Err("Python backend did not start within 30s. Run `python main.py` first.".into());
            }
            std::thread::sleep(std::time::Duration::from_millis(300));
        }
    }
}
