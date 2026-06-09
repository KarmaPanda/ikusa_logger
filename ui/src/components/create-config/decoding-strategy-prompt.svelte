<script lang="ts">
	import { onDestroy } from 'svelte';
	import Button from '../../svelte-ui/elements/button.svelte';
	import Select from './select.svelte';
	import { ModalManager } from '../../svelte-ui/modal/modal-store';

	export let initial_value = 'utf16le';
	export let resolve_choice: (value: 'utf16le' | 'latin1' | null) => void;

	const decoding_strategy_options = ['UTF-16LE (ASIA)', 'Latin-1 (NA/EU)'];
	const decoding_strategy_values = ['utf16le', 'latin1'] as const;

	let selected_value = Math.max(
		0,
		decoding_strategy_values.findIndex((value) => value === initial_value)
	);
	let settled = false;

	function finish(value: 'utf16le' | 'latin1' | null) {
		if (settled) {
			return;
		}

		settled = true;
		resolve_choice(value);
		ModalManager.close();
	}

	onDestroy(() => {
		if (!settled) {
			settled = true;
			resolve_choice(null);
		}
	});
</script>

<div class="w-full max-w-md">
	<div class="mb-4 space-y-2">
		<h2 class="text-lg font-semibold text-foreground">Choose decoding strategy</h2>
		<p class="text-sm text-foreground-secondary">
			Pick the strategy that matches the log you are opening or recording.
		</p>
	</div>

	<div class="space-y-2">
		<p class="text-sm text-foreground">Decoding Strategy</p>
		<Select
			options={decoding_strategy_options}
			bind:selected_value
			class_name="w-full p-2 rounded-lg !ring-gold truncate"
		/>
		<p class="text-xs text-foreground-secondary">UTF-16LE is used primarily for ASIA servers.</p>
		<p class="text-xs text-foreground-secondary">Latin-1 is used for NA/EU servers.</p>
	</div>

	<div class="mt-5 flex flex-wrap justify-end gap-2">
		<Button size="sm" color="secondary" on:click={() => finish(null)}>Cancel</Button>
		<Button
			size="sm"
			on:click={() => finish(decoding_strategy_values[selected_value] ?? 'utf16le')}
		>
			Continue
		</Button>
	</div>
</div>
