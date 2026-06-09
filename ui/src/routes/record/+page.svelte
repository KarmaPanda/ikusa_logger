<script lang="ts">
	import {
		stop_logger,
		type LoggerCallback,
		start_logger,
		quote_logger_argument
	} from '../../logic/logger-wrapper';
	import { onDestroy, onMount } from 'svelte';
	import { filesystem } from '@neutralinojs/lib';
	import Logger from '../../components/create-config/logger.svelte';
	import {
		get_config,
		parse_analyzer_output_line,
		type Config,
		type LogType
	} from '../../components/create-config/config';
	import { get_runtime_path } from '../../logic/runtime-path';
	import { show_toast } from '../../svelte-ui/util';

	let logs: LogType[] = [];
	let is_destroyed = false;
	let retry_count = 0;
	let start_in_flight = false;
	let restart_scheduled = false;
	let config: Config;
	let recovery_flush_timeout: number | null = null;
	let recovery_pending_write = false;

	const RECOVERY_SNAPSHOT_PATH = get_runtime_path('logger\\.tmp\\record-session-recovery.json');

	type RecoveryLog = {
		identifier: string;
		time: string;
		names: { name: string; offset: number }[];
		hex?: string;
		payload?: string;
	};

	function normalize_recovery_log(entry: unknown): LogType | null {
		if (!entry || typeof entry !== 'object') {
			return null;
		}

		const candidate = entry as RecoveryLog;
		const hex_or_payload = String(candidate.hex ?? candidate.payload ?? '').trim();
		if (!hex_or_payload || !/^[0-9a-f]+$/i.test(hex_or_payload)) {
			return null;
		}

		if (!Array.isArray(candidate.names)) {
			return null;
		}

		const names = candidate.names
			.map((item) => ({
				name: String(item?.name ?? ''),
				offset: Number(item?.offset)
			}))
			.filter((item) => Number.isFinite(item.offset));

		if (names.length < 3) {
			return null;
		}

		return {
			identifier: String(candidate.identifier ?? ''),
			time: String(candidate.time ?? ''),
			names,
			hex: hex_or_payload
		};
	}

	function schedule_recovery_write() {
		recovery_pending_write = true;
		if (recovery_flush_timeout !== null) {
			return;
		}

		recovery_flush_timeout = window.setTimeout(async () => {
			recovery_flush_timeout = null;
			if (!recovery_pending_write) {
				return;
			}

			recovery_pending_write = false;
			await write_recovery_snapshot();
		}, 1250);
	}

	async function write_recovery_snapshot() {
		if (logs.length === 0) {
			return;
		}

		try {
			await filesystem.writeFile(
				RECOVERY_SNAPSHOT_PATH,
				JSON.stringify(
					{
						version: 1,
						savedAt: new Date().toISOString(),
						logs: logs.map((log) => ({
							...log,
							// Keep a dedicated payload field for session recovery compatibility.
							payload: log.hex
						}))
					},
					null,
					2
				)
			);
		} catch (error) {
			console.error('Failed to write record recovery snapshot', error);
		}
	}

	async function clear_recovery_snapshot() {
		try {
			await filesystem.writeFile(RECOVERY_SNAPSHOT_PATH, '');
		} catch (error) {
			console.error('Failed to clear record recovery snapshot', error);
		}
	}

	async function try_restore_recovery_snapshot() {
		try {
			const raw = await filesystem.readFile(RECOVERY_SNAPSHOT_PATH);
			if (!raw || raw.trim().length === 0) {
				return;
			}

			const snapshot = JSON.parse(raw) as {
				logs?: RecoveryLog[];
				savedAt?: string;
			};

			const restored_logs = Array.isArray(snapshot.logs)
				? snapshot.logs
						.map(normalize_recovery_log)
						.filter((entry): entry is LogType => entry !== null)
				: [];

			if (restored_logs.length === 0) {
				return;
			}

			const confirm_restore = window.confirm(
				`Recovered ${restored_logs.length} unsaved log entries from a previous session.${snapshot.savedAt ? `\nSnapshot time: ${snapshot.savedAt}` : ''}\n\nRestore them now?`
			);
			if (!confirm_restore) {
				return;
			}

			logs = restored_logs;

			show_toast('Recovered unsaved logs from the previous session.', 'success');
		} catch {
			// Ignore missing or malformed snapshots.
		}
	}

	function handle_logs_saved() {
		clear_recovery_snapshot().catch((error) => console.error(error));
	}

	function build_analyze_args() {
		const parts: string[] = [];
		if (config.all_interfaces) {
			parts.push('-i');
		} else if (config.interface_name) {
			parts.push('--interface', quote_logger_argument(config.interface_name));
		}
		parts.push(config.ip_filter ? '-p' : '--no-ipFilter');
		return parts.join(' ');
	}

	async function start_analyze_logger(reason: 'initial' | 'retry') {
		if (!config || is_destroyed || start_in_flight) {
			return;
		}

		start_in_flight = true;
		try {
			await start_logger(logger_callback, 'analyze', build_analyze_args());
			if (reason === 'initial') {
				retry_count = 0;
			}
		} finally {
			start_in_flight = false;
		}
	}

	function schedule_restart() {
		if (is_destroyed || restart_scheduled || start_in_flight) {
			return;
		}

		if (retry_count >= 3) {
			alert('Tried to start logger 3 times, but failed. Please try again.');
			return;
		}

		restart_scheduled = true;
		window.setTimeout(async () => {
			restart_scheduled = false;
			if (is_destroyed) {
				return;
			}
			retry_count++;
			await start_analyze_logger('retry');
		}, 400);
	}

	const logger_callback: LoggerCallback = (data, status) => {
		if (status === 'running') {
			retry_count = 0;
			restart_scheduled = false;
			const new_log = parse_analyzer_output_line(data);
			if (new_log) {
				if (logs.find((log) => log.hex === new_log.hex && log.time === new_log.time)) {
					return;
				}

				logs.push(new_log);
				logs = logs;
				schedule_recovery_write();
			} else if (data.includes('Error while reading network.')) {
				alert('Error while reading network. Please notify me on Discord.');
			}
		} else if (status === ('error' as any)) {
			console.error(data);
			alert(
				'An error occurred while trying to start the logger. Error message: ' +
					data +
					'\nLogger will be restarted.'
			);
			schedule_restart();
		} else if (status === 'terminated') {
			schedule_restart();
		} else {
			alert('Unknown status: ' + status);
		}
	};

	onMount(async () => {
		await try_restore_recovery_snapshot();
		config = await get_config();
		await start_analyze_logger('initial');
	});
	onDestroy(() => {
		is_destroyed = true;
		if (recovery_flush_timeout !== null) {
			window.clearTimeout(recovery_flush_timeout);
			recovery_flush_timeout = null;
		}
		if (logs.length > 0) {
			write_recovery_snapshot().catch((error) => console.error(error));
		}
		stop_logger().catch((error) => console.error(error));
	});
</script>

<Logger {logs} on:saved={handle_logs_saved} />
