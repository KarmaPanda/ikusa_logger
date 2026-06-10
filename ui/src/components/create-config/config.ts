import { clipboard, filesystem, storage } from '@neutralinojs/lib';
import { get_runtime_path } from '../../logic/runtime-path';

export type Config = {
	patch: string;
	decoding_strategy: string;
	identifier: string;
	discovery_processes: string[];
	ips: string[];
	player_one: number;
	player_two: number;
	guild: number;
	kill: number | null;
	diagnostics_enabled: boolean;
	auto_scroll: boolean;
	include_characters: boolean;
	all_interfaces: boolean;
	interface_name: string;
	ip_filter: boolean;
	ui_scale: number;
};

export type LogType = {
	identifier: string;
	time: string;
	names: { name: string; offset: number }[];
	hex: string;
};

export type Log = {
	time: string;
	names: string[];
	kill: boolean;
}

export const PERSONAL_FAMILY_NAME_KEY = 'personal_family_name';

export function calculate_kd(kills: number, deaths: number) {
	if (deaths <= 0) {
		return kills > 0 ? 'Perfect' : '0.00';
	}

	return (kills / deaths).toFixed(2);
}

function normalize_log_name(value: unknown) {
	return String(value ?? '')
		.replaceAll('\0', '')
		.replaceAll(' ', '')
		.trim();
}

function is_valid_combat_name_char(ch: string) {
	if (!ch) {
		return false;
	}

	if (/^[A-Za-z0-9_-]$/.test(ch)) {
		return true;
	}

	const codepoint = ch.codePointAt(0) ?? 0;
	if ((codepoint >= 0x0e01 && codepoint <= 0x0e3a) || (codepoint >= 0x0e40 && codepoint <= 0x0e4e)) {
		return true;
	}
	if (codepoint >= 0xac00 && codepoint <= 0xd7a3) {
		return true;
	}

	return /\p{M}/u.test(ch);
}

export function is_valid_combat_name(name: unknown) {
	const value = normalize_log_name(name);
	if (!value || value.startsWith('UNKNOWN_')) {
		return false;
	}
	if (value.length < 2 || value.length > 32) {
		return false;
	}
	if (value.includes(',') || value.includes(' ')) {
		return false;
	}
	if (/[\p{Cc}\p{Cs}\p{Co}\p{Cn}]/u.test(value)) {
		return false;
	}
	const chars = [...value];
	if (!chars.every((ch) => is_valid_combat_name_char(ch))) {
		return false;
	}

	return chars.some((ch) => /\p{L}/u.test(ch));
}

export function get_log_name_at_offset(log: LogType, offset: number) {
	const analyzer_name = log.names.find((entry) => entry.offset === offset)?.name;
	if (is_valid_combat_name(analyzer_name)) {
		return normalize_log_name(analyzer_name);
	}

	return normalize_log_name(hexToString(log.hex.slice(offset, offset + 64)));
}

export function parse_analyzer_output_line(data: string): LogType | null {
	if (!data || data.includes('Network Interfaces:')) {
		return null;
	}

	const parts = data.split(',');
	if (parts.length < 6) {
		return null;
	}

	const identifier = parts[0]?.trim();
	const time = parts[1]?.trim();
	const hex = parts[parts.length - 1]?.trim();
	if (!identifier || !time || !hex || !/^[0-9a-f]+$/i.test(hex)) {
		return null;
	}

	const names = parts
		.slice(2, -1)
		.map((entry) => {
			const trimmed = entry.trim();
			const last_space = trimmed.lastIndexOf(' ');
			if (last_space <= 0) {
				return null;
			}

			const name = trimmed.slice(0, last_space);
			const offset = Number.parseInt(trimmed.slice(last_space + 1), 10);
			if (!name || Number.isNaN(offset)) {
				return null;
			}

			return { name, offset };
		})
		.filter((value): value is { name: string; offset: number } => value !== null);

	if (names.length < 3) {
		return null;
	}

	return {
		identifier,
		time,
		names,
		hex
	};
}

export type CalibrationSelection = {
	possible_name_offsets: { offset: number; count: number }[][];
	name_indices: number[];
	player_one_index: number;
	player_two_index: number;
	guild_index: number;
	possible_kill_offsets: number[];
	kill_index: number;
};

const KNOWN_SERVER_IPS = [
	'20.76.13',
	'20.76.14',
	'211.188.27',
	'20.25.194',
	'172.183.60'
];

const DEFAULT_IPS = KNOWN_SERVER_IPS;

