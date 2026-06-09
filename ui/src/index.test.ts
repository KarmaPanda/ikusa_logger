import { describe, expect, it } from 'vitest';

import {
	get_log_name_at_offset,
	is_valid_combat_name,
	type LogType
} from './components/create-config/config';

describe('combat log name helpers', () => {
	it('prefers analyzer-vetted names over raw hex decoding', () => {
		const log: LogType = {
			identifier: 'deadbeef',
			time: '09:08:12',
			names: [{ name: 'Senira', offset: 100 }],
			hex: ''.padEnd(200, '0')
		};

		expect(get_log_name_at_offset(log, 100)).toBe('Senira');
	});

	it('rejects malformed core combat names', () => {
		expect(is_valid_combat_name('')).toBe(false);
		expect(is_valid_combat_name('Й')).toBe(false);
		expect(is_valid_combat_name('UNKNOWN_1')).toBe(false);
		expect(is_valid_combat_name('ValidName')).toBe(true);
	});
});
