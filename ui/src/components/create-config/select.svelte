<script lang="ts">
	export let selected_value: number | string = 0;
	export let options: (string | number)[] = [];
	export let option_disabled: boolean[] = [];
	export let on_change: (e: Event) => void = (e) => {};
	export let class_name = '';

	$: select_class = class_name || 'w-32 p-1 rounded-lg !ring-gold truncate';
</script>

<select bind:value={selected_value} class={select_class} on:change={on_change}>
	{#each options as option, i}
		<option
			value={i}
			disabled={option_disabled[i] === true}
			class="rounded-lg text-gray-800 bg-gray-300"
		>
			{option}
		</option>
	{/each}
</select>
