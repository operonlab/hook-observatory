use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, Runtime,
};

// TODO: Mouse passthrough — Tauri 2 exposes window.set_ignore_cursor_events(true).
// Enable this when the mascot is in "idle" state so clicks pass through to desktop.
// Disable it when user hovers over the speech bubble / input area.

// TODO: Window drag — implement custom drag via mousedown on the mascot canvas.
// Use window.start_dragging() (Tauri 2 API) inside a Tauri command:
//   #[tauri::command]
//   fn start_drag(window: tauri::Window) { window.start_dragging().ok(); }

/// Toggle main window visibility.
fn toggle_window<R: Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            window.hide().ok();
        } else {
            window.show().ok();
            window.set_focus().ok();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            // --- System Tray Setup ---
            let show_item = MenuItem::with_id(app, "show", "Show / Hide", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            let _tray = TrayIconBuilder::new()
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => toggle_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // Left-click on tray icon toggles the window.
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        toggle_window(tray.app_handle());
                    }
                })
                .build(app)?;

            // --- Global Shortcut: Cmd+Shift+A → toggle window ---
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

                let shortcut = Shortcut::new(
                    Some(Modifiers::META | Modifiers::SHIFT),
                    Code::KeyA,
                );

                let app_handle = app.handle().clone();
                app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        toggle_window(&app_handle);
                    }
                })?;
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![start_drag])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Expose window dragging to the frontend.
/// Call from JS: invoke("start_drag") on mousedown of the drag handle area.
#[tauri::command]
fn start_drag(window: tauri::WebviewWindow) {
    window.start_dragging().ok();
}
