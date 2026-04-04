// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            commands::check_dependencies,
            commands::install_hooks,
            commands::get_config,
            commands::save_config,
            commands::detect_tools,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
