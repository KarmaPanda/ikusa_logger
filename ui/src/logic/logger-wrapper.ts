import { dev } from '$app/environment';
import { events, os, storage } from '@neutralinojs/lib';
import { get_project_path, get_runtime_root } from './runtime-path';

const DEV_LOGGER_CONSOLE_KEY = 'ikusa_dev_logger_console_enabled';
const DEBUG_MIRROR_DIR = 'logger\\.tmp';
const DEBUG_MIRROR_FILE = 'ui-dev-logger-mirror.log';

function quote_windows_path(path: string) {
	return `"${path}"`;
}

function get_logger_cwd() {
	return get_runtime_root();
}

function get_logger_command() {
	if (dev) {
		return quote_windows_path(get_project_path('logger\\dist\\logger\\logger.exe'));
	}

	return quote_windows_path(`${window.NL_PATH}\\logger\\logger.exe`);
}

export function quote_logger_argument(value: string) {
	return quote_windows_path(value.replaceAll('"', '\\"'));
}

export function get_dev_logger_console_enabled() {
	return dev_logger_console_enabled_cache;
}

export function set_dev_logger_console_enabled(enabled: boolean) {
	dev_logger_console_enabled_cache = Boolean(enabled);
	storage
		.setData(DEV_LOGGER_CONSOLE_KEY, dev_logger_console_enabled_cache ? '1' : '0')
		.catch((error) => console.warn('Failed to persist debug logger mirror setting', error));
}

let dev_logger_console_enabled_cache = false;
let dev_logger_console_loaded = false;

export async function load_dev_logger_console_enabled() {
	if (dev_logger_console_loaded) {
		return dev_logger_console_enabled_cache;
	}

	try {
		const raw = await storage.getData(DEV_LOGGER_CONSOLE_KEY);
		dev_logger_console_enabled_cache = String(raw ?? '').trim() === '1';
	} catch (error) {
		if ((error as { code?: string } | undefined)?.code !== 'NE_ST_NOSTKEX') {
			console.warn('Failed to load debug logger mirror setting', error);
		}
		dev_logger_console_enabled_cache = false;
	}

	dev_logger_console_loaded = true;
	return dev_logger_console_enabled_cache;
}

let debug_tail_window_started = false;

export async function close_debug_tail_window() {
	try {
		await os.execCommand('taskkill /F /FI "WINDOWTITLE eq Ikusa Logger Debug Tail"', {
			background: false,
			cwd: get_logger_cwd()
		});
	} catch {
		// No matching window is expected when debug tail is not open.
	} finally {
		debug_tail_window_started = false;
	}
}

function get_debug_mirror_dir_path() {
	return `${get_logger_cwd()}\\${DEBUG_MIRROR_DIR}`;
}

function get_debug_mirror_file_path() {
	return `${get_debug_mirror_dir_path()}\\${DEBUG_MIRROR_FILE}`;
}

async function ensure_debug_mirror_target() {
	const mirror_dir = quote_windows_path(get_debug_mirror_dir_path());
	const mirror_file = quote_windows_path(get_debug_mirror_file_path());
	const ensure_command = `cmd /c if not exist ${mirror_dir} mkdir ${mirror_dir} & if not exist ${mirror_file} type nul > ${mirror_file}`;
	await os.execCommand(ensure_command, { background: false, cwd: get_logger_cwd() });
}

async function append_debug_mirror_run_marker(label: string) {
	await ensure_debug_mirror_target();
	const mirror_file = quote_windows_path(get_debug_mirror_file_path());
	const timestamp = new Date().toISOString();
	const safe_label = String(label ?? '').replaceAll('"', '');
	const marker = `[RUN_START ${timestamp}] ${safe_label}`;
	const marker_command = `cmd /c echo.>>${mirror_file} & echo ${marker}>>${mirror_file}`;
	await os.execCommand(marker_command, { background: false, cwd: get_logger_cwd() });
}

async function ensure_debug_tail_window() {
	if (debug_tail_window_started) {
		return;
	}

	// If the app was relaunched (e.g. Dev Mode restart), close any stale tail
	// window from a previous session before opening a fresh one.
	await close_debug_tail_window();

	const mirror_file_path = get_debug_mirror_file_path().replaceAll("'", "''");
	const tail_command = `start "Ikusa Logger Debug Tail" powershell -NoLogo -ExecutionPolicy Bypass -Command "Get-Content -Path '${mirror_file_path}' -Wait"`;
	await os.execCommand(tail_command, { background: true, cwd: get_logger_cwd() });
	debug_tail_window_started = true;
}