const DEFAULT_CONFIG: Config = {
	decoding_strategy: 'utf16le',
	identifier: '',
	discovery_processes: [],
	ips: [...DEFAULT_IPS],
	player_one: 0,
	player_two: 0,
	guild: 0,
	kill: 0,
	patch: '',
	diagnostics_enabled: false,
	auto_scroll: true,
	include_characters: true,
	all_interfaces: true,
	interface_name: '',
	ip_filter: true,
	ui_scale: 1
};

function get_system_default_ui_scale() {
	if (typeof window === 'undefined') {
		return DEFAULT_CONFIG.ui_scale;
	}

	const ratio = Number(window.devicePixelRatio || 1);
	const supported = [0.75, 1, 1.25];
	let closest = supported[0];
	let closest_distance = Math.abs(ratio - closest);

	for (const value of supported.slice(1)) {
		const distance = Math.abs(ratio - value);
		if (distance < closest_distance) {
			closest = value;
			closest_distance = distance;
		}
	}

	return closest;
}

function clamp_ui_scale(value: unknown) {
	if (typeof value !== 'number' || Number.isNaN(value)) {
		return DEFAULT_CONFIG.ui_scale;
	}

	return Math.min(1.25, Math.max(0.75, value));
}

function get_config_path() {
	return get_runtime_path('config.ini');
}

function get_config_backup_path() {
	return `${get_config_path()}.bak`;
}

function parse_number(value: string | undefined, fallback: number | null) {
	if (value === undefined) {
		return fallback;
	}

	const normalized = value.trim().toLowerCase();
	if (normalized === '' || normalized === 'undefined' || normalized === 'null' || normalized === 'none') {
		return null;
	}

	const parsed = Number.parseInt(value, 10);
	return Number.isNaN(parsed) ? fallback : parsed;
}

function parse_boolean(value: unknown, fallback: boolean) {
	return typeof value === 'boolean' ? value : fallback;
}

function is_valid_ip_prefix(value: unknown): value is string {
	if (typeof value !== 'string') {
		return false;
	}

	const trimmed = value.trim();
	if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(trimmed)) {
		return false;
	}

	return trimmed.split('.').every((segment) => {
		const number = Number.parseInt(segment, 10);
		return number >= 0 && number <= 255;
	});
}

function normalize_ip_prefixes(values: unknown) {
	if (!Array.isArray(values)) {
		return [...DEFAULT_IPS];
	}

	const unique = Array.from(
		new Set(values.filter((value): value is string => is_valid_ip_prefix(value)).map((value) => value.trim()))
	);

	if (unique.length > 0) {
		return unique;
	}

	return [...DEFAULT_IPS];
}

function normalize_process_names(values: unknown) {
	if (!Array.isArray(values)) {
		return [];
	}

	const deduped: string[] = [];
	for (const value of values) {
		const normalized = String(value ?? '').trim();
		if (!normalized) {
			continue;
		}
		if (deduped.some((existing) => existing.toLowerCase() === normalized.toLowerCase())) {
			continue;
		}
		deduped.push(normalized);
	}

	return deduped;
}

function normalize_decoding_strategy(value: unknown, legacy_region?: unknown) {
	const normalized = String(value ?? '')
		.trim()
		.toLowerCase();
	if (normalized.replaceAll('-', '').startsWith('latin1')) {
		return 'latin1';
	}
	if (normalized === 'utf16le' || normalized === 'utf16' || normalized === 'utf-16le' || normalized === 'utf-16') {
		return 'utf16le';
	}

	const legacy = String(legacy_region ?? '')
		.trim()
		.toUpperCase();
	if (legacy === 'NA' || legacy === 'EU') {
		return 'latin1';
	}

	return DEFAULT_CONFIG.decoding_strategy;
}

