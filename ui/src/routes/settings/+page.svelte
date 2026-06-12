<script lang="ts">
	import Select from '../../components/create-config/select.svelte';
	import { onMount } from 'svelte';
	import { get_config, type Config, update_config } from '../../components/create-config/config';
	import Button from '../../svelte-ui/elements/button.svelte';
	import LoadingIndicator from '../../svelte-ui/elements/loading-indicator.svelte';
	import { app, os } from '@neutralinojs/lib';
	import { dev } from '$app/environment';
	import { get_main_executable_command } from '../../logic/app-command';
	import {
		run_logger_command,
		quote_logger_argument,
		get_dev_logger_console_enabled,
		set_dev_logger_console_enabled,
		load_dev_logger_console_enabled
	} from '../../logic/logger-wrapper';

	let config: Config;

	let selected_interface = 0;
	let interface_options = ['All', 'Default'];
	let interface_values = ['', ''];
	type InterfaceDescriptor = {
		value: string;
		label: string;
		name?: string;
		guid?: string;
		description?: string;
		network_name?: string;
		ips?: string[];
		available?: boolean;
	};

	let ip_filter = true;
	let diagnostics_enabled = true;
	let dev_logger_console_enabled = false;
	let available_discovery_processes: string[] = [];
	let selected_discovery_process_index = 0;
	let selected_ui_scale = 1;
	let settings_loaded = false;
	const ui_scale_options = ['75%', '100%', '125%'];
	const ui_scale_values = [0.75, 1, 1.25];

	async function update_interface() {
		if (config) {
			const is_all = selected_interface === 0;
			const interface_name =
				selected_interface >= 2 ? (interface_values[selected_interface] ?? '') : '';
			config = await update_config({
				...config,
				all_interfaces: is_all,
				interface_name
			});
		}
	}

	function parse_interfaces_output(raw_output: string): InterfaceDescriptor[] {
		const lines = raw_output
			.split(/\r?\n/)
			.map((line) => line.trim())
			.filter(Boolean);

		for (let index = lines.length - 1; index >= 0; index--) {
			try {
				const parsed = JSON.parse(lines[index]);
				if (Array.isArray(parsed)) {
					return parsed
						.map((value): InterfaceDescriptor | null => {
							if (typeof value === 'string') {
								const normalized = value.trim();
								if (!normalized) return null;
								return { value: normalized, label: normalized, name: normalized, guid: normalized };
							}

							if (!value || typeof value !== 'object') return null;

							const parsed_value = String((value as { value?: unknown }).value ?? '').trim();
							const parsed_name = String((value as { name?: unknown }).name ?? '').trim();
							const parsed_guid = String((value as { guid?: unknown }).guid ?? '').trim();
							const normalized_value = parsed_value || parsed_guid || parsed_name;
							if (!normalized_value) return null;

							const description = String(
								(value as { description?: unknown }).description ?? ''
							).trim();
							const network_name = String(
								(value as { network_name?: unknown }).network_name ?? ''
							).trim();
							const ips = Array.isArray((value as { ips?: unknown }).ips)
								? (value as { ips: unknown[] }).ips
										.map((entry) => String(entry).trim())
										.filter(Boolean)
								: [];
							const availability = Boolean((value as { available?: unknown }).available);
							const label =
								String((value as { label?: unknown }).label ?? '').trim() ||
								[
									parsed_name || parsed_guid,
									description,
									network_name ? `net=${network_name}` : '',
									ips.length > 0 ? `ips=${ips.slice(0, 3).join(',')}` : '',
									availability ? '' : 'unavailable'
								]
									.filter(Boolean)
									.join(' | ');

							return {
								value: normalized_value,
								label,
								name: parsed_name,
								guid: parsed_guid,
								description,
								network_name,
								ips,
								available: availability
							};
						})
						.filter((item): item is InterfaceDescriptor => Boolean(item));
				}
			} catch {
				// keep scanning lines
			}
		}

		return [];
	}

	async function load_interfaces() {
		try {
			const result = await run_logger_command('--list-interfaces --json');
			const discovered = parse_interfaces_output(result.stdOut);
			const available_only = discovered.filter((entry) => entry.available !== false);
			const unique = available_only.filter(
				(entry, index, all) => all.findIndex((other) => other.value === entry.value) === index
			);

			interface_options = ['All', 'Default', ...unique.map((entry) => entry.label)];
			interface_values = ['', '', ...unique.map((entry) => entry.value)];
		} catch (error) {
			console.error(error);
			interface_options = ['All', 'Default'];
			interface_values = ['', ''];
		}
	}

	async function update_ip_filter() {
		if (config) {
			config = await update_config({ ...config, ip_filter });
		}
	}

	async function update_ui_scale() {
		if (config) {
			config = await update_config({ ...config, ui_scale: ui_scale_values[selected_ui_scale] });
		}
	}

	async function update_diagnostics_enabled() {
		if (config) {
			await update_config({ ...config, diagnostics_enabled });
		}
	}

	function update_dev_logger_console_enabled() {
		set_dev_logger_console_enabled(dev_logger_console_enabled);
	}

	function parse_discovery_processes_output(raw_output: string): string[] {
		const lines = raw_output
			.split(/\r?\n/)
			.map((line) => line.trim())
			.filter(Boolean);

		for (let index = lines.length - 1; index >= 0; index--) {
			try {
				const parsed = JSON.parse(lines[index]);
				if (Array.isArray(parsed)) {
					return parsed
						.map((entry) => String(entry ?? '').trim())
						.filter((entry) => entry.length > 0);
				}
			} catch {
				// Continue scanning until a JSON payload is found.
			}
		}

		return [];
	}

	async function load_discovery_processes() {
		try {
			const result = await run_logger_command('--list-discovery-processes --json');
			const processes = parse_discovery_processes_output(result.stdOut);
			available_discovery_processes = Array.from(new Set(processes));
			selected_discovery_process_index = 0;
		} catch (error) {
			console.error(error);
			available_discovery_processes = [];
			selected_discovery_process_index = 0;
		}
	}

	async function add_discovery_process() {
		if (!config) {
			return;
		}
		const selected = available_discovery_processes[selected_discovery_process_index] ?? '';
		if (!selected) {
			return;
		}

		const existing = Array.isArray(config.discovery_processes)
			? [...config.discovery_processes]
			: [];
		if (existing.some((entry) => String(entry).toLowerCase() === selected.toLowerCase())) {
			return;
		}

		const discovery_processes = [...existing, selected];
		config = await update_config({ ...config, discovery_processes });
	}

	async function remove_discovery_process(process_name: string) {
		if (!config) {
			return;
		}

		const discovery_processes = (config.discovery_processes ?? []).filter(
			(entry) => String(entry).toLowerCase() !== process_name.toLowerCase()
		);
		config = await update_config({ ...config, discovery_processes });
	}

	function get_active_discovery_targets() {
		const base_targets = ['BlackDesert64.exe', 'ExitLag.exe'];
		const configured = (config?.discovery_processes ?? [])
			.map((entry) => String(entry ?? '').trim())
			.filter((entry) => entry.length > 0);
		const merged = [...base_targets];

		for (const processName of configured) {
			if (merged.some((existing) => existing.toLowerCase() === processName.toLowerCase())) {
				continue;
			}
			merged.push(processName);
		}

		return merged;
	}

	$: if (settings_loaded) {
		ip_filter;
		update_ip_filter();
	}

	$: if (settings_loaded) {
		diagnostics_enabled;
		update_diagnostics_enabled();
	}

	onMount(async () => {
		config = await get_config();
		dev_logger_console_enabled = await load_dev_logger_console_enabled();
		await load_interfaces();
		await load_discovery_processes();
		if (config.all_interfaces === true || config.all_interfaces === undefined) {
			selected_interface = 0;
		} else if (config.interface_name) {
			const found_index = interface_values.findIndex((value) => value === config.interface_name);
			selected_interface = found_index >= 2 ? found_index : 1;
		} else {
			selected_interface = 1;
		}
		ip_filter = config.ip_filter === true || config.ip_filter === undefined ? true : false;
		diagnostics_enabled = config.diagnostics_enabled === true;
		dev_logger_console_enabled = get_dev_logger_console_enabled();
		selected_ui_scale = Math.max(
			0,
			ui_scale_values.findIndex((value) => value === config.ui_scale)
		);
		settings_loaded = true;
	});

	$: if (settings_loaded) {
		dev_logger_console_enabled;
		update_dev_logger_console_enabled();
	}

	async function restart_dev() {
		if (dev) return;
		await os.execCommand(`${get_main_executable_command()} --window-enable-inspector`, {
			background: true
		});
		app.exit();
	}

	async function restart_browser() {
		if (dev) return;
		await os.execCommand(`${get_main_executable_command()} --mode=browser`, {
			background: true
		});
		app.exit();
	}