async function maybe_mirror_logger_console(command: string) {
	if (!(await load_dev_logger_console_enabled())) {
		return;
	}

	const mirror_file = quote_windows_path(get_debug_mirror_file_path());
	const mirrored_command = `cmd /c "${command} 1>>${mirror_file} 2>&1"`;
	try {
		await ensure_debug_mirror_target();
		await ensure_debug_tail_window();
		await os.execCommand(mirrored_command, { background: true, cwd: get_logger_cwd() });
	} catch (error) {
		console.warn('Failed to mirror logger command in debug console', error);
		console.warn('Mirrored command:', mirrored_command);
	}
}

function handle_process(evt: CustomEvent) {
	if (!logger || logger.id !== evt.detail.id) {
		return;
	}

	switch (evt.detail.action) {
		case 'stdOut':
			console.log(evt.detail.data.trim());
			callback?.(String(evt.detail.data ?? ''), 'running');
			break;
		case 'stdErr':
			alert(
				'Something went wrong. Please contact me on discord and send the following error message:\n\n' +
				evt.detail.data
			);
			console.error(evt.detail.data);
			callback?.(String(evt.detail.data ?? ''), 'error');
			break;
		case 'exit':
			console.log(`Logger process terminated with exit code: ${evt.detail.data}`);
			clear_periodic_auto_discovery();
			logger = null;
			callback?.(evt.detail.data, 'terminated');
			callback = null;
			events.off('spawnedProcess', handle_process);
			break;
	}
}

const arg_mapping = {
	sniff: '',
	open_file: '-f',
	status: '-s',
	update: '-u',
	record: '-r',
	analyze: '-a',
} as const;

let logger: os.SpawnedProcess | null = null;
let last_auto_discovery_at = 0;
const AUTO_DISCOVERY_INTERVAL_MS = 30000;
const PERIODIC_AUTO_DISCOVERY_MS = 45000;
let auto_discovery_interval_id: number | null = null;
let auto_discovery_in_flight = false;

export type LoggerCallback = (data: string, status: 'running' | 'terminated' | 'error') => void;
let callback: LoggerCallback | null = null;

function clear_periodic_auto_discovery() {
	if (auto_discovery_interval_id !== null) {
		window.clearInterval(auto_discovery_interval_id);
		auto_discovery_interval_id = null;
	}
}

function supports_auto_discovery(arg: keyof typeof arg_mapping) {
	return arg === 'analyze' || arg === 'record' || arg === 'sniff';
}

function start_periodic_auto_discovery(arg: keyof typeof arg_mapping) {
	clear_periodic_auto_discovery();

	if (!supports_auto_discovery(arg)) {
		return;
	}

	auto_discovery_interval_id = window.setInterval(() => {
		if (!logger) {
			clear_periodic_auto_discovery();
			return;
		}

		run_auto_discovery_before_start(arg).catch((error) => {
			console.warn('Periodic auto-discovery failed', error);
		});
	}, PERIODIC_AUTO_DISCOVERY_MS);
}

async function run_auto_discovery_before_start(arg: keyof typeof arg_mapping) {
	if (!supports_auto_discovery(arg)) {
		return;
	}

	if (auto_discovery_in_flight) {
		return;
	}

	const now = Date.now();
	if (now - last_auto_discovery_at < AUTO_DISCOVERY_INTERVAL_MS) {
		return;
	}

	last_auto_discovery_at = now;
	auto_discovery_in_flight = true;

	try {
		const logger_command = get_logger_command();
		const discovery_command_parts = [
			logger_command,
			'--discover-game-ips',
			'--game-process',
			'BlackDesert64.exe',
			'--include-exitlag',
			'--apply-discovered-ips',
			'--json'
		];

		const discovery_command = discovery_command_parts.join(' ');

		const result = (await os.execCommand(discovery_command, {
			background: false,
			cwd: get_logger_cwd()
		})) as { stdOut?: string; stdErr?: string; exitCode?: number };

		if (result?.stdErr && result.stdErr.trim().length > 0) {
			console.warn('Auto-discovery stderr:', result.stdErr.trim());
		}

		if (result?.stdOut) {
			const lines = result.stdOut
				.split(/\r?\n/)
				.map((line) => line.trim())
				.filter(Boolean);
			for (let index = lines.length - 1; index >= 0; index--) {
				try {
					const payload = JSON.parse(lines[index]) as {
						summary?: { high_confidence_prefixes?: string[] };
						applied_ips?: string[];
					};
					const prefixes = payload?.summary?.high_confidence_prefixes ?? [];
					const applied = payload?.applied_ips ?? [];
					if (applied.length > 0) {
						console.log('Auto-discovery applied IP prefixes:', prefixes.join(', '));
					} else if (prefixes.length > 0) {
						console.log('Auto-discovery discovered IP prefixes:', prefixes.join(', '));
					}
					break;
				} catch {
					continue;
				}
			}
		}
	} catch (error) {
		console.warn('Auto-discovery failed before logger start', error);
	} finally {
		auto_discovery_in_flight = false;
	}
}