function parse_config_file(raw_config: string): Partial<Config> {
	const sections = new Map<string, Map<string, string>>();
	let current_section = '';

	for (const raw_line of raw_config.split(/\r?\n/)) {
		const line = raw_line.trim();
		if (!line || line.startsWith(';') || line.startsWith('#')) {
			continue;
		}

		const section_match = line.match(/^\[(.+)\]$/);
		if (section_match) {
			current_section = section_match[1].toUpperCase();
			if (!sections.has(current_section)) {
				sections.set(current_section, new Map());
			}
			continue;
		}

		const separator_index = line.indexOf('=');
		if (separator_index === -1 || !current_section) {
			continue;
		}

		const key = line.slice(0, separator_index).trim().toLowerCase();
		const value = line.slice(separator_index + 1).trim();
		sections.get(current_section)?.set(key, value);
	}

	const package_section = sections.get('PACKAGE');
	const general_section = sections.get('GENERAL');
	const discovery_section = sections.get('DISCOVERY');
	const ip_section = sections.get('IP');
	const discovery_values = discovery_section
		? Array.from(discovery_section.entries())
			.filter(([key]) => {
				const normalized = key.toLowerCase();
				return normalized.startsWith('process') || normalized === 'extra_processes';
			})
			.flatMap(([, value]) =>
				String(value ?? '')
					.split(/[;,\r\n]+/)
					.map((entry) => entry.trim())
					.filter(Boolean)
			)
		: [];
	const ips_from_file = ip_section
		? Array.from(ip_section.values()).filter((prefix) => is_valid_ip_prefix(prefix))
		: [];

	return {
		patch: normalize_patch_date(general_section?.get('patch') ?? ''),
		decoding_strategy: normalize_decoding_strategy(
			general_section?.get('decoding_strategy'),
			general_section?.get('region')
		),
		identifier: String(package_section?.get('identifier') ?? '').trim().toLowerCase(),
		discovery_processes: normalize_process_names(discovery_values),
		ips: ips_from_file,
		diagnostics_enabled: ['1', 'true', 'yes', 'on'].includes((general_section?.get('diagnostics') ?? 'false').toLowerCase()),
		ip_filter: ['1', 'true', 'yes', 'on'].includes((general_section?.get('ip_filter') ?? 'true').toLowerCase()),
		all_interfaces: !['0', 'false', 'no', 'off'].includes((general_section?.get('all_interfaces') ?? 'true').toLowerCase()),
		interface_name: general_section?.get('interface') ?? '',
		player_one: parse_number(package_section?.get('player_one'), DEFAULT_CONFIG.player_one) ?? DEFAULT_CONFIG.player_one,
		player_two: parse_number(package_section?.get('player_two'), DEFAULT_CONFIG.player_two) ?? DEFAULT_CONFIG.player_two,
		guild: parse_number(package_section?.get('guild'), DEFAULT_CONFIG.guild) ?? DEFAULT_CONFIG.guild,
		kill: parse_number(package_section?.get('kill'), DEFAULT_CONFIG.kill)
	};
}

function normalize_config(config?: Partial<Config> | null): Config {
	return {
		patch:
			typeof config?.patch === 'string'
				? normalize_patch_date(config.patch)
				: normalize_patch_date(DEFAULT_CONFIG.patch),
		decoding_strategy: normalize_decoding_strategy(
			(config as { decoding_strategy?: unknown } | null | undefined)?.decoding_strategy,
			(config as { region?: unknown } | null | undefined)?.region
		),
		identifier:
			typeof config?.identifier === 'string'
				? config.identifier.trim().toLowerCase()
				: DEFAULT_CONFIG.identifier,
		discovery_processes: normalize_process_names(config?.discovery_processes),
		ips: normalize_ip_prefixes(config?.ips),
		player_one:
			typeof config?.player_one === 'number' ? config.player_one : DEFAULT_CONFIG.player_one,
		player_two:
			typeof config?.player_two === 'number' ? config.player_two : DEFAULT_CONFIG.player_two,
		guild: typeof config?.guild === 'number' ? config.guild : DEFAULT_CONFIG.guild,
		kill: typeof config?.kill === 'number' || config?.kill === null ? config.kill : DEFAULT_CONFIG.kill,
		diagnostics_enabled: parse_boolean(config?.diagnostics_enabled, DEFAULT_CONFIG.diagnostics_enabled),
		auto_scroll: parse_boolean(config?.auto_scroll, DEFAULT_CONFIG.auto_scroll),
		include_characters: parse_boolean(
			config?.include_characters,
			DEFAULT_CONFIG.include_characters
		),
		all_interfaces: parse_boolean(config?.all_interfaces, DEFAULT_CONFIG.all_interfaces),
		interface_name: typeof config?.interface_name === 'string' ? config.interface_name : DEFAULT_CONFIG.interface_name,
		ip_filter: parse_boolean(config?.ip_filter, DEFAULT_CONFIG.ip_filter),
		ui_scale:
			typeof config?.ui_scale === 'number'
				? clamp_ui_scale(config.ui_scale)
				: get_system_default_ui_scale()
	};
}

export function apply_ui_scale(ui_scale?: number) {
	if (typeof document === 'undefined') {
		return;
	}

	document.documentElement.style.setProperty('--ui-scale', String(clamp_ui_scale(ui_scale)));
}

