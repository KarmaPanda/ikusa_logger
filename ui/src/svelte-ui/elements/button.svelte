<script lang="ts">
	interface $$Props {
		class?: string;
		id?: string;
		color?: 'primary' | 'secondary';
		disabled?: boolean;
		size?: 'sm' | 'md' | 'lg';
	}
</script>

<button
	type="button"
	on:click
	disabled={$$props.disabled || false}
	id={$$props.id}
	class="
	{($$props.color === 'primary' || !$$props.color) &&
		`bg-gold-300 focus:ring-gold-400 text-black border ${
			$$props.disabled ? '!bg-gray-700 text-gray-400 border-gray-600' : 'border-gold'
		}`}
	{$$props.color === 'secondary' &&
		'bg-background focus:ring-gray-400 border border-foreground-secondary'}
	text-center font-medium focus:ring-4 focus:outline-none flex items-center justify-center rounded-lg disabled:cursor-not-allowed {$$props.class}
	{($$props.size === 'md' || !$$props.size) && 'h-10 px-5 text-sm'}
	{$$props.size === 'sm' && 'h-8 px-4 text-xs'}
	{$$props.size === 'lg' && 'h-12 px-6 text-lg'}
	"
>
	<slot />
</button>
