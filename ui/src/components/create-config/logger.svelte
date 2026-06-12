<script lang="ts">
	import VirtualList from '@sveltejs/svelte-virtual-list';
	import { open_pcap_save_location, open_save_location } from '../../logic/file';
	import LoadingIndicator from '../../svelte-ui/elements/loading-indicator.svelte';
	import IoMdSettings from 'svelte-icons/io/IoMdSettings.svelte';
	import { find_all_indices } from '../../svelte-ui/util';
	import Button from '../../svelte-ui/elements/button.svelte';
	import Checkbox from '../../svelte-ui/elements/checkbox.svelte';
	import ConfigModal from './config.modal.svelte';
	import {
		build_calibrated_config,
		calculate_kd,
		update_config,
		type Config,
		type CalibrationSelection,
		type LogType,
		get_date,
		get_formatted_date,
		get_config,
		get_log_name_at_offset,
		is_valid_combat_name,
		PERSONAL_FAMILY_NAME_KEY
	} from '../../components/create-config/config';
	import { events, filesystem, os, storage } from '@neutralinojs/lib';
	import {
		quote_logger_argument,
		spawn_parallel_logger,
		stop_spawned_logger,
		stop_logger
	} from '../../logic/logger-wrapper';
	import { createEventDispatcher, onDestroy, onMount } from 'svelte';
	import { ModalManager } from '../../svelte-ui/modal/modal-store';
	import Icon from '../../svelte-ui/elements/icon.svelte';
	import Select from './select.svelte';
	import { dev } from '$app/environment';
	import GuildInfos from './guild-infos.svelte';
	import { show_toast } from '../../svelte-ui/util';
	import { get_runtime_path } from '../../logic/runtime-path';

	interface $$Props {
		logs: LogType[];
		loading?: boolean;
	}

	export let logs: LogType[];
	export let loading = false;

	const dispatch = createEventDispatcher<{
		saved: void;
		pcapRecordingChange: { recording: boolean };
	}>();

	let possible_name_offsets: { offset: number; count: number }[][] = [];
	let name_indices: number[] = [0, 0, 0, 0, 0];

	let player_one_index = 0;
	let player_two_index = 1;
	let guild_index = 2;
	let indices_auto_detected = false;

	let possible_kill_offsets: number[] = [];
	let kill_index = 0;

	let config: Config;
	let auto_scroll = true;
	let is_destroyed = false;
	let list_height = 0;
	let invert_combat_direction = false;
	let show_invalid_logs = false;
	let show_partial_logs = false;
	let show_only_partial_logs = false;
	let auto_revealed_incomplete_logs = false;
	let invalid_log_count = 0;
	let partial_log_count = 0;
	let displayed_logs: LogType[] = [];
	let manual_role_names: Record<
		string,
		Partial<Record<'player_one' | 'player_two' | 'guild', string>>
	> = {};
	const personal_stats_storage_key = PERSONAL_FAMILY_NAME_KEY;
	let personal_family_name = '';

	let incident_count = 0;
	let incident_poll_interval: number | null = null;
	let incident_session_start_unix = 0;
	let list_needs_remount = 0;
	let pcap_recording = false;
	let pcap_capture_process_id: number | null = null;
	let pcap_capture_output = '';
	let pcap_stop_requested = false;

	export function has_active_pcap_capture() {
		return pcap_recording;
	}

	export async function stop_active_pcap_capture_for_exit() {
		await stop_pcap_capture(true);
	}

	$: dispatch('pcapRecordingChange', { recording: pcap_recording });

	function get_incidents_path() {
		const today_iso = new Date().toISOString().slice(0, 10);
		return get_runtime_path(`logger\\.tmp\\${today_iso}.log.incidents.jsonl`);
	}

	function should_include_incident(parsed: { packet_time?: number; reason?: string }) {
		if (
			typeof parsed.packet_time !== 'number' ||
			parsed.packet_time < incident_session_start_unix
		) {
			return false;
		}

		return (
			parsed.reason !== 'analyze-duplicate-suppressed' &&
			parsed.reason !== 'analyze-relaxed-duplicate-suppressed'
		);
	}

	function get_session_incident_lines(content: string) {
		const lines = content
			.split(/\r?\n/)
			.map((line) => line.trim())
			.filter((line) => line.length > 0);

		return lines.filter((line) => {
			try {
				const parsed = JSON.parse(line) as { packet_time?: number; reason?: string };
				return should_include_incident(parsed);
			} catch {
				// Keep malformed lines out of per-session counters/exports.
			}
			return false;
		});
	}

	async function poll_incidents() {
		try {
			const content = await filesystem.readFile(get_incidents_path());
			incident_count = get_session_incident_lines(content).length;
		} catch {
			incident_count = 0;
		}
	}

	onMount(async () => {
		incident_session_start_unix = Date.now() / 1000;
		config = await get_config();
		possible_kill_offsets = [typeof config.kill === 'number' ? config.kill : 0];
		seed_possible_name_offsets_from_config();
		indices_auto_detected = false;
		if (logs.length > 0) {
			await calculate_config();
		}
		auto_scroll = config.auto_scroll;
		personal_family_name = await storage.getData(personal_stats_storage_key).catch(() => '');
		await poll_incidents();
		incident_poll_interval = window.setInterval(poll_incidents, 5000);
	});

	onMount(() => {
		const update_list_dimensions = () => {
			list_height = window.innerHeight;
			list_needs_remount += 1;
		};
		const window_size_observer =
			typeof ResizeObserver !== 'undefined'
				? new ResizeObserver(() => update_list_dimensions())
				: null;

		window.requestAnimationFrame(update_list_dimensions);
		window.addEventListener('resize', update_list_dimensions);
		window_size_observer?.observe(document.documentElement);

		return () => {
			window_size_observer?.disconnect();
			window.removeEventListener('resize', update_list_dimensions);
		};
	});

	onDestroy(() => {
		is_destroyed = true;
		if (incident_poll_interval) window.clearInterval(incident_poll_interval);
		if (pcap_recording) {
			stop_pcap_capture(true).catch((error) => console.error(error));
		}
		stop_logger().catch((error) => console.error(error));
	});

	function normalize_pcap_base_path(path: string) {
		const trimmed = path.trim();
		if (trimmed.toLowerCase().endsWith('.pcap')) {
			return trimmed.slice(0, -5);
		}

		return trimmed;
	}

	function handle_parallel_pcap_process(evt: CustomEvent) {
		if (!pcap_capture_process_id || Number(evt.detail.id) !== Number(pcap_capture_process_id)) {
			return;
		}

		switch (evt.detail.action) {
			case 'stdErr':
				show_toast('PCAP recorder reported an error. Check logger output.', 'error');
				console.error('PCAP recorder stderr:', evt.detail.data);
				break;
			case 'exit':
				pcap_recording = false;
				pcap_capture_process_id = null;
				if (!is_destroyed) {
					if (pcap_stop_requested) {
						show_toast('PCAP capture stopped and saved.', 'success');
					} else {
						show_toast('PCAP recorder stopped unexpectedly.', 'error');
					}
				}
				pcap_stop_requested = false;
				break;
		}
	}

	async function start_pcap_capture() {
		if (pcap_recording) {
			return;
		}

		const chosen = await open_pcap_save_location(get_formatted_date(get_date()) + '.pcap');
		if (!chosen) {
			return;
		}

		const output_base = normalize_pcap_base_path(chosen);
		if (!output_base) {
			show_toast('Invalid capture path.', 'error');
			return;
		}

		const iface_args: string[] = [];
		if (config?.all_interfaces) {
			iface_args.push('-i');
		} else if (config?.interface_name) {
			iface_args.push('--interface', quote_logger_argument(config.interface_name));
		}
		if (config?.ip_filter) {
			iface_args.push('-p');
		}
		const recorder_args = `-r -o ${quote_logger_argument(output_base)}${iface_args.length > 0 ? ' ' + iface_args.join(' ') : ''}`;
		const spawned = await spawn_parallel_logger(recorder_args);
		pcap_capture_process_id = Number(spawned.id);
		pcap_capture_output = `${output_base}.pcap`;
		pcap_recording = true;
		pcap_stop_requested = false;
		show_toast('Separate PCAP capture started.', 'success');
	}

	async function stop_pcap_capture(silent = false) {
		if (!pcap_recording || !pcap_capture_process_id) {
			return;
		}

		pcap_stop_requested = true;
		const process_id = pcap_capture_process_id;
		try {
			await stop_spawned_logger(process_id);
		} catch (error) {
			pcap_recording = false;
			pcap_capture_process_id = null;
			pcap_stop_requested = false;
			if (!silent) {
				show_toast('Failed to stop PCAP capture cleanly.', 'error');
			}
			console.error(error);
		}
	}

	onMount(() => {
		events.on('spawnedProcess', handle_parallel_pcap_process);
	});

	onDestroy(() => {
		events.off('spawnedProcess', handle_parallel_pcap_process);
	});

	$: {
		auto_scroll;
		config && update_config({ ...config, auto_scroll });
	}

	$: {
		if (logs.length > 0) {
			logs_changed();
		} else {
			scroll(true);
		}
	}

	function logs_changed() {
		auto_scroll && setTimeout(scroll);
		auto_reveal_incomplete_logs_if_needed();

		if (logs.length < 50 || logs.length % 100 === 0) {
			refresh_kill_offsets(logs);
			void calculate_config();
		}
	}

	function auto_reveal_incomplete_logs_if_needed() {
		if (auto_revealed_incomplete_logs || logs.length === 0) {
			if (logs.length === 0) {
				auto_revealed_incomplete_logs = false;
			}
			return;
		}

		let has_complete = false;
		let has_incomplete = false;
		for (const log of logs) {
			const state = get_log_completion_state(log);
			if (state === 'complete') {
				has_complete = true;
				break;
			}
			if (state === 'partial' || state === 'invalid') {
				has_incomplete = true;
			}
		}

		if (!has_complete && has_incomplete) {
			show_partial_logs = true;
			show_invalid_logs = true;
			auto_revealed_incomplete_logs = true;
			show_toast('Showing partial/invalid rows automatically (no complete rows yet).', 'info');
		}
	}

	function refresh_kill_offsets(source_logs: LogType[]) {
		const recalculated_candidates = find_kill_offset(source_logs);
		const recalculated_offsets = recalculated_candidates.map((entry) => entry.offset);
		const selected_kill_offset = possible_kill_offsets[kill_index];
		const configured_kill_offset = typeof config?.kill === 'number' ? config.kill : null;
		const pinned_kill_offset =
			typeof selected_kill_offset === 'number' && selected_kill_offset > 0
				? selected_kill_offset
				: configured_kill_offset;

		if (recalculated_offsets.length === 0) {
			if (
				typeof pinned_kill_offset === 'number' &&
				pinned_kill_offset > 0 &&
				!possible_kill_offsets.includes(pinned_kill_offset)
			) {
				possible_kill_offsets = [pinned_kill_offset, ...possible_kill_offsets];
				kill_index = 0;
			}
			return;
		}

		possible_kill_offsets = recalculated_offsets;

		if (
			typeof pinned_kill_offset === 'number' &&
			pinned_kill_offset > 0 &&
			possible_kill_offsets.includes(pinned_kill_offset)
		) {
			kill_index = possible_kill_offsets.indexOf(pinned_kill_offset);
			return;
		}

		if (kill_index >= possible_kill_offsets.length) {
			kill_index = 0;
		}
	}

	function seed_possible_name_offsets_from_config() {
		const seeded = [
			[{ offset: config.player_one, count: 1 }],
			[{ offset: config.player_two, count: 1 }],
			[{ offset: config.guild, count: 1 }],
			[],
			[]
		];

		if (possible_name_offsets.length === 0) {
			possible_name_offsets = seeded;
			return;
		}

		possible_name_offsets = seeded.map((seeded_list, index) => {
			const existing = possible_name_offsets[index] ?? [];
			const seeded_entry = seeded_list[0];

			if (!seeded_entry) {
				return [...existing];
			}

			if (existing.some((entry) => entry.offset === seeded_entry.offset)) {
				return [...existing];
			}

			return [seeded_entry, ...existing];
		});
	}

	async function calculate_config(auto_persist = true) {
		possible_name_offsets = possible_name_offsets.map((list) =>
			list.map((n) => ({ ...n, count: 0 }))
		);
		// get all offsets for each name and count how many times they appear
		for (const log of logs) {
			for (let i = 0; i < log.names.length; i++) {
				const name = log.names[i];
				if (possible_name_offsets[i]) {
					const index = possible_name_offsets[i].findIndex((n) => n.offset === name.offset);
					if (index !== -1) {
						possible_name_offsets[i][index].count++;
					} else {
						possible_name_offsets[i].push({ offset: name.offset, count: 1 });
					}
				} else {
					possible_name_offsets[i] = [{ offset: name.offset, count: 1 }];
				}
			}
		}

		// sort by number of times they appear
		for (let i = 0; i < possible_name_offsets.length; i++) {
			possible_name_offsets[i] = possible_name_offsets[i].sort((a, b) => b.count - a.count);
		}

		// Auto-detect slot assignments from config offsets (once per session)
		if (!indices_auto_detected && config && possible_name_offsets.some((s) => s.length > 0)) {
			const find_best_slot = (target_offset: number) => {
				let best = -1;
				let best_count = 0;
				for (let i = 0; i < possible_name_offsets.length; i++) {
					const entry = possible_name_offsets[i].find((e) => e.offset === target_offset);
					if (entry && entry.count > best_count) {
						best = i;
						best_count = entry.count;
					}
				}
				return best;
			};
			const p1 = find_best_slot(config.player_one);
			const p2 = find_best_slot(config.player_two);
			const g = find_best_slot(config.guild);
			if (p1 !== -1) player_one_index = p1;
			if (p2 !== -1) player_two_index = p2;

			const can_use_slot = (slot: number) =>
				slot >= 0 &&
				slot < possible_name_offsets.length &&
				possible_name_offsets[slot]?.length > 0 &&
				slot !== player_one_index &&
				slot !== player_two_index;

			let guild_slot_assigned = false;
			if (g !== -1 && can_use_slot(g)) {
				guild_index = g;
				guild_slot_assigned = true;
			}

			if (!guild_slot_assigned) {
				for (const preferred_slot of [2, 3]) {
					if (can_use_slot(preferred_slot)) {
						guild_index = preferred_slot;
						guild_slot_assigned = true;
						break;
					}
				}
			}

			if (!guild_slot_assigned) {
				for (let i = 0; i < possible_name_offsets.length; i++) {
					if (can_use_slot(i)) {
						guild_index = i;
						guild_slot_assigned = true;
						break;
					}
				}
			}

			if (p1 !== -1 && p2 !== -1 && guild_slot_assigned) {
				indices_auto_detected = true;
			}
		}

		if (auto_persist) {
			await persist_selected_config();
		}
	}

	async function persist_selected_config() {
		const next_config = build_calibrated_config(config, logs, {
			possible_name_offsets,
			name_indices,
			player_one_index,
			player_two_index,
			guild_index,
			possible_kill_offsets,
			kill_index
		} satisfies CalibrationSelection);

		if (!next_config) {
			return;
		}

		config = await update_config(next_config);
	}

	function remap_loaded_logs_from_selected_offsets() {
		if (!logs.length) {
			return;
		}

		const selected_offsets = [
			possible_name_offsets[player_one_index]?.[name_indices[player_one_index]]?.offset,
			possible_name_offsets[player_two_index]?.[name_indices[player_two_index]]?.offset,
			possible_name_offsets[guild_index]?.[name_indices[guild_index]]?.offset
		].filter((offset): offset is number => typeof offset === 'number' && Number.isFinite(offset));

		if (selected_offsets.length === 0) {
			return;
		}

		logs = logs.map((log) => {
			let next_names = [...log.names];

			for (const offset of selected_offsets) {
				const resolved_name = get_log_name_at_offset({ ...log, names: next_names }, offset);
				const existing_index = next_names.findIndex((entry) => entry.offset === offset);

				if (existing_index !== -1) {
					next_names[existing_index] = {
						...next_names[existing_index],
						name: resolved_name
					};
				} else {
					next_names = [...next_names, { name: resolved_name, offset }];
				}
			}

			return {
				...log,
				names: next_names
			};
		});
	}

	$: get_name_options = (i: number, log: LogType) => {
		const names = possible_name_offsets
			/* .filter((_, index) => index !== i) */
			.map((list, index) => {
				const selected = name_indices[index];
				const entry = list?.[selected] ?? list?.[0];
				if (typeof entry?.offset !== 'number') {
					return '';
				}
				const resolved = get_log_name_at_offset(log, entry.offset);
				return is_valid_combat_name(resolved) ? resolved : '';
			});
		return names;
	};

	$: get_name_option_disabled = (i: number, log: LogType) => {
		const names = get_name_options(i, log);
		return names.map((name) => !is_valid_combat_name(name));
	};

	$: get_name = (i: number, log: LogType) => {
		const list = possible_name_offsets[i];
		const selected = name_indices[i];
		const entry = list?.[selected] ?? list?.[0];
		return typeof entry?.offset === 'number' ? get_log_name_at_offset(log, entry.offset) : '';
	};

	function get_selected_offset(slot_index: number) {
		const list = possible_name_offsets[slot_index];
		const selected = name_indices[slot_index];
		const entry = list?.[selected] ?? list?.[0];
		return typeof entry?.offset === 'number' ? entry.offset : undefined;
	}

	function get_log_key(log: LogType) {
		return `${log.time}|${log.hex}`;
	}

	function can_drop_log(log: LogType) {
		return get_log_completion_state(log) !== 'complete';
	}

	function drop_log_row(log: LogType) {
		if (!can_drop_log(log)) {
			return;
		}

		const index = logs.indexOf(log);
		if (index === -1) {
			return;
		}

		logs = [...logs.slice(0, index), ...logs.slice(index + 1)];

		const key = get_log_key(log);
		if (manual_role_names[key]) {
			const next = { ...manual_role_names };
			delete next[key];
			manual_role_names = next;
		}
	}

	function get_manual_role_name(log: LogType, role: 'player_one' | 'player_two' | 'guild') {
		const key = get_log_key(log);
		return manual_role_names[key]?.[role] ?? '';
	}

	function get_role_index(role: 'player_one' | 'player_two' | 'guild') {
		return role === 'player_one'
			? player_one_index
			: role === 'player_two'
				? player_two_index
				: guild_index;
	}

	function set_manual_role_name(
		log: LogType,
		role: 'player_one' | 'player_two' | 'guild',
		value: string
	) {
		const key = get_log_key(log);
		const normalized = String(value ?? '').trim();
		const existing = manual_role_names[key] ?? {};

		if (!normalized) {
			if (!(role in existing)) {
				return;
			}

			const next_entry = { ...existing };
			delete next_entry[role];
			const next = { ...manual_role_names };
			if (Object.keys(next_entry).length === 0) {
				delete next[key];
			} else {
				next[key] = next_entry;
			}
			manual_role_names = next;
			return;
		}

		manual_role_names = {
			...manual_role_names,
			[key]: {
				...existing,
				[role]: normalized
			}
		};
	}

	function get_role_name(role: 'player_one' | 'player_two' | 'guild', log: LogType) {
		const manual_value = get_manual_role_name(log, role);
		if (manual_value.length > 0) {
			return manual_value;
		}

		const role_index = get_role_index(role);
		const selected_role_name = get_name(role_index, log);
		if (is_valid_combat_name(selected_role_name)) {
			return selected_role_name;
		}

		return '';
	}

	function get_partial_fill_candidates(role: 'player_one' | 'player_two' | 'guild', log: LogType) {
		const current = get_manual_role_name(log, role);
		const taken = new Set(
			(['player_one', 'player_two', 'guild'] as const)
				.filter((entry_role) => entry_role !== role)
				.map((entry_role) => get_role_name(entry_role, log))
				.filter((name) => is_valid_combat_name(name))
		);

		const options = Array.from(
			new Set(
				log.names
					.map((entry) => String(entry.name ?? '').trim())
					.filter((name) => is_valid_combat_name(name) && !taken.has(name))
			)
		);

		if (current && !options.includes(current)) {
			options.unshift(current);
		}

		return options;
	}

	function apply_partial_fill_candidate(
		role: 'player_one' | 'player_two' | 'guild',
		log: LogType,
		e: Event
	) {
		const selected = (e.target as HTMLSelectElement).value;
		set_manual_role_name(log, role, selected);
	}

	function should_show_manual_input(role: 'player_one' | 'player_two' | 'guild', log: LogType) {
		if (get_log_completion_state(log) !== 'partial') {
			return false;
		}

		const manual_value = get_manual_role_name(log, role);
		if (manual_value.length > 0) {
			return true;
		}
		return !is_valid_combat_name(get_role_name(role, log));
	}

	function should_show_partial_fill_select(
		role: 'player_one' | 'player_two' | 'guild',
		log: LogType
	) {
		if (!should_show_manual_input(role, log)) {
			return false;
		}
		return get_partial_fill_candidates(role, log).length > 0;
	}

	function get_export_value(name: string, placeholder: string) {
		return is_valid_combat_name(name) ? name : placeholder;
	}

	function get_export_character_names(log: LogType) {
		const player_one_offset = get_selected_offset(player_one_index);
		const player_two_offset = get_selected_offset(player_two_index);
		const guild_offset = get_selected_offset(guild_index);
		const selected_offsets = new Set(
			[player_one_offset, player_two_offset, guild_offset].filter(
				(offset): offset is number => typeof offset === 'number' && Number.isFinite(offset)
			)
		);

		const remaining_entries = log.names
			.filter((entry) => !selected_offsets.has(entry.offset))
			.map((entry) => ({
				name: String(entry.name ?? '').trim(),
				offset: entry.offset
			}))
			.filter((entry) => is_valid_combat_name(entry.name));

		if (
			typeof player_one_offset !== 'number' ||
			typeof player_two_offset !== 'number' ||
			!Number.isFinite(player_one_offset) ||
			!Number.isFinite(player_two_offset) ||
			player_one_offset === player_two_offset
		) {
			return remaining_entries.map((entry) => entry.name);
		}

		const player_one_names: string[] = [];
		const player_two_names: string[] = [];
		const unassigned_names: string[] = [];

		for (const entry of remaining_entries) {
			const distance_to_player_one = Math.abs(entry.offset - player_one_offset);
			const distance_to_player_two = Math.abs(entry.offset - player_two_offset);

			if (distance_to_player_one < distance_to_player_two) {
				player_one_names.push(entry.name);
			} else if (distance_to_player_two < distance_to_player_one) {
				player_two_names.push(entry.name);
			} else {
				unassigned_names.push(entry.name);
			}
		}

		return [...player_one_names, ...player_two_names, ...unassigned_names];
	}

	function get_log_completion_state(log: LogType) {
		const player_one_name = get_role_name('player_one', log);
		const player_two_name = get_role_name('player_two', log);
		const guild_name = get_role_name('guild', log);
		const core_names = [player_one_name, player_two_name, guild_name];
		const valid_core_names = core_names.filter((value) => is_valid_combat_name(value));
		const valid_core_count = valid_core_names.length;
		const unique_valid_core_count = new Set(valid_core_names).size;

		if (valid_core_count === 3 && unique_valid_core_count === 3) {
			return 'complete' as const;
		}
		// Treat only one-missing-core records as partial.
		if (valid_core_count === 2) {
			return 'partial' as const;
		}
		return 'invalid' as const;
	}

	function should_include_character_name(name: string) {
		return is_valid_combat_name(name);
	}

	function find_kill_offset(logs: LogType[]) {
		const all_indices: number[] = [];
		for (const log of logs) {
			let indices = find_all_indices(log.hex, '01');
			indices = indices.filter((index) =>
				log.names.every((n) => index > n.offset + 64 || index < n.offset)
			);
			all_indices.push(...indices);
		}
		const possible_kill_offsets = new Map<number, number>();
		for (const log of logs) {
			for (const index of all_indices) {
				if (log.hex.slice(index, index + 2) === '00') {
					if (possible_kill_offsets.has(index)) {
						possible_kill_offsets.set(index, possible_kill_offsets.get(index)! + 1);
					} else {
						possible_kill_offsets.set(index, 1);
					}
				}
			}
		}
		// creates array sorted by value
		const sorted = Array.from(possible_kill_offsets.entries())
			.sort((a, b) => b[1] - a[1])
			.map(([offset, count]) => ({ offset: offset + 1, count }));

		return sorted;
	}

	function is_kill_log(log: LogType) {
		const kill_offset = possible_kill_offsets[kill_index];
		if (typeof kill_offset !== 'number') {
			return false;
		}

		const marker = log.hex[kill_offset];
		return marker === '1';
	}

	function is_own_kill(log: LogType) {
		return invert_combat_direction ? !is_kill_log(log) : is_kill_log(log);
	}

	function toggle_kill_direction() {
		invert_combat_direction = !invert_combat_direction;
		logs = [...logs];
	}

	function get_display_combat(log: LogType) {
		const player_one_name = get_role_name('player_one', log);
		const player_two_name = get_role_name('player_two', log);
		const kill = is_own_kill(log);

		if (!invert_combat_direction) {
			return {
				left: player_one_name,
				verb: kill ? 'has killed' : 'died to',
				right: player_two_name,
				isKill: kill
			};
		}

		return {
			left: player_two_name,
			verb: kill ? 'died to' : 'has killed',
			right: player_one_name,
			isKill: !kill
		};
	}

	function should_display_log(log: LogType) {
		const state = get_log_completion_state(log);
		if (show_only_partial_logs) {
			return state === 'partial';
		}
		if (state === 'complete') {
			return true;
		}
		if (state === 'partial') {
			return show_partial_logs;
		}
		return show_invalid_logs;
	}

	$: {
		logs;
		manual_role_names;
		player_one_index;
		player_two_index;
		guild_index;

		invalid_log_count = logs.reduce(
			(count, log) => count + (get_log_completion_state(log) === 'invalid' ? 1 : 0),
			0
		);
		partial_log_count = logs.reduce(
			(count, log) => count + (get_log_completion_state(log) === 'partial' ? 1 : 0),
			0
		);
	}

	$: {
		logs;
		show_invalid_logs;
		show_partial_logs;
		show_only_partial_logs;
		manual_role_names;
		player_one_index;
		player_two_index;
		guild_index;

		displayed_logs = logs.filter((log) => should_display_log(log));
	}

	function update_names(target: 'player_one' | 'player_two' | 'guild', e: Event) {
		indices_auto_detected = true; // Prevent auto-detection from overriding manual changes
		if (target === 'player_one') {
			const new_value = parseInt((e.target as HTMLSelectElement).value);
			if (new_value === player_two_index) {
				player_two_index = player_one_index;
			} else if (new_value === guild_index) {
				guild_index = player_one_index;
			}
			player_one_index = new_value;
		} else if (target === 'player_two') {
			const new_value = parseInt((e.target as HTMLSelectElement).value);
			if (new_value === player_one_index) {
				player_one_index = player_two_index;
			} else if (new_value === guild_index) {
				guild_index = player_two_index;
			}
			player_two_index = new_value;
		} else if (target === 'guild') {
			const new_value = parseInt((e.target as HTMLSelectElement).value);
			if (new_value === player_one_index) {
				player_one_index = guild_index;
			} else if (new_value === player_two_index) {
				player_two_index = guild_index;
			}
			guild_index = new_value;
		}
	}

	function parse_log_stats(log: LogType) {
		const killer = is_own_kill(log)
			? get_role_name('player_one', log)
			: get_role_name('player_two', log);
		const victim = is_own_kill(log)
			? get_role_name('player_two', log)
			: get_role_name('player_one', log);
		return { killer, victim };
	}

	function update_personal_family_name(value: string) {
		personal_family_name = value;
		storage.setData(personal_stats_storage_key, personal_family_name).catch(() => null);
	}

	function handle_personal_family_name_input(e: Event) {
		update_personal_family_name((e.currentTarget as HTMLInputElement).value);
	}

	function scroll(top?: boolean) {
		const container = document.querySelector('svelte-virtual-list-viewport');
		if (container && !top) {
			container.scrollTop = container.scrollHeight;
		} else if (container) {
			container.scrollTop = 0;
		}
	}

	function correct_scroll_after_filter_toggle(force_top = false) {
		window.requestAnimationFrame(() => {
			const container = document.querySelector('svelte-virtual-list-viewport');
			if (!container) {
				return;
			}

			if (force_top) {
				container.scrollTop = 0;
				return;
			}

			const max_scroll_top = Math.max(0, container.scrollHeight - container.clientHeight);
			if (auto_scroll) {
				container.scrollTop = max_scroll_top;
				return;
			}

			if (container.scrollTop > max_scroll_top) {
				container.scrollTop = max_scroll_top;
			}
		});
	}

	function get_logs_string() {
		let output = '';
		const version_stamp = `# ikusa-logger version: ${NL_APPVERSION}`;
		const filtered_logs = logs.filter((log) => should_display_log(log));
		const logs_to_export = filtered_logs.length > 0 ? filtered_logs : logs;

		for (const log of logs_to_export) {
			let characters = '';

			const combat = get_display_combat(log);
			const guild_name = get_role_name('guild', log);
			const state = get_log_completion_state(log);
			const left = get_export_value(combat.left, '<missing-player-one>');
			const right = get_export_value(combat.right, '<missing-player-two>');
			const guild = get_export_value(guild_name, '<missing-guild>');
			let status_prefix = state === 'complete' ? '' : `[${state.toUpperCase()}] `;

			if (config.include_characters) {
				const remaining_names = get_export_character_names(log);
				if (remaining_names.length > 0) {
					characters = ` (${remaining_names.join(',')})`;
				}
			}

			output += `[${log.time}] ${status_prefix}${left} ${combat.verb} ${right} from ${guild}${characters}\n`;
		}

		return `${version_stamp}\n${output}`;
	}

	function build_incident_destination_path(path: string) {
		if (path.toLowerCase().endsWith('.log')) {
			return path.slice(0, -4) + '.incidents.jsonl';
		}

		return path + '.incidents.jsonl';
	}

	async function copy_analyze_incidents_to_save_path(path: string) {
		const today_iso = new Date().toISOString().slice(0, 10);
		const source_candidates = [
			get_runtime_path(`logger\\.tmp\\${today_iso}.log.incidents.jsonl`),
			get_runtime_path(`logger\\.tmp\\${get_formatted_date(get_date())}.log.incidents.jsonl`)
		];

		for (const source of source_candidates) {
			try {
				const content = await filesystem.readFile(source);
				if (!content || !content.trim()) {
					continue;
				}

				const session_lines = get_session_incident_lines(content);
				if (session_lines.length === 0) {
					continue;
				}

				await filesystem.writeFile(
					build_incident_destination_path(path),
					session_lines.join('\n') + '\n'
				);
				return true;
			} catch {
				// Ignore missing source candidates and continue to next path.
			}
		}

		return false;
	}

	async function save_logs() {
		const path = await open_save_location(get_formatted_date(get_date()) + '.log');
		if (!path) {
			return;
		}

		await filesystem.writeFile(path, get_logs_string());
		const copied_incidents = await copy_analyze_incidents_to_save_path(path);
		dispatch('saved');
		if (copied_incidents) {
			show_toast('Incident diagnostics were saved next to the log file.', 'success');
		}
	}

	async function upload() {
		const website = dev ? 'http://localhost:5174' : 'https://ikusa.site';
		const result = await fetch(website + '/api/create', {
			method: 'POST',
			body: get_logs_string(),
			headers: {
				'Content-Type': 'text/plain'
			}
		});

		if (result.status === 200) {
			const id = (await result.json()).id;
			os.open(`${website}/wars?id=${id}`);
		} else {
			console.error(result);
		}
	}

	$: upload_disabled = logs.length === 0 || loading;
	$: save_disabled = (logs.length === 0 && incident_count === 0) || loading;

	$: own_guild_member_count = displayed_logs.reduce((players, log) => {
		const name = get_display_combat(log).left;
		if (!players.includes(name)) {
			players.push(name);
		}
		return players;
	}, [] as string[]).length;

	$: enemy_count = displayed_logs.reduce((players, log) => {
		const name = get_display_combat(log).right;
		if (!players.includes(name)) {
			players.push(name);
		}
		return players;
	}, [] as string[]).length;

	$: alliance_overview = displayed_logs.reduce(
		(acc, log) => {
			if (is_own_kill(log)) {
				acc.own.kills += 1;
				acc.enemy.deaths += 1;
			} else {
				acc.own.deaths += 1;
				acc.enemy.kills += 1;
			}
			return acc;
		},
		{
			own: { kills: 0, deaths: 0 },
			enemy: { kills: 0, deaths: 0 }
		}
	);

	$: personal_stats = (() => {
		const name = personal_family_name.trim();
		if (!name) return { kills: 0, deaths: 0 };
		return displayed_logs.reduce(
			(acc, log) => {
				const { killer, victim } = parse_log_stats(log);
				if (killer === name) acc.kills += 1;
				if (victim === name) acc.deaths += 1;
				return acc;
			},
			{ kills: 0, deaths: 0 }
		);
	})();

	$: ownKillPct = (() => {
		const total = alliance_overview.own.kills + alliance_overview.own.deaths;
		return total > 0 ? (alliance_overview.own.kills / total) * 100 : 0;
	})();

	$: enemyKillPct = (() => {
		const total = alliance_overview.enemy.kills + alliance_overview.enemy.deaths;
		return total > 0 ? (alliance_overview.enemy.kills / total) * 100 : 0;
	})();
