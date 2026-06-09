import { dev } from '$app/environment';

function trim_trailing_separators(path: string) {
	return path.replace(/[\\/]+$/, '');
}

function normalize_windows_path(path: string) {
	return trim_trailing_separators(path.replaceAll('/', '\\'));
}

function join_windows_path(root: string, relative_path: string) {
	const normalized_relative = relative_path.replaceAll('/', '\\').replace(/^\\+/, '');
	return `${trim_trailing_separators(root)}\\${normalized_relative}`;
}

export function get_project_root() {
	if (dev) {
		const configured_root = String(import.meta.env.VITE_IKUSA_PROJECT_ROOT ?? '').trim();
		if (configured_root) {
			return normalize_windows_path(configured_root);
		}

		return '.';
	}

	return window.NL_PATH;
}

export function get_runtime_root() {
	if (dev) {
		const configured_root = String(import.meta.env.VITE_IKUSA_DEV_RUNTIME ?? '').trim();
		if (configured_root) {
			return normalize_windows_path(configured_root);
		}

		return join_windows_path(get_project_root(), '.dev-runtime');
	}

	return window.NL_PATH;
}

export function get_project_path(relative_path: string) {
	return join_windows_path(get_project_root(), relative_path);
}

export function get_runtime_path(relative_path: string) {
	return join_windows_path(get_runtime_root(), relative_path);
}