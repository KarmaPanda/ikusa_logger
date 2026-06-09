<script lang="ts">
	import { app, os } from '@neutralinojs/lib';
	import Button from '../svelte-ui/elements/button.svelte';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import LoadingIndicator from '../svelte-ui/elements/loading-indicator.svelte';
	import { check_status, type LoggerStatus } from '../logic/logger-status';
	import { get_check_update_script_command, get_update_script_command } from '../logic/app-command';
	import GoMarkGithub from 'svelte-icons/go/GoMarkGithub.svelte';
	import Icon from '../svelte-ui/elements/icon.svelte';
	import FaDiscord from 'svelte-icons/fa/FaDiscord.svelte';
	import { get_config, update_config } from '../components/create-config/config';
	import { prompt_decoding_strategy } from '../components/create-config/decoding-strategy-prompt';

	let loading = false;
	let status: LoggerStatus;
	let update_available = false;
	let version = NL_APPVERSION;

	function normalize_version(value: string | undefined): string {
		const trimmed = String(value || '').trim();
		if (!trimmed) {
			return '';
		}

		const without_quotes = trimmed.replace(/^["']+|["']+$/g, '');
		return without_quotes.replace(/^v/i, '').toLowerCase();
	}

	async function check_for_updates() {
		const result = (await os.execCommand(get_check_update_script_command(), {
			background: false
		})) as {
			stdOut?: string;
			stdErr?: string;
			exitCode?: number;
		};

		if ((result?.exitCode ?? 1) !== 0) {
			// Private repositories may block some endpoints for update probing.
			// Keep startup clean and simply skip showing the update banner.
			return;
		}

		const latest_version = String(result?.stdOut || '')
			.split(/\r?\n/)
			.map((line) => line.trim())
			.filter(Boolean)
			.at(-1);

		if (!latest_version) {
			return;
		}

		const latest_normalized = normalize_version(latest_version);
		const current_normalized = normalize_version(NL_APPVERSION);

		if (latest_normalized && latest_normalized != current_normalized) {
			update_available = true;
			version = latest_version;
		}
	}

	async function update() {
		try {
			os.execCommand(`${get_update_script_command()} ${version}`, { background: true });
			await app.exit();
		} catch (err) {
			alert(
				'Updating went wrong, check your internet connection. ' + ((err as Error).message || err)
			);
			console.error(err);
		}
	}

	async function choose_strategy_and_go(destination: '/record' | '/open') {
		const config = await get_config();
		const selected_strategy = await prompt_decoding_strategy(config.decoding_strategy);
		if (!selected_strategy) {
			return;
		}

		await update_config({ ...config, decoding_strategy: selected_strategy });
		await goto(destination);
	}

	onMount(async () => {
		try {
			loading = true;
			console.log('Checking for updates');
			await check_for_updates().catch((e) => console.error(e));
			console.log('Checking status');
			status = await check_status();
			console.log('Starting logger');
		} catch (e) {
			console.error(e);
			/* alert('Upadating went wrong, check your internet connection.' + (e as Error).message || e); */
		}
		loading = false;
	});
</script>

<div class="relative h-full w-full flex flex-col items-center justify-center overflow-hidden pb-10">
	<div class="flex flex-col items-center justify-center gap-2 w-full max-w-[14rem] px-2">
		<Button class="w-full" size="lg" on:click={() => choose_strategy_and_go('/record')}
			>Record</Button
		>
		<Button class="w-full" size="lg" on:click={() => choose_strategy_and_go('/open')}>Open</Button>
		<Button class="w-full" size="lg" on:click={() => goto('/settings')} color="secondary"
			>Settings</Button
		>
		<!-- 	<div
		class="text-submarine-500 absolute top-1/2 -translate-y-1/2 left-2 text-xs w-56 text-center flex flex-col"
	>
		<p>
			If your version is below 1.3.0, then you have to completly reinstall Ikusa Logger by
			downloading the latest installer.
		</p>
		<br />
		<p>The auto patcher might cause issues. If you have any questions, join our discord server.</p>
	</div> -->
		<div class="min-h-[32px] mt-2 text-center flex flex-col items-center justify-center w-full">
			{#if loading}
				<LoadingIndicator />
			{:else}
				{#if update_available}
					<Button class="w-full max-w-[14rem]" size="lg" on:click={update}>Update</Button>
				{/if}

				{#if status?.npcap_installed}
					<p class="text-submarine-500">Npcap found</p>
				{:else}
					<p class="text-red-500 flex justify-center flex-col">
						Npcap is not installed. <a
							href="https://npcap.com/dist/npcap-1.87.exe"
							class="underline">Download</a
						>
					</p>
				{/if}
			{/if}
		</div>
	</div>

	<div
		class="w-full flex flex-wrap gap-2 justify-between absolute bottom-0 left-0 p-2 text-[clamp(0.7rem,1.6vmin,0.9rem)] z-0"
	>
		<p>Made by <b>sch.28</b> forked by KarmaPanda</p>
	</div>
</div>