</script>

{#if displayed_logs.length > 0}
	<span class="absolute top-2 left-0 right-0 text-center text-gray-400 text-sm"
		>Adjust the Logs to: <b>Family-Name-1</b> kills/died to
		<b>Family-Name-2</b> from <b>Guild</b></span
	>
{/if}
<div class="flex flex-col gap-2 items-center w-full h-full min-h-0 relative">
	<div class="flex flex-wrap gap-2 items-center justify-start w-full px-1 flex-shrink-0">
		<!-- <p class="w-16">Kill offset:</p>-->
		<!-- <Select options={possible_kill_offsets} bind:selected_value={kill_index} /> -->
		<button
			on:click={() => {
				ModalManager.open(GuildInfos, {
					logs: displayed_logs.map((l) => ({
						names: l.names.map((n) => n.name)
					})),
					guild_index,
					player_one_index,
					player_two_index
				});
			}}
			class="flex h-8 cursor-pointer items-center gap-2 rounded-lg bg-gray-700 px-2 text-xs"
		>
			{displayed_logs.length} Logs | ({own_guild_member_count} vs. {enemy_count})
		</button>
		{#if invalid_log_count > 0 || show_invalid_logs}
			<button
				on:click={() => {
					const is_hiding_invalid_logs = show_invalid_logs;
					show_invalid_logs = !show_invalid_logs;
					correct_scroll_after_filter_toggle(is_hiding_invalid_logs);
				}}
				class={`flex h-8 items-center gap-2 rounded-lg px-2 text-xs ${show_invalid_logs ? 'bg-red-800/70 text-red-200' : 'bg-gray-700 text-gray-200'}`}
				title="Invalid logs are hidden by default. Enable this to inspect them."
			>
				{show_invalid_logs ? 'Hide' : 'Show'} invalid logs ({invalid_log_count})
			</button>
		{/if}
		{#if partial_log_count > 0 || show_partial_logs || show_only_partial_logs}
			<button
				on:click={() => {
					show_partial_logs = !show_partial_logs;
					if (!show_partial_logs && show_only_partial_logs) {
						show_only_partial_logs = false;
					}
					correct_scroll_after_filter_toggle();
				}}
				class={`flex h-8 items-center gap-2 rounded-lg px-2 text-xs ${show_partial_logs ? 'bg-yellow-800/70 text-yellow-200' : 'bg-gray-700 text-gray-200'}`}
				title="Partially completed logs have some resolvable names but are missing at least one core field."
			>
				{show_partial_logs ? 'Hide' : 'Show'} partial logs ({partial_log_count})
			</button>
			<button
				on:click={() => {
					show_only_partial_logs = !show_only_partial_logs;
					if (show_only_partial_logs) {
						show_partial_logs = true;
						show_invalid_logs = false;
					}
					correct_scroll_after_filter_toggle();
				}}
				class={`flex h-8 items-center gap-2 rounded-lg px-2 text-xs ${show_only_partial_logs ? 'bg-amber-700/80 text-amber-100' : 'bg-gray-700 text-gray-200'}`}
				title="Render only partial logs."
			>
				{show_only_partial_logs ? 'Show mixed logs' : 'Only partial logs'}
			</button>
		{/if}
		{#if incident_count > 0}
			<span
				class="flex h-8 items-center gap-1 rounded-lg bg-yellow-800/70 px-2 text-xs text-yellow-300"
				title="Packets where the fallback parser was used — review for mis-parsed names"
			>
				⚠ {incident_count} incident{incident_count === 1 ? '' : 's'}
			</span>
		{/if}
		{#if config}
			<span
				class={`flex h-8 items-center rounded-lg px-2 text-xs ${config.diagnostics_enabled ? 'bg-emerald-900/60 text-emerald-300' : 'bg-gray-700 text-gray-300'}`}
				title="Controls whether .diagnostics.jsonl/.diagnostics.summary.json are generated"
			>
				Diagnostics: {config.diagnostics_enabled ? 'ON' : 'OFF'}
			</span>
		{/if}
		<div
			class="ml-0 sm:ml-2 flex h-8 items-center rounded-lg bg-gray-700 px-2 text-xs text-gray-200"
		>
			<Checkbox bind:checked={auto_scroll} class="!mr-1" />
			<span>Auto scroll</span>
		</div>
		<div class="ml-auto flex items-center gap-2 shrink-0">
			<button
				class="shrink-0"
				on:click={() =>
					ModalManager.open(ConfigModal, {
						config: config,
						options: {
							possible_kill_offsets,
							possible_name_offsets,
							name_indices,
							player_one_index,
							player_two_index,
							guild_index,
							kill_index
						},
						onChange: async (options) => {
							const previous_selected_kill_offset = possible_kill_offsets[kill_index];
							possible_kill_offsets = options.possible_kill_offsets;
							possible_name_offsets = options.possible_name_offsets;
							name_indices = options.name_indices;
							player_one_index = options.player_one_index;
							player_two_index = options.player_two_index;
							guild_index = options.guild_index;
							kill_index = options.kill_index;
							config.ips = options.server_ips;
							config.include_characters = options.include_characters;
							remap_loaded_logs_from_selected_offsets();
							await persist_selected_config();
						}
					})}
			>
				<Icon icon={IoMdSettings} />
			</button>
		</div>
	</div>
	<div class="w-full flex flex-row gap-2 min-h-0 flex-1 overflow-x-auto overflow-y-hidden">
		<div
			class="log-panel flex-1 basis-0 min-w-0 min-h-[240px] rounded-lg border border-gray-700 overflow-x-auto overflow-y-hidden p-2 relative h-full"
		>
			{#if loading && displayed_logs.length === 0}
				<div class="absolute inset-0 flex justify-center items-center mb-14">
					<LoadingIndicator />
				</div>
			{:else if displayed_logs.length === 0 && !loading}
				<div class="absolute inset-0 flex items-center justify-center">
					<p class="text-center text-gray-400">Waiting for valid logs...</p>
				</div>
			{/if}
			{#key `${displayed_logs.length === 0}-${list_height}-${list_needs_remount}`}
				<VirtualList items={displayed_logs} let:item={log}>
					<div class="flex gap-2 group py-1 items-center px-1 justify-start w-max min-w-full">
						<p class="text-sm text-gray-400">{log.time}</p>
						{#if get_log_completion_state(log) === 'partial'}
							<span
								class="inline-flex h-5 items-center rounded-md bg-yellow-800/70 px-1.5 text-[9px] font-semibold uppercase tracking-wide text-yellow-200 sm:h-6 sm:px-2 sm:text-[10px]"
								title="Partially completed log"
							>
								<span class="sm:hidden">P</span>
								<span class="hidden sm:inline">PARTIAL</span>
							</span>
						{:else if get_log_completion_state(log) === 'invalid'}
							<span
								class="inline-flex h-5 items-center rounded-md bg-red-800/70 px-1.5 text-[9px] font-semibold uppercase tracking-wide text-red-200 sm:h-6 sm:px-2 sm:text-[10px]"
								title="Invalid log"
							>
								<span class="sm:hidden">I</span>
								<span class="hidden sm:inline">INVALID</span>
							</span>
						{/if}
						<!-- <p>{log.names[player_one_index].name}</p> -->
						{#if should_show_manual_input('player_one', log)}
							<div
								class="flex flex-col gap-1 w-[clamp(6rem,14vw,10rem)] min-w-[6rem] xl:w-[clamp(8rem,22vw,18rem)] xl:min-w-[8rem]"
							>
								{#if should_show_partial_fill_select('player_one', log)}
									<select
										class="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
										value={get_manual_role_name(log, 'player_one')}
										on:change={(e) => apply_partial_fill_candidate('player_one', log, e)}
									>
										<option value="">Select name...</option>
										{#each get_partial_fill_candidates('player_one', log) as option}
											<option value={option}>{option}</option>
										{/each}
									</select>
								{/if}
								<input
									class="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
									placeholder="Family-Name-1"
									value={get_manual_role_name(log, 'player_one')}
									on:input={(e) =>
										set_manual_role_name(
											log,
											'player_one',
											(e.currentTarget as HTMLInputElement).value
										)}
								/>
							</div>
						{:else}
							<Select
								options={get_name_options(player_one_index, log)}
								option_disabled={get_name_option_disabled(player_one_index, log)}
								selected_value={player_one_index}
								class_name="w-[clamp(6rem,14vw,10rem)] min-w-[6rem] xl:w-[clamp(8rem,22vw,18rem)] xl:min-w-[8rem]"
								on_change={(e) => update_names('player_one', e)}
							/>
						{/if}
						<div class="flex justify-center items-center w-20 sm:w-24 text-center">
							<button
								type="button"
								class={`self-center w-full text-center ${get_display_combat(log).isKill ? 'text-submarine-500' : 'text-red-500'} cursor-pointer hover:underline`}
								on:click={toggle_kill_direction}
							>
								{get_display_combat(log).isKill ? 'killed' : 'died to'}
							</button>
						</div>
						{#if should_show_manual_input('player_two', log)}
							<div
								class="flex flex-col gap-1 w-[clamp(6rem,14vw,10rem)] min-w-[6rem] xl:w-[clamp(8rem,22vw,18rem)] xl:min-w-[8rem]"
							>
								{#if should_show_partial_fill_select('player_two', log)}
									<select
										class="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
										value={get_manual_role_name(log, 'player_two')}
										on:change={(e) => apply_partial_fill_candidate('player_two', log, e)}
									>
										<option value="">Select name...</option>
										{#each get_partial_fill_candidates('player_two', log) as option}
											<option value={option}>{option}</option>
										{/each}
									</select>
								{/if}
								<input
									class="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
									placeholder="Family-Name-2"
									value={get_manual_role_name(log, 'player_two')}
									on:input={(e) =>
										set_manual_role_name(
											log,
											'player_two',
											(e.currentTarget as HTMLInputElement).value
										)}
								/>
							</div>
						{:else}
							<Select
								options={get_name_options(player_two_index, log)}
								option_disabled={get_name_option_disabled(player_two_index, log)}
								selected_value={player_two_index}
								class_name="w-[clamp(6rem,14vw,10rem)] min-w-[6rem] xl:w-[clamp(8rem,22vw,18rem)] xl:min-w-[8rem]"
								on_change={(e) => update_names('player_two', e)}
							/>
						{/if}
						<p class="text-sm text-gray-400">from</p>
						{#if should_show_manual_input('guild', log)}
							<div
								class="flex flex-col gap-1 w-[clamp(6rem,14vw,10rem)] min-w-[6rem] xl:w-[clamp(8rem,22vw,18rem)] xl:min-w-[8rem]"
							>
								{#if should_show_partial_fill_select('guild', log)}
									<select
										class="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
										value={get_manual_role_name(log, 'guild')}
										on:change={(e) => apply_partial_fill_candidate('guild', log, e)}
									>
										<option value="">Select guild...</option>
										{#each get_partial_fill_candidates('guild', log) as option}
											<option value={option}>{option}</option>
										{/each}
									</select>
								{/if}
								<input
									class="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
									placeholder="Guild"
									value={get_manual_role_name(log, 'guild')}
									on:input={(e) =>
										set_manual_role_name(log, 'guild', (e.currentTarget as HTMLInputElement).value)}
								/>
							</div>
						{:else}
							<Select
								options={get_name_options(guild_index, log)}
								option_disabled={get_name_option_disabled(guild_index, log)}
								selected_value={guild_index}
								class_name="w-[clamp(6rem,14vw,10rem)] min-w-[6rem] xl:w-[clamp(8rem,22vw,18rem)] xl:min-w-[8rem]"
								on_change={(e) => update_names('guild', e)}
							/>
						{/if}
						{#if can_drop_log(log)}
							<button
								type="button"
								class="ml-1 h-6 min-w-6 rounded bg-red-900/70 px-1.5 text-[10px] font-semibold uppercase tracking-wide text-red-100 hover:bg-red-800 sm:h-7 sm:px-2 sm:text-[11px]"
								on:click={() => drop_log_row(log)}
								title="Remove this partial/invalid row"
							>
								<span class="sm:hidden">x</span>
								<span class="hidden sm:inline">Drop</span>
							</button>
						{/if}
						<!-- <div class="ml-auto hidden group-hover:flex items-center">
							<button on:click={() => null}>
								<Icon icon={MdDelete} class="self-center text-red-500" />
							</button>
						</div> -->
					</div>
				</VirtualList>
			{/key}
		</div>
		<div
			class="w-[clamp(300px,34vw,520px)] grid grid-cols-1 gap-2 flex-shrink-0 text-xs h-full overflow-y-auto"
		>
			<div class="rounded-lg border border-gray-700 p-2.5">
				<p class="uppercase tracking-wide text-gray-400 mb-1.5">War Overview</p>
				{#if logs.length === 0}
					<p class="text-gray-500">No logs yet</p>
				{:else}
					<p class="text-gray-400">{own_guild_member_count} vs {enemy_count} players</p>
					<p class="mt-1">
						<span class="text-submarine-500">K {alliance_overview.own.kills}</span>
						<span class="text-gray-500 mx-1">.</span>
						<span class="text-red-500">D {alliance_overview.own.deaths}</span>
						<span class="text-gray-500 mx-1">.</span>
						<span class="font-semibold"
							>{calculate_kd(alliance_overview.own.kills, alliance_overview.own.deaths)}</span
						>
					</p>
					<p class="text-gray-400 mt-0.5">
						Enemy K/D:
						<span class="font-semibold text-foreground-secondary"
							>{calculate_kd(alliance_overview.enemy.kills, alliance_overview.enemy.deaths)}</span
						>
					</p>
				{/if}
			</div>
			<div class="rounded-lg border border-gray-700 p-2.5">
				<p class="uppercase tracking-wide text-gray-400 mb-1.5">Personal</p>
				<input
					class="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 mb-1.5"
					placeholder="Family name"
					value={personal_family_name}
					on:input={handle_personal_family_name_input}
				/>
				{#if !personal_family_name.trim()}
					<p class="text-gray-500">Enter your family name</p>
				{:else}
					<p>
						<span class="text-submarine-500">K {personal_stats.kills}</span>
						<span class="text-gray-500 mx-1">.</span>
						<span class="text-red-500">D {personal_stats.deaths}</span>
						<span class="text-gray-500 mx-1">.</span>
						<span class="font-semibold"
							>{calculate_kd(personal_stats.kills, personal_stats.deaths)}</span
						>
					</p>
				{/if}
			</div>
			<div class="rounded-lg border border-gray-700 p-2.5">
				<p class="uppercase tracking-wide text-gray-400 mb-2">K/D Breakdown</p>
				{#if logs.length === 0}
					<p class="text-gray-500">No logs yet</p>
				{:else}
					<div class="mb-3">
						<div class="flex justify-between mb-1">
							<span class="text-gray-400">Your Alliance</span>
							<span class="font-semibold"
								>{calculate_kd(alliance_overview.own.kills, alliance_overview.own.deaths)}</span
							>
						</div>
						<div class="h-1.5 rounded-full bg-gray-700 overflow-hidden">
							<div
								class="h-full bg-submarine-500 transition-all"
								style="width: {ownKillPct}%"
							></div>
						</div>
						<div class="flex justify-between mt-1">
							<span class="text-submarine-500">K {alliance_overview.own.kills}</span>
							<span class="text-red-500">D {alliance_overview.own.deaths}</span>
						</div>
					</div>
					<div>
						<div class="flex justify-between mb-1">
							<span class="text-gray-400">Enemy</span>
							<span class="font-semibold"
								>{calculate_kd(alliance_overview.enemy.kills, alliance_overview.enemy.deaths)}</span
							>
						</div>
						<div class="h-1.5 rounded-full bg-gray-700 overflow-hidden">
							<div class="h-full bg-red-500 transition-all" style="width: {enemyKillPct}%"></div>
						</div>
						<div class="flex justify-between mt-1">
							<span class="text-submarine-500">K {alliance_overview.enemy.kills}</span>
							<span class="text-red-500">D {alliance_overview.enemy.deaths}</span>
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
	<div class="flex flex-wrap gap-2 w-full justify-center flex-shrink-0">
		<Button class="w-full sm:w-32 max-w-[12rem]" on:click={upload} disabled={true}>Upload</Button>
		<Button
			class="w-full sm:w-40 max-w-[14rem]"
			on:click={pcap_recording ? () => stop_pcap_capture() : start_pcap_capture}
			color="secondary"
		>
			{pcap_recording ? 'Stop PCAP Capture' : 'Record Separate PCAP'}
		</Button>
		<Button
			class="w-full sm:w-32 max-w-[12rem]"
			on:click={save_logs}
			color="secondary"
			disabled={save_disabled}>Save</Button
		>
	</div>
	{#if pcap_recording}
		<p class="text-xs text-emerald-300 text-center mt-1">
			Separate capture running: {pcap_capture_output}
		</p>
	{/if}
</div>

<style>
	.log-panel :global(svelte-virtual-list-viewport) {
		width: max-content;
		min-width: 100%;
		overflow-x: visible;
	}
</style>
