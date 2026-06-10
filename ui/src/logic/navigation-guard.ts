import { get, writable } from 'svelte/store';

type ExitGuardState = {
    has_log_entries: boolean;
    has_active_separate_pcap: boolean;
    stop_active_separate_pcap: (() => Promise<void>) | null;
};

const default_exit_guard_state: ExitGuardState = {
    has_log_entries: false,
    has_active_separate_pcap: false,
    stop_active_separate_pcap: null
};

const exit_guard_state = writable<ExitGuardState>({ ...default_exit_guard_state });

export function set_exit_guard_state(partial_state: Partial<ExitGuardState>) {
    exit_guard_state.update((current) => ({
        ...current,
        ...partial_state
    }));
}

export function clear_exit_guard_state() {
    exit_guard_state.set({ ...default_exit_guard_state });
}

export async function confirm_exit_to_home() {
    const current = get(exit_guard_state);

    if (current.has_active_separate_pcap) {
        const confirm_stop = window.confirm(
            'Separate PCAP recording is active. Stop recording and exit this page?'
        );
        if (!confirm_stop) {
            return false;
        }

        if (current.stop_active_separate_pcap) {
            try {
                await current.stop_active_separate_pcap();
            } catch (error) {
                console.error(error);
                window.alert('Failed to stop separate PCAP recording. Stay on this page and try stopping it manually.');
                return false;
            }
        }
    }

    if (current.has_log_entries) {
        const confirm_exit = window.confirm(
            'This page has log entries. Exit anyway? Unsaved changes may be lost.'
        );
        if (!confirm_exit) {
            return false;
        }
    }

    return true;
}