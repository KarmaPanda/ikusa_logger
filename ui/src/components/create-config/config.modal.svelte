<script lang="ts">
	import IoMdClipboard from 'svelte-icons/io/IoMdClipboard.svelte';
	import { onDestroy } from 'svelte';
	import Icon from '../../svelte-ui/elements/icon.svelte';
	import { copy_to_clipboard, get_default_server_ips, type Config } from './config';
	import Select from './select.svelte';
	import Checkbox from '../../svelte-ui/elements/checkbox.svelte';

	export let config: Config;
	export let options: {
		possible_kill_offsets: number[];
		possible_name_offsets: { offset: number; count: number }[][];
		name_indices: number[];
		player_one_index: number;
		player_two_index: number;
		guild_index: number;
		kill_index: number;
		include_characters: boolean;
	};
	export let onChange: (
		new_options: typeof options & { server_ips: string[]; include_characters: boolean }
	) => void;

	function update_name_index(slot_index: number, e: Event) {
		const index = +(e.target as HTMLSelectElement).value;
		options.name_indices[slot_index] = index;
		emit_change();
	}

	function update_kill_index(e: Event) {
		const index = +(e.target as HTMLSelectElement).value;
		options.kill_index = index;
		emit_change();
	}

	function emit_change() {
		onChange({
			...options,
			include_characters,
			server_ips: [...server_ips]
		});
	}

	function set_name_offset(slot_index: number, offset: number) {
		if (!Number.isInteger(offset)) {
			return;
		}

		const list = options.possible_name_offsets[slot_index] ?? [];
		let selected_index = list.findIndex((entry) => entry.offset === offset);
		if (selected_index === -1) {
			list.unshift({ offset, count: 0 });
			selected_index = 0;
		}

		options.possible_name_offsets[slot_index] = list;
		options.name_indices[slot_index] = selected_index;
		emit_change();
	}

	function get_name_offset(slot_index: number) {
		const list = options.possible_name_offsets[slot_index] ?? [];
		const selected_index = options.name_indices[slot_index] ?? 0;
		const selected = list[selected_index];
		return selected?.offset ?? 0;
	}

	function set_kill_offset(offset: number) {
		if (!Number.isInteger(offset)) {
			return;
		}

		let selected_index = options.possible_kill_offsets.findIndex((entry) => entry === offset);
		if (selected_index === -1) {
			options.possible_kill_offsets = [offset, ...options.possible_kill_offsets];
			selected_index = 0;
		}

		options.kill_index = selected_index;
		emit_change();
	}

	function get_kill_offset() {
		return options.possible_kill_offsets[options.kill_index] ?? 0;
	}

	function update_server_index(e: Event) {
		selected_server_index = +(e.target as HTMLSelectElement).value;
	}

	function is_valid_ip_prefix(value: string) {
		const trimmed = value.trim();
		if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(trimmed)) {
			return false;
		}

		return trimmed.split('.').every((segment) => {
			const part = Number.parseInt(segment, 10);
			return part >= 0 && part <= 255;
		});
	}

	function add_server_ip() {
		const normalized = new_server_ip.trim();
		if (!is_valid_ip_prefix(normalized)) {
			set_server_ip_message('Use format xxx.xxx.xxx (each 0-255).');
			return;
		}

		if (server_ips.includes(normalized)) {
			selected_server_index = server_ips.indexOf(normalized);
			new_server_ip = '';
			set_server_ip_message('That IP prefix is already in the list.');
			return;
		}

		server_ips = [...server_ips, normalized];
		selected_server_index = server_ips.length - 1;
		new_server_ip = '';
		set_server_ip_message('Server IP prefix added.', 'success', true);
		emit_change();
	}

	function remove_selected_server_ip() {
		if (server_ips.length <= 1) {
			set_server_ip_message('At least one server IP is required.');
			return;
		}

		server_ips = server_ips.filter((_, index) => index !== selected_server_index);
		if (selected_server_index >= server_ips.length) {
			selected_server_index = Math.max(0, server_ips.length - 1);
		}
		set_server_ip_message('');
		emit_change();
	}

	function handle_server_ip_keydown(event: KeyboardEvent) {
		if (event.key !== 'Enter') {
			return;
		}

		event.preventDefault();
		add_server_ip();
	}

	function handle_server_ip_input(event: Event) {
		new_server_ip = (event.target as HTMLInputElement).value;
		const normalized = new_server_ip.trim();
		if (!normalized) {
			set_server_ip_message('');
			return;
		}

		set_server_ip_message(
			is_valid_ip_prefix(normalized) ? '' : 'Use format xxx.xxx.xxx (each 0-255).'
		);
	}

	function set_server_ip_message(
		message: string,
		tone: 'warning' | 'success' = 'warning',
		auto_clear = false
	) {
		if (server_ip_message_timeout !== null) {
			window.clearTimeout(server_ip_message_timeout);
			server_ip_message_timeout = null;
		}

		server_ip_validation_message = message;
		server_ip_validation_tone = tone;

		if (auto_clear && message) {
			server_ip_message_timeout = window.setTimeout(() => {
				server_ip_validation_message = '';
				server_ip_message_timeout = null;
			}, 1500);
		}
	}

	let include_characters = config.include_characters;
	let selected_server_index = 0;
	let new_server_ip = '';
	let server_ip_validation_message = '';
	let server_ip_validation_tone: 'warning' | 'success' = 'warning';
	let server_ip_message_timeout: number | null = null;
	$: preview_ips = get_default_server_ips();
	let server_ips = config?.ips?.length ? [...config.ips] : [...preview_ips];

	onDestroy(() => {
		if (server_ip_message_timeout !== null) {
			window.clearTimeout(server_ip_message_timeout);
		}
	});
	$: {
		if (selected_server_index >= server_ips.length) {
			selected_server_index = 0;
		}
	}

	$: {
		include_characters;
		emit_change();
	}