export async function stop_logger() {
	clear_periodic_auto_discovery();
	events.off('spawnedProcess', handle_process);

	// Capture and clear module state immediately so concurrent calls skip these operations
	const current_logger = logger;
	logger = null;
	callback = null;

	if (current_logger) {
		try {
			await os.updateSpawnedProcess(current_logger.id, 'exit');
		} catch (e) {
			console.error(e);
		}
	}

	try {
		await os.execCommand('taskkill /F /IM logger.exe ', { background: false, cwd: get_logger_cwd() });
	} catch (e) {
		console.error(e);
	}
}

export async function start_logger(
	clb: LoggerCallback,
	arg: keyof typeof arg_mapping,
	data?: string
) {
	console.log('Killing previous instances');
	await stop_logger();
	await run_auto_discovery_before_start(arg);

	if (arg === 'analyze' && (await load_dev_logger_console_enabled())) {
		await append_debug_mirror_run_marker('analyze replay');
	}

	const extra_args = data ? ' ' + data : '';
	const logger_command = get_logger_command();
	const command = logger_command + ' ' + arg_mapping[arg] + extra_args;

	console.log('Starting logger with command: ' + command);
	await maybe_mirror_logger_console(command);

	events.off('spawnedProcess', handle_process);
	logger = await os.spawnProcess(command, get_logger_cwd());
	start_periodic_auto_discovery(arg);
	callback = clb;
	events.on('spawnedProcess', handle_process);
}

export async function spawn_parallel_logger(data: string) {
	const logger_command = get_logger_command();
	const command = `${logger_command} ${data}`;
	await maybe_mirror_logger_console(command);
	return await os.spawnProcess(command, get_logger_cwd());
}

export async function stop_spawned_logger(process_id: number | string) {
	await os.updateSpawnedProcess(Number(process_id), 'exit');
}

// Runs the calibrator as a one-shot execCommand WITHOUT stopping the currently spawned recorder.
export async function probe_logger_command(data: string): Promise<{ stdOut: string; stdErr: string; exitCode: number }> {
	const logger_command = get_logger_command();
	const command = `${logger_command} ${data}`;
	await maybe_mirror_logger_console(command);
	const result = await os.execCommand(command, { background: false, cwd: get_logger_cwd() });
	return result as { stdOut: string; stdErr: string; exitCode: number };
}

export async function run_logger_command(data?: string): Promise<{ stdOut: string; stdErr: string; exitCode: number }> {
	await stop_logger();

	const logger_command = get_logger_command();
	const command = data ? `${logger_command} ${data}` : logger_command;
	await maybe_mirror_logger_console(command);

	return await new Promise<{ stdOut: string; stdErr: string; exitCode: number }>(
		async (resolve, reject) => {
			let spawned: os.SpawnedProcess | null = null;
			let stdOut = '';
			let stdErr = '';

			const handle_once = (evt: CustomEvent) => {
				if (!spawned || spawned.id !== evt.detail.id) {
					return;
				}

				switch (evt.detail.action) {
					case 'stdOut':
						stdOut += evt.detail.data;
						break;
					case 'stdErr':
						stdErr += evt.detail.data;
						break;
					case 'exit':
						events.off('spawnedProcess', handle_once);
						if (logger?.id === spawned.id) {
							logger = null;
							callback = null;
						}
						resolve({
							stdOut,
							stdErr,
							exitCode: Number.parseInt(String(evt.detail.data), 10) || 0
						});
						break;
				}
			};

			events.on('spawnedProcess', handle_once);

			try {
				spawned = await os.spawnProcess(command, get_logger_cwd());
				logger = spawned;
			} catch (error) {
				events.off('spawnedProcess', handle_once);
				reject(error);
			}
		}
	);
}
