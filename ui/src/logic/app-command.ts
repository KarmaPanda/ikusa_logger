import { get_project_path } from './runtime-path';

function quote_windows_path(path: string) {
    return `"${path}"`;
}

export function get_app_command(relative_path: string) {
    return quote_windows_path(get_project_path(relative_path));
}

export function get_main_executable_command() {
    return get_app_command('ikusa-logger-win_x64.exe');
}

export function get_update_script_command() {
    return get_app_command('update.bat');
}

export function get_check_update_script_command() {
    return get_app_command('check-update.bat');
}