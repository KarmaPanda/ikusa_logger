import type { Action } from 'svelte/action';
import { toast } from 'svelte-sonner';
import { browser } from '$app/environment';
import generateUniqueId from 'generate-unique-id';
import { goto } from '$app/navigation';
import type { SvelteComponent } from 'svelte';

export type Component = new (...args: any[]) => SvelteComponent;

export function show_toast(message: string, type: 'success' | 'error') {
	toast[type](message, {
		duration: 2500,
		style: 'background: #f5cd40; color: #000; min-width: 200px;'
	});
}

export function redirect_and_toast(destination: string, message: string) {
	show_toast(message, 'error');
	goto(destination, { replaceState: true });
}

export async function sleep(ms?: number) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export const click_outside: Action<HTMLElement, (() => void) | undefined> = (node, callback) => {
	const handle_click = (event: MouseEvent) =>
		node &&
		!node.contains(event.target as HTMLElement) &&
		!event.defaultPrevented &&
		(callback ? callback() : null);

	document.addEventListener('click', handle_click, true);

	return {
		update(newCallback) {
			callback = newCallback;
		},
		destroy() {
			document.removeEventListener('click', handle_click, true);
		}
	};
};

function measure_scrollbar() {
	if (!browser) return;
	const div = document.createElement('div');
	div.style.width = '100px';
	div.style.height = '100px';
	div.style.overflow = 'scroll';
	div.style.position = 'absolute';
	div.style.top = '-9999px';
	document.body.appendChild(div);
	const scrollbarWidth = div.offsetWidth - div.clientWidth;
	document.body.removeChild(div);
	return scrollbarWidth;
}

export const scrollbar_width = measure_scrollbar();

export function format(number: number, places = 2) {
	return +number?.toFixed(places);
}

export function get_remaining_height(el: HTMLElement, margin = 0) {
	if (!el) return 0;
	const { top } = el.getBoundingClientRect();
	const { innerHeight } = window;
	return innerHeight - top - margin;
}

export function generate_id() {
	return generateUniqueId() as string;
}

export function find_all_indices(str: string, substr: string) {
	const occurrences: number[] = [];
	let pos = str.indexOf(substr);
	while (pos !== -1) {
		occurrences.push(pos);
		pos = str.indexOf(substr, pos + 1);
	}
	return occurrences;
}