async function read_config_file(): Promise<Partial<Config> | null> {
	try {
		const raw_config = await filesystem.readFile(get_config_path());
		return parse_config_file(raw_config);
	} catch (error) {
		console.error(error);
		return null;
	}
}

export function get_date() {
	const today = new Date();
	const year = today.getFullYear();
	const month = String(today.getMonth() + 1).padStart(2, '0');
	const day = String(today.getDate()).padStart(2, '0');
	return `${year}-${month}-${day}`;
}

export function get_formatted_date(date_string: string) {
	const iso_match = String(date_string).match(/^(\d{4})-(\d{2})-(\d{2})$/);
	let date: Date;

	if (iso_match) {
		date = new Date(Number.parseInt(iso_match[1], 10), Number.parseInt(iso_match[2], 10) - 1, Number.parseInt(iso_match[3], 10));
	} else {
		date = new Date(date_string);
	}

	// Fallback to today if date is invalid
	if (isNaN(date.getTime())) {
		date = new Date();
	}

	const formatter = new Intl.DateTimeFormat('de', {
		day: '2-digit',
		month: '2-digit',
		year: 'numeric'
	});
	return formatter.format(date).replace(/\//g, '.');
}

function normalize_patch_date(value: string) {
	const input = String(value ?? '').trim();
	if (!input) {
		const iso = get_date();
		const iso_match = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
		if (!iso_match) {
			return '01.01.1970';
		}
		return `${iso_match[2]}.${iso_match[3]}.${iso_match[1]}`;
	}

	const iso_match = input.match(/^(\d{4})-(\d{2})-(\d{2})$/);
	if (iso_match) {
		return `${iso_match[2]}.${iso_match[3]}.${iso_match[1]}`;
	}

	const dot_match = input.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
	if (dot_match) {
		const first = Number.parseInt(dot_match[1], 10);
		const second = Number.parseInt(dot_match[2], 10);

		// If first part exceeds 12, treat source as dd.mm.yyyy and swap to mm.dd.yyyy.
		if (first > 12 && second >= 1 && second <= 12) {
			return `${dot_match[2]}.${dot_match[1]}.${dot_match[3]}`;
		}

		// Otherwise keep input ordering as already-normalized mm.dd.yyyy.
		return `${dot_match[1]}.${dot_match[2]}.${dot_match[3]}`;
	}

	const parsed = new Date(input);
	if (!Number.isNaN(parsed.getTime())) {
		const year = parsed.getFullYear();
		const month = String(parsed.getMonth() + 1).padStart(2, '0');
		const day = String(parsed.getDate()).padStart(2, '0');
		return `${month}.${day}.${year}`;
	}

	return '01.01.1970';
}

export function get_default_server_ips() {
	return [...DEFAULT_IPS];
}

export function stringify_config(config: Config) {
	const ips = normalize_ip_prefixes(config.ips);
	const discovery_processes = normalize_process_names(config.discovery_processes);
	const ip_lines = ips
		.map((prefix, index) => `server_${index + 1} = ${prefix}`)
		.join('\n');
	const discovery_lines = discovery_processes
		.map((name, index) => `process_${index + 1} = ${name}`)
		.join('\n');
	const discovery_block = discovery_lines.length > 0 ? `[DISCOVERY]\n${discovery_lines}\n` : '';
	return `[GENERAL]
patch=${normalize_patch_date(config.patch || get_date())}
decoding_strategy=${normalize_decoding_strategy(config.decoding_strategy)}
diagnostics=${config.diagnostics_enabled ? 'true' : 'false'}
ip_filter=${config.ip_filter ? 'true' : 'false'}
all_interfaces=${config.all_interfaces ? 'true' : 'false'}
interface=${config.interface_name || ''}
${discovery_block}[IP]
${ip_lines}
[PACKAGE]
identifier = ${config.identifier || ''}
guild = ${config.guild}
player_one = ${config.player_one}
player_two = ${config.player_two}
kill = ${config.kill}
log_length = 600
name_length = 64`;
}

/* 
export async function get_config() {
	const config_parser = new ConfigIniParser.ConfigIniParser();
	const raw_config = await filesystem.readFile('config.ini');
	const parsed_config = config_parser.parse(raw_config);
	const config: Config = {
		player_one: parsed_config.get('PACKAGE', 'player_one'),
		player_two: parsed_config.get('PACKAGE', 'player_two'),
		guild: parsed_config.get('PACKAGE', 'guild'),
		kill: parsed_config.get('PACKAGE', 'kill')
	};
	return config;
}

export async function update_config(config: Config) {
	filesystem.writeFile('config.ini', stringify_config(config));
} */

export async function update_config(config: Config) {
	const normalized = normalize_config(config);
	try {
		const current_config = await filesystem.readFile(get_config_path());
		if (current_config && current_config.trim().length > 0) {
			let existing_backup = '';
			try {
				existing_backup = await filesystem.readFile(get_config_backup_path());
			} catch {
				// Missing backup is expected on first run.
			}

			// Preserve the first known-good rollback point instead of replacing it
			// on every config write.
			if (!existing_backup || existing_backup.trim().length === 0) {
				await filesystem.writeFile(get_config_backup_path(), current_config);
			}
		}
	} catch {
		// Missing config file on first run is expected; skip backup.
	}
	await storage.setData('config', JSON.stringify(normalized));
	await filesystem.writeFile(get_config_path(), stringify_config(normalized));
	apply_ui_scale(normalized.ui_scale);
	return normalized;
}

export async function get_config(): Promise<Config> {
	const stored_config_raw = await storage.getData('config').catch((e) => console.error(e));
	const file_config = await read_config_file();
	const stored_config = stored_config_raw ? (JSON.parse(stored_config_raw) as Partial<Config>) : null;
	const normalized = normalize_config({
		...stored_config,
		...file_config
	});

	if (!stored_config_raw || !file_config) {
		await update_config(normalized);
	} else {
		// Keep storage in sync with the authoritative on-disk config.
		await storage.setData('config', JSON.stringify(normalized));
	}

	apply_ui_scale(normalized.ui_scale);

	return normalized;
}

export function build_calibrated_config(
	config: Config,
	logs: LogType[],
	selection: CalibrationSelection
): Config | null {
	if (!logs.length) {
		return null;
	}

	const identifiers = new Map<string, number>();
	for (const log of logs) {
		const candidate = String(log.identifier ?? '').trim().toLowerCase();
		if (!/^[0-9a-f]{10}$/i.test(candidate)) {
			continue;
		}
		identifiers.set(candidate, (identifiers.get(candidate) ?? 0) + 1);
	}

	const selected_identifier = Array.from(identifiers.entries())
		.sort((a, b) => b[1] - a[1])
		.map(([identifier]) => identifier)[0];
	const player_one = selection.possible_name_offsets[selection.player_one_index]?.[
		selection.name_indices[selection.player_one_index]
	]?.offset;
	const player_two = selection.possible_name_offsets[selection.player_two_index]?.[
		selection.name_indices[selection.player_two_index]
	]?.offset;
	const guild = selection.possible_name_offsets[selection.guild_index]?.[
		selection.name_indices[selection.guild_index]
	]?.offset;
	const kill = selection.possible_kill_offsets[selection.kill_index];

	if (
		typeof player_one !== 'number' ||
		typeof player_two !== 'number' ||
		typeof guild !== 'number'
	) {
		return null;
	}

	return normalize_config({
		...config,
		patch: get_date(),
		identifier: selected_identifier ?? config.identifier,
		player_one,
		player_two,
		guild,
		kill: typeof kill === 'number' ? kill : null
	});
}

export function copy_to_clipboard(config: Config) {
	clipboard.writeText(stringify_config(config));
}

export function hexToString(hex: string) {
	if (!hex || hex.length < 2) {
		return '';
	}

	const byteLength = Math.floor(hex.length / 2);
	const bytes = new Uint8Array(byteLength);
	for (let i = 0; i < byteLength; i++) {
		bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
	}

	// Name fields are UTF-16LE and null-padded.
	let utf16End = bytes.length;
	for (let i = 0; i + 1 < bytes.length; i += 2) {
		if (bytes[i] === 0 && bytes[i + 1] === 0) {
			utf16End = i;
			break;
		}
	}

	if (utf16End > 0 && utf16End % 2 === 0) {
		try {
			return new TextDecoder('utf-16le').decode(bytes.slice(0, utf16End));
		} catch (error) {
			// Fallback below for non-UTF16 fields.
		}
	}

	const singleEnd = bytes.indexOf(0);
	const sliceEnd = singleEnd === -1 ? bytes.length : singleEnd;
	const singleBytes = bytes.slice(0, sliceEnd);
	for (const encoding of ['utf-8', 'windows-874', 'tis-620']) {
		try {
			const decoded = new TextDecoder(encoding, { fatal: false }).decode(singleBytes);
			if (decoded) {
				return decoded;
			}
		} catch (error) {
			// Try the next fallback encoding.
		}
	}

	try {
		return new TextDecoder('latin1', { fatal: false }).decode(singleBytes);
	} catch (error) {
		return '';
	}
}
