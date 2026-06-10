<script lang="ts">
	import Button from '../../svelte-ui/elements/button.svelte';
	import { start_logger, stop_logger, type LoggerCallback } from '../../logic/logger-wrapper';
	import Logger from '../../components/create-config/logger.svelte';
	import { open_file } from '../../logic/file';
	import {
		get_config,
		parse_analyzer_output_line,
		type Log,
		type LogType
	} from '../../components/create-config/config';
	import { filesystem } from '@neutralinojs/lib';
	import { onDestroy } from 'svelte';
	import LogEditor from '../../components/create-config/log-editor.svelte';
	import { clear_exit_guard_state, set_exit_guard_state } from '../../logic/navigation-guard';
	let logs: LogType[] = [];
	let combat_logs: Log[] = [];
	let loading = false;
	let pcap_progress_current = 0;
	let pcap_progress_total = 0;
	let pcap_progress_percent = 0;
	let stopping_replay = false;
	let has_active_separate_pcap = false;
	let logger_component: {
		stop_active_pcap_capture_for_exit?: () => Promise<void>;
		has_active_pcap_capture?: () => boolean;
	} | null = null;

	let is_network = false;

	const log_regex =
		/^\[(?<time>[^\]]+)\]\s+(?<player_one>.+?)\s+(?<verb>died to|has killed)\s+(?<player_two>.+?)\s+from\s+(?<guild>.+?)(?:\s+\((?<family_one>[^,]+),(?<family_two>[^)]+)\))?$/u;

	const logger_callback: LoggerCallback = (data, status) => {
		if (status === 'running') {
			if (data.startsWith('PCAP_TOTAL ')) {
				const total = Number.parseInt(data.replace('PCAP_TOTAL ', '').trim(), 10);
				if (!Number.isNaN(total) && total >= 0) {
					pcap_progress_total = total;
				}
				return;
			}

			if (data.startsWith('PCAP_PROGRESS ')) {
				const parts = data.trim().split(/\s+/);
				if (parts.length >= 2) {
					const current = Number.parseInt(parts[1], 10);
					const total = parts.length >= 3 ? Number.parseInt(parts[2], 10) : 0;
					if (!Number.isNaN(current) && current >= 0) {
						pcap_progress_current = current;
					}
					if (!Number.isNaN(total) && total >= 0) {
						pcap_progress_total = total;
					}
				}
				return;
			}

			const new_log = parse_analyzer_output_line(data);
			if (new_log) {
				if (logs.find((log) => log.hex === new_log.hex && log.time === new_log.time)) {
					return;
				}

				logs.push(new_log);
				logs = logs;
			}
		} else if (status === ('error' as any)) {
			console.error(data);
			loading = false;
		} else if (status === 'terminated') {
			loading = false;
		}
	};

	$: pcap_progress_percent =
		pcap_progress_total > 0
			? Math.min(100, Math.floor((pcap_progress_current / pcap_progress_total) * 100))
			: 0;

	async function open_pcap() {
		logs = [];
		combat_logs = [];
		has_active_separate_pcap = false;
		pcap_progress_current = 0;
		pcap_progress_total = 0;
		const filePaths = await open_file();
		if (!filePaths || filePaths.length === 0) return;
		const config = await get_config();
		if (filePaths[0].includes('.txt') || filePaths[0].includes('.log')) {
			const filePath = filePaths[0];
			is_network = false;
			let data = await filesystem.readFile(filePath);
			if (!data) return;
			logs = [];
			const lines = data.split(/\r?\n/);
			for (const line of lines) {
				const match = line.trim().match(log_regex);
				if (match && match.groups) {
					const new_combat_log: Log = {
						time: match.groups.time,
						names: [
							match.groups.player_one,
							match.groups.player_two,
							match.groups.guild,
							match.groups.family_one ?? '',
							match.groups.family_two ?? ''
						],
						kill: match.groups.verb === 'has killed'
					};
					combat_logs.push(new_combat_log);
				}
			}
			combat_logs = combat_logs;
		} else {
			is_network = true;
			start_logger(
				logger_callback,
				'analyze',
				// Always disable IP filter for PCAP replay: transient ExitLag relay IPs
				// from the original capture session are not available at replay time.
				'-f ' + '"' + filePaths + '"' + ' --no-ipFilter'
			);
			loading = true;
		}
	}

	async function stop_active_separate_pcap_for_exit() {
		if (!logger_component?.stop_active_pcap_capture_for_exit) {
			return;
		}

		await logger_component.stop_active_pcap_capture_for_exit();
		has_active_separate_pcap = false;
	}

	function handle_pcap_recording_change(event: CustomEvent<{ recording: boolean }>) {
		has_active_separate_pcap = event.detail.recording === true;
	}

	$: set_exit_guard_state({
		has_log_entries: logs.length > 0 || combat_logs.length > 0,
		has_active_separate_pcap,
		stop_active_separate_pcap: stop_active_separate_pcap_for_exit
	});

	async function stop_pcap_replay() {
		if (!loading || stopping_replay) {
			return;
		}

		stopping_replay = true;
		try {
			await stop_logger();
		} catch (error) {
			console.error(error);
		} finally {
			loading = false;
			stopping_replay = false;
		}
	}

	onDestroy(() => {
		clear_exit_guard_state();
		stop_logger().catch((error) => console.error(error));
	});
</script>

<div class="flex flex-col gap-2 h-full min-h-0">
	<div class="shrink-0 flex flex-wrap gap-2">
		<Button class="w-full sm:flex-1" on:click={open_pcap}>Open File</Button>
		{#if is_network && loading}
			<Button class="w-full sm:w-32" on:click={stop_pcap_replay} disabled={stopping_replay}
				>Stop Replay</Button
			>
		{/if}
	</div>
	{#if is_network && loading}
		<div class="w-full rounded-lg border border-gray-700 bg-gray-900/70 px-3 py-2">
			<div class="mb-1 flex items-center justify-between text-xs text-gray-300">
				<span>Reading PCAP...</span>
				{#if pcap_progress_total > 0}
					<span>{pcap_progress_percent}% ({pcap_progress_current}/{pcap_progress_total})</span>
				{:else if pcap_progress_current > 0}
					<span>{pcap_progress_current} packets</span>
				{/if}
			</div>
			<div class="h-2 w-full overflow-hidden rounded bg-gray-700">
				<div
					class="h-full bg-gold transition-all duration-150"
					style={`width:${pcap_progress_total > 0 ? pcap_progress_percent : 0}%`}
				></div>
			</div>
		</div>
	{/if}
	<div class="flex-1 min-h-0">
		{#if is_network}
			<Logger
				bind:this={logger_component}
				{logs}
				{loading}
				on:pcapRecordingChange={handle_pcap_recording_change}
			/>
		{:else}
			<LogEditor logs={combat_logs} {loading} />
		{/if}
	</div>
</div>