</script>

{#if !settings_loaded}
	<div class="h-full w-full flex items-center justify-center">
		<LoadingIndicator />
	</div>
{:else}
	<div class="h-full w-full flex flex-col gap-3 overflow-auto pr-1">
		<div class="w-full">
			<p class="block mb-1 text-sm text-foreground">Network Interface</p>
			<Select
				options={interface_options}
				bind:selected_value={selected_interface}
				class_name="w-full p-2 rounded-lg !ring-gold truncate"
				on_change={update_interface}
			/>
		</div>
		<div class="w-full">
			<label for="ip-filter-toggle" class="block mb-1 text-sm text-foreground"
				>Enable IP Filter</label
			>
			<label
				class="w-full flex items-center justify-between rounded-lg border border-foreground-secondary/40 px-3 py-2"
			>
				<span class="text-sm text-foreground-secondary"
					>Filter packets by configured server IPs</span
				>
				<input
					id="ip-filter-toggle"
					type="checkbox"
					bind:checked={ip_filter}
					class="h-5 w-5 rounded border border-foreground-secondary bg-background text-gold-300"
				/>
			</label>
		</div>
		<div class="w-full">
			<label for="diagnostics-toggle" class="block mb-1 text-sm text-foreground"
				>Enable Diagnostics Logs</label
			>
			<label
				class="w-full flex items-center justify-between rounded-lg border border-foreground-secondary/40 px-3 py-2"
			>
				<span class="text-sm text-foreground-secondary"
					>Write diagnostics events and summary files</span
				>
				<input
					id="diagnostics-toggle"
					type="checkbox"
					bind:checked={diagnostics_enabled}
					class="h-5 w-5 rounded border border-foreground-secondary bg-background text-gold-300"
				/>
			</label>
		</div>
		<div class="w-full">
			<label for="dev-logger-console-toggle" class="block mb-1 text-sm text-foreground"
				>Debug: Mirror Logger in Console</label
			>
			<label
				class="w-full flex items-center justify-between rounded-lg border border-foreground-secondary/40 px-3 py-2"
			>
				<span class="text-sm text-foreground-secondary"
					>Open a separate cmd window for each logger command</span
				>
				<input
					id="dev-logger-console-toggle"
					type="checkbox"
					bind:checked={dev_logger_console_enabled}
					class="h-5 w-5 rounded border border-foreground-secondary bg-background text-gold-300"
				/>
			</label>
		</div>
		<div class="w-full">
			<label for="discovery-processes" class="block mb-1 text-sm text-foreground"
				>Additional Discovery Processes</label
			>
			<p class="mb-2 text-xs text-foreground-secondary">
				Select a running process to discover relay/VPN IPs for filtering. BlackDesert64.exe and
				ExitLag.exe are already included automatically.
			</p>
			<div class="flex gap-2">
				<select
					id="discovery-processes"
					class="w-full rounded-lg border border-foreground-secondary/40 bg-background px-3 py-2 text-sm text-foreground"
					bind:value={selected_discovery_process_index}
				>
					{#if available_discovery_processes.length === 0}
						<option value={0}>No processes found</option>
					{:else}
						{#each available_discovery_processes as processName, index}
							<option value={index}>{processName}</option>
						{/each}
					{/if}
				</select>
				<Button
					class="shrink-0"
					on:click={add_discovery_process}
					disabled={available_discovery_processes.length === 0}
				>
					Add
				</Button>
			</div>
			{#if (config.discovery_processes ?? []).length > 0}
				<div class="mt-2 flex flex-wrap gap-2">
					{#each config.discovery_processes as processName}
						<span
							class="inline-flex items-center gap-2 rounded-lg border border-foreground-secondary/40 px-2 py-1 text-xs text-foreground-secondary"
						>
							{processName}
							<button
								type="button"
								class="rounded px-1 text-red-300 hover:bg-red-900/40"
								on:click={() => remove_discovery_process(processName)}
								title="Remove process"
							>
								x
							</button>
						</span>
					{/each}
				</div>
			{/if}
			<div class="mt-2 flex justify-end">
				<Button class="w-full sm:w-auto" on:click={load_discovery_processes}>Refresh List</Button>
			</div>
			<div class="mt-3 rounded-lg border border-foreground-secondary/30 bg-background/60 px-3 py-2">
				<p class="text-xs font-semibold text-foreground-secondary">Active Discovery Targets</p>
				<p class="mt-1 text-xs text-foreground-secondary break-words">
					{get_active_discovery_targets().join(', ')}
				</p>
			</div>
		</div>
		<div class="w-full">
			<p class="block mb-1 text-sm text-foreground">UI Scale</p>
			<Select
				options={ui_scale_options}
				bind:selected_value={selected_ui_scale}
				class_name="w-full p-2 rounded-lg !ring-gold truncate"
				on_change={update_ui_scale}
			/>
		</div>
		<div class="mt-auto w-full flex flex-col gap-2 pb-2">
			<Button class="w-full" on:click={restart_dev}>Dev Mode</Button>
			<Button class="w-full" on:click={restart_browser}>Browser Mode</Button>
		</div>
	</div>
{/if}
