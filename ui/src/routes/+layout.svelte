<script lang="ts">
	import { init, events, os, app, window as nlWindow } from '@neutralinojs/lib';
	import { onMount } from 'svelte';
	import '../app.css';
	import Modal from '../svelte-ui/modal/modal.svelte';
	import { Toaster } from 'svelte-sonner';
	import { get_remaining_height, show_toast } from '../svelte-ui/util';
	import Header from '../components/header.svelte';
	import LoadingIndicator from '../svelte-ui/elements/loading-indicator.svelte';
	import { get_config } from '../components/create-config/config';

	let is_ready = false;
	let base_window_width = 0;
	let base_window_height = 0;
	let base_device_pixel_ratio = 0;
	let base_chrome_ratio = 0;
	let base_screen_width = 0;
	let base_screen_height = 0;
	let last_device_pixel_ratio = 0;
	let last_screen_width = 0;
	let last_screen_height = 0;
	let neutralino_dpi_scale: number | null = null;
	let neutralino_poll_in_flight = false;
	let last_applied_dpi_scale = 1;
	let last_window_center_x = Number.NaN;
	let last_window_center_y = Number.NaN;
	let last_window_position_x = Number.NaN;
	let last_window_position_y = Number.NaN;
	let dpr_watch_interval: number | null = null;
	let viewport_height = 0;
	let content_height = 0;
	const dpi_compensation_strength = 0.6;

	$: content_height = viewport_height ? Math.max(0, get_remaining_height(container, 16)) : 0;

	function running_on_windows_desktop() {
		return (
			running_in_desktop_client() &&
			/windows/i.test(String((window as any).NL_OS ?? navigator.userAgent))
		);
	}

	function build_windows_monitor_dpi_command(center_x: number, center_y: number) {
		const x = Math.round(center_x);
		const y = Math.round(center_y);
		return `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "& { $ErrorActionPreference = 'Stop'; Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CopilotMonitorDpi {
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT {
        public int X;
        public int Y;
    }
    [DllImport(\"user32.dll\")]
    public static extern IntPtr MonitorFromPoint(POINT pt, uint flags);
    [DllImport(\"Shcore.dll\")]
    public static extern int GetDpiForMonitor(IntPtr monitor, int dpiType, out uint dpiX, out uint dpiY);
}
'@; $point = New-Object CopilotMonitorDpi+POINT; $point.X = ${x}; $point.Y = ${y}; $monitor = [CopilotMonitorDpi]::MonitorFromPoint($point, 2); if ($monitor -eq [IntPtr]::Zero) { return }; $dpiX = 0; $dpiY = 0; $result = [CopilotMonitorDpi]::GetDpiForMonitor($monitor, 0, [ref]$dpiX, [ref]$dpiY); if ($result -eq 0) { Write-Output $dpiX } }"`;
	}

	async function get_windows_monitor_scale(center_x: number, center_y: number) {
		if (!running_on_windows_desktop()) {
			return null;
		}

		const result = await os.execCommand(build_windows_monitor_dpi_command(center_x, center_y));
		if (result.exitCode !== 0) {
			return null;
		}

		const dpi_value = Number.parseFloat(String(result.stdOut ?? '').trim());
		if (!Number.isFinite(dpi_value) || dpi_value <= 0) {
			return null;
		}

		return Math.max(0.5, Math.min(2, dpi_value / 96));
	}

	async function refresh_neutralino_monitor_scale(force = false) {
		if (!running_in_desktop_client() || neutralino_poll_in_flight) {
			return;
		}

		neutralino_poll_in_flight = true;
		try {
			const [position, size] = await Promise.all([nlWindow.getPosition(), nlWindow.getSize()]);
			const position_x = Number(position?.x || 0);
			const position_y = Number(position?.y || 0);

			const center_x = position_x + Number(size?.width || 0) / 2;
			const center_y = position_y + Number(size?.height || 0) / 2;
			const center_changed =
				!Number.isFinite(last_window_center_x) ||
				!Number.isFinite(last_window_center_y) ||
				Math.abs(center_x - last_window_center_x) > 8 ||
				Math.abs(center_y - last_window_center_y) > 8;

			last_window_position_x = position_x;
			last_window_position_y = position_y;
			last_window_center_x = center_x;
			last_window_center_y = center_y;

			if (!force && !center_changed && neutralino_dpi_scale != null) {
				return;
			}

			const windows_scale = await get_windows_monitor_scale(center_x, center_y);
			if (windows_scale != null) {
				neutralino_dpi_scale = windows_scale;
				return;
			}

			neutralino_dpi_scale = null;
		} catch (_error) {
			neutralino_dpi_scale = null;
		} finally {
			neutralino_poll_in_flight = false;
		}
	}

	function handle_monitor_context_refresh() {
		void refresh_neutralino_monitor_scale(true).finally(() => {
			update_window_scale();
		});
	}

	function update_window_scale() {
		viewport_height = window.innerHeight;
		const current_dpr = Number(window.devicePixelRatio || 1);
		const current_chrome_ratio =
			window.innerWidth > 0
				? Number(window.outerWidth || window.innerWidth) / window.innerWidth
				: 1;
		const current_screen_width = Number(window.screen?.width || 0);
		const current_screen_height = Number(window.screen?.height || 0);

		if (!base_window_width || !base_window_height) {
			base_window_width = window.innerWidth;
			base_window_height = window.innerHeight;
		}
		if (!base_device_pixel_ratio) {
			base_device_pixel_ratio = current_dpr;
		}
		if (!base_chrome_ratio) {
			base_chrome_ratio = current_chrome_ratio;
		}
		if (!base_screen_width && current_screen_width > 0) {
			base_screen_width = current_screen_width;
		}
		if (!base_screen_height && current_screen_height > 0) {
			base_screen_height = current_screen_height;
		}
		last_device_pixel_ratio = current_dpr;
		last_screen_width = current_screen_width;
		last_screen_height = current_screen_height;

		const scale_x = window.innerWidth / base_window_width;
		const scale_y = window.innerHeight / base_window_height;
		const window_scale = Math.max(0.7, Math.min(1, scale_x, scale_y));

		let monitor_scale = neutralino_dpi_scale ?? current_dpr;

		// Some Windows/webview combinations do not update devicePixelRatio when
		// moving across monitors. Fallback to outer/inner chrome ratio as a
		// monitor-DPI proxy in that case.
		if (
			neutralino_dpi_scale == null &&
			base_device_pixel_ratio > 0 &&
			Math.abs(current_dpr - base_device_pixel_ratio) < 0.001 &&
			base_chrome_ratio > 0 &&
			current_chrome_ratio > 0
		) {
			const screen_scale_candidates: number[] = [];
			if (base_screen_width > 0 && current_screen_width > 0) {
				screen_scale_candidates.push(base_screen_width / current_screen_width);
			}
			if (base_screen_height > 0 && current_screen_height > 0) {
				screen_scale_candidates.push(base_screen_height / current_screen_height);
			}

			const screen_scale =
				screen_scale_candidates.length > 0
					? screen_scale_candidates.reduce((sum, value) => sum + value, 0) /
						screen_scale_candidates.length
					: 1;

			// Treat proxy signals as relative change from startup monitor and
			// convert to an absolute DPI scale anchored at startup DPR.
			if (Math.abs(screen_scale - 1) > 0.02) {
				monitor_scale = base_device_pixel_ratio * screen_scale;
			} else {
				monitor_scale = base_device_pixel_ratio * (current_chrome_ratio / base_chrome_ratio);
			}
		}

		monitor_scale = Math.max(0.5, Math.min(2, monitor_scale));
		const full_dpi_compensation = 1 / monitor_scale;
		// Blend toward full compensation so high-DPI monitors are moderated
		// without fully neutralizing OS scale differences.
		const dpi_scale = Math.max(
			0.5,
			Math.min(2, 1 + (full_dpi_compensation - 1) * dpi_compensation_strength)
		);

		if (Math.abs(dpi_scale - last_applied_dpi_scale) > 0.02) {
			base_window_width = window.innerWidth;
			base_window_height = window.innerHeight;
		}
		last_applied_dpi_scale = dpi_scale;

		document.documentElement.style.setProperty('--window-scale', String(window_scale));
		document.documentElement.style.setProperty('--dpi-scale', String(dpi_scale));
	}

	let last_refresh_block_notice_at = 0;

	function running_in_desktop_client() {
		return typeof window !== 'undefined' && typeof (window as any).NL_PATH === 'string';
	}

	function handle_refresh_key(event: KeyboardEvent) {
		if (!running_in_desktop_client()) {
			return;
		}

		const is_ctrl_or_meta_r = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'r';
		const is_f5 = event.key === 'F5';
		if (!is_ctrl_or_meta_r && !is_f5) {
			return;
		}

		event.preventDefault();
		event.stopPropagation();

		const now = Date.now();
		if (now - last_refresh_block_notice_at > 1500) {
			last_refresh_block_notice_at = now;
			show_toast('Refresh is disabled in the desktop app to protect active sessions.', 'error');
		}
	}

	onMount(() => {
		handle_monitor_context_refresh();
		window.requestAnimationFrame(update_window_scale);
		window.addEventListener('resize', update_window_scale);
		const window_size_observer =
			typeof ResizeObserver !== 'undefined'
				? new ResizeObserver(() => update_window_scale())
				: null;
		window_size_observer?.observe(document.documentElement);
		dpr_watch_interval = window.setInterval(() => {
			if (running_in_desktop_client() && !neutralino_poll_in_flight) {
				void nlWindow.getPosition().then((position) => {
					const position_x = Number(position?.x || 0);
					const position_y = Number(position?.y || 0);
					const moved =
						!Number.isFinite(last_window_position_x) ||
						!Number.isFinite(last_window_position_y) ||
						Math.abs(position_x - last_window_position_x) > 8 ||
						Math.abs(position_y - last_window_position_y) > 8;

					if (moved) {
						handle_monitor_context_refresh();
					}
				});
			}

			const current_dpr = Number(window.devicePixelRatio || 1);
			const current_chrome_ratio =
				window.innerWidth > 0
					? Number(window.outerWidth || window.innerWidth) / window.innerWidth
					: 1;
			const current_screen_width = Number(window.screen?.width || 0);
			const current_screen_height = Number(window.screen?.height || 0);
			const screen_changed =
				(current_screen_width > 0 && current_screen_width !== last_screen_width) ||
				(current_screen_height > 0 && current_screen_height !== last_screen_height);
			if (
				current_dpr !== last_device_pixel_ratio ||
				Math.abs(current_chrome_ratio - base_chrome_ratio) > 0.02 ||
				screen_changed
			) {
				handle_monitor_context_refresh();
			}
		}, 200);
		window.addEventListener('focus', handle_monitor_context_refresh);
		window.addEventListener('visibilitychange', handle_monitor_context_refresh);
		window.addEventListener('keydown', handle_refresh_key, { capture: true });

		const handle_ready = async () => {
			try {
				await get_config();
			} catch (error) {
				console.error(error);
			}
			is_ready = true;
		};

		const handle_window_close = async () => {
			await os.execCommand('taskkill /F /IM logger.exe ');
			await app.exit();
		};

		events.on('ready', handle_ready);
		events.on('windowClose', handle_window_close);
		init();

		return () => {
			events.off('ready', handle_ready);
			events.off('windowClose', handle_window_close);
			window_size_observer?.disconnect();
			window.removeEventListener('resize', update_window_scale);
			if (dpr_watch_interval) {
				window.clearInterval(dpr_watch_interval);
				dpr_watch_interval = null;
			}
			window.removeEventListener('focus', handle_monitor_context_refresh);
			window.removeEventListener('visibilitychange', handle_monitor_context_refresh);
			window.removeEventListener('keydown', handle_refresh_key, { capture: true });
			document.documentElement.style.setProperty('--window-scale', '1');
			document.documentElement.style.setProperty('--dpi-scale', '1');
		};
	});

	let container: HTMLElement;
</script>

{#if is_ready}
	<div class="h-full w-full">
		<div class="h-full w-full max-w-none px-2 py-2 sm:px-4 sm:py-4 overflow-auto">
			<Header />
			<div
				class="mt-3 sm:mt-6 flex flex-col items-stretch min-h-0 overflow-auto"
				bind:this={container}
				style="height: {content_height + viewport_height * 0}px;"
			>
				<slot />
			</div>
		</div>
		<Modal />
		<Toaster />
	</div>
{:else}
	<div class="h-full w-full flex items-center justify-center overflow-hidden">
		<LoadingIndicator />
	</div>
{/if}
