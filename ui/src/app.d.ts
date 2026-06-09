// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces
declare global {
	const NL_APPVERSION: string;
	interface ImportMetaEnv {
		readonly VITE_IKUSA_PROJECT_ROOT?: string;
		readonly VITE_IKUSA_DEV_RUNTIME?: string;
	}

	interface ImportMeta {
		readonly env: ImportMetaEnv;
	}

	interface Window {
		NL_PATH: string;
	}
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface Platform {}
	}
}

export { };
