<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import Icon from '../svelte-ui/elements/icon.svelte';
	import IoMdArrowRoundBack from 'svelte-icons/io/IoMdArrowRoundBack.svelte';
	import { confirm_exit_to_home } from '../logic/navigation-guard';

	$: show_arrow = $page.route.id !== '/';

	const version = NL_APPVERSION;

	async function navigate_home_guarded() {
		if ($page.route.id === '/') {
			return;
		}

		const can_exit = await confirm_exit_to_home();
		if (!can_exit) {
			return;
		}

		await goto('/');
	}
</script>

<header
	class="relative flex items-center justify-center shrink-0 w-full min-h-[3.5rem] sm:min-h-[4.5rem]"
>
	{#if show_arrow}
		<button
			type="button"
			class="absolute left-0 top-1/2 -translate-y-1/2 p-2 text-gold"
			on:click={navigate_home_guarded}
		>
			<Icon icon={IoMdArrowRoundBack} />
		</button>
	{/if}
	<div class="flex items-end w-full">
		<a
			class="text-[clamp(1.5rem,4vmin,2.5rem)] font-bold text-gold mt-2 sm:mt-4 flex flex-col items-center leading-none w-full"
			href={'/'}
			on:click|preventDefault={navigate_home_guarded}
		>
			<span>Ikusa+</span>
			<span class="text-[clamp(0.65rem,1.4vmin,0.8rem)] font-light"
				>Logger <span class="text-[clamp(0.65rem,1.4vmin,0.8rem)]">{version}</span></span
			>
		</a>
	</div>
</header>
