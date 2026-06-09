import { ModalManager } from '../../svelte-ui/modal/modal-store';
import DecodingStrategyPrompt from './decoding-strategy-prompt.svelte';

export type DecodingStrategy = 'utf16le' | 'latin1';

export function normalize_decoding_strategy(value: unknown): DecodingStrategy {
    const normalized = String(value ?? '').trim().toLowerCase();
    if (normalized.replaceAll('-', '').startsWith('latin1')) {
        return 'latin1';
    }

    return 'utf16le';
}

export function prompt_decoding_strategy(initial_value: unknown) {
    return new Promise<DecodingStrategy | null>((resolve_choice) => {
        ModalManager.open(DecodingStrategyPrompt, {
            initial_value: normalize_decoding_strategy(initial_value),
            resolve_choice
        });
    });
}