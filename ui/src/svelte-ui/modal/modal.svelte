<script lang="ts">
	import { ModalManager } from './modal-store';

	let modalPayload: { component: any; props: Record<string, any> } | null = null;

	ModalManager.store.subscribe((new_modal) => {
		modalPayload = new_modal;
	});

	function close_modal() {
		ModalManager.close();
	}

	function handle_overlay_click(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			close_modal();
		}
	}
</script>

{#if modalPayload}
	<div
		class="z-[51] fixed top-0 left-0 w-screen h-screen flex flex-col justify-center bg-background bg-opacity-90"
		role="dialog"
		aria-modal="true"
		tabindex="0"
		on:keydown={(event) => event.key === 'Escape' && close_modal()}
		on:click={handle_overlay_click}
	>
		<div class="relative m-2 max-h-full z-[52] pointer-events-none">
			<div class="relative w-fit max-w-full max-h-full my-2 mx-auto bg-background shadow-lg rounded-lg border-gold border h-full pointer-events-auto">
				<div class="relative p-4 overflow-auto h-full">
					<svelte:component this={modalPayload.component} {...modalPayload.props} />
				</div>
			</div>
		</div>
	</div>
{/if}