</script>

{#if config}
	<div class="flex justify-between">
		<h3 class="font-bold">Config</h3>
		<button on:click={copy_to_clipboard.bind(null, config)}>
			<Icon icon={IoMdClipboard} />
		</button>
	</div>
	<div>
		<Checkbox bind:checked={include_characters} />
		<span>Characters</span>
	</div>
	<pre class="text-sm mt-2">
[GENERAL]
patch 		= 	{config.patch}
decoding_strategy 	= 	{config.decoding_strategy}
[IP]
servers 		= 	<Select
			options={server_ips}
			selected_value={selected_server_index}
			on_change={(e) => update_server_index(e)}
		/>
add_server 	= 	<input
			type="text"
			class="w-32 p-1 rounded-lg !ring-gold text-xs"
			placeholder="20.76.13"
			bind:value={new_server_ip}
			on:input={handle_server_ip_input}
			on:keydown={handle_server_ip_keydown}
		/>

server_actions 	= 	<span class="inline-flex gap-1 align-middle">
				<button class="rounded px-2 py-0.5 bg-emerald-700 text-white" on:click={add_server_ip}>Add</button>
				<button class="rounded px-2 py-0.5 bg-red-700 text-white" on:click={remove_selected_server_ip}
				>Delete</button
			>
			</span>

			{#if server_ip_validation_message}
			<span
				class={`ml-2 text-[11px] ${server_ip_validation_tone === 'success' ? 'text-emerald-300' : 'text-amber-300'}`}>
					{server_ip_validation_message}
				</span>
		{/if}
[PACKAGE]
identifier 	= 	{config.identifier || '(auto)'}
kill 		= 	<span class="inline-flex items-center gap-1 align-middle"
			><input
				type="number"
				class="w-24 p-1 rounded-lg !ring-gold text-xs"
				value={get_kill_offset()}
				on:input={(e) => set_kill_offset(Number.parseInt((e.target as HTMLInputElement).value, 10))}
			/><Select
				options={options.possible_kill_offsets}
				selected_value={options.kill_index}
				on_change={(e) => update_kill_index(e)}
				class_name="w-20 p-1 rounded-lg !ring-gold text-xs"
			/></span
		>
player_one 	= 	<span class="inline-flex items-center gap-1 align-middle"
			><input
				type="number"
				class="w-24 p-1 rounded-lg !ring-gold text-xs"
				value={get_name_offset(options.player_one_index)}
				on:input={(e) =>
					set_name_offset(
						options.player_one_index,
						Number.parseInt((e.target as HTMLInputElement).value, 10)
					)}
			/><Select
				options={(options.possible_name_offsets[options.player_one_index] ?? []).map(
					(entry) => entry.offset
				)}
				selected_value={options.name_indices[options.player_one_index] ?? 0}
				on_change={(e) => update_name_index(options.player_one_index, e)}
				class_name="w-20 p-1 rounded-lg !ring-gold text-xs"
			/></span
		>
player_two 	= 	<span class="inline-flex items-center gap-1 align-middle"
			><input
				type="number"
				class="w-24 p-1 rounded-lg !ring-gold text-xs"
				value={get_name_offset(options.player_two_index)}
				on:input={(e) =>
					set_name_offset(
						options.player_two_index,
						Number.parseInt((e.target as HTMLInputElement).value, 10)
					)}
			/><Select
				options={(options.possible_name_offsets[options.player_two_index] ?? []).map(
					(entry) => entry.offset
				)}
				selected_value={options.name_indices[options.player_two_index] ?? 0}
				on_change={(e) => update_name_index(options.player_two_index, e)}
				class_name="w-20 p-1 rounded-lg !ring-gold text-xs"
			/></span
		>
guild 		= 	<span class="inline-flex items-center gap-1 align-middle"
			><input
				type="number"
				class="w-24 p-1 rounded-lg !ring-gold text-xs"
				value={get_name_offset(options.guild_index)}
				on:input={(e) =>
					set_name_offset(
						options.guild_index,
						Number.parseInt((e.target as HTMLInputElement).value, 10)
					)}
			/><Select
				options={(options.possible_name_offsets[options.guild_index] ?? []).map(
					(entry) => entry.offset
				)}
				selected_value={options.name_indices[options.guild_index] ?? 0}
				on_change={(e) => update_name_index(options.guild_index, e)}
				class_name="w-20 p-1 rounded-lg !ring-gold text-xs"
			/></span
		>
</pre>
{/if}
