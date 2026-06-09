import { get, writable } from 'svelte/store';
import type { Component } from '../util';

export type ModalPayload = {
	component: Component;
	props: Record<string, any>;
};

const CurrentModal = writable<ModalPayload | null>(null);

export abstract class ModalManager {
	static open(modal: Component, props: Record<string, any> = {}) {
		const current = get(CurrentModal);
		if (current?.component === modal) CurrentModal.set(null);
		else CurrentModal.set({ component: modal, props });
	}

	static close() {
		CurrentModal.set(null);
	}

	static get store() {
		return CurrentModal;
	}
}
