/// The desktop shell holds no data and no secrets: it renders the interface, opens the
/// native file picker, and reads the files the employee chose so they can be uploaded.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .run(tauri::generate_context!())
        .expect("error while running Cadastro AI");
}
