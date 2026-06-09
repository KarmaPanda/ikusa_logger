<script lang="ts">
	import IoMdHelp from 'svelte-icons/io/IoMdHelp.svelte';

	import type { HTMLAttributes } from 'svelte/elements';
	import Icon from './icon.svelte';
	interface $$Props extends HTMLAttributes<HTMLDivElement> {
		text: string;
	}

	export let text = 'Tooltip text';
</script>

<div {...$$restProps} class="relative inline-flex group">
	<Icon icon={IoMdHelp} />
	<div
		class="pointer-events-none absolute z-50 left-1/2 -translate-x-1/2 -top-2 -translate-y-full whitespace-normal max-w-md rounded-lg shadow-lg border border-foreground-secondary bg-background text-foreground px-3 py-2 text-sm font-medium opacity-0 group-hover:opacity-100 transition-opacity"
	>
		{text}
	</div>
</div>
