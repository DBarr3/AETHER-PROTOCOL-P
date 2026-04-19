#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod errors;
mod manifest;
mod payload;
mod installer;

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running AetherCloud Setup");
}
