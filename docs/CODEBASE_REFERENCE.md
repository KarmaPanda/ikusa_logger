# Ikusa Logger Codebase Reference

This document is a maintainer-focused map of the repository.

## Top-Level Structure

- `logger/`: Python backend (packet capture, replay, parsing, diagnostics)
- `ui/`: Svelte UI for recording, calibration, export, and settings
- `scripts/`: build, deploy, update automation
- `version/`: app/version manifest assets
- `config.ini`: runtime parser/filter config

## Backend Runtime Modes

Entry point: `logger/logger.py`

- `sniff` mode: live TCP sniff, parse combat logs, write `.log`
- `analyze` mode: emit calibration-friendly analyzer rows
- `open` mode: replay pcap and write normal `.log`
- `record` mode: capture separate pcap without parsing
- `status` mode: runtime dependency/config checks

## IP Filtering and Discovery

### Static + Transient Filter Model

IP filtering uses:

- static prefixes from `config.ini [IP]`
- transient prefixes/endpoints discovered at runtime (ExitLag + game)

Shared helper:

- `logger/src/options/live_ip_discovery.py`

Responsibilities:

- run periodic discovery loop
- parse discovery payload robustly
- refresh transient prefixes/endpoints in memory
- expose a singleton thread start per mode

Used by:

- `logger/src/options/sniff.py`
- `logger/src/options/analyzer.py`
- `logger/src/options/record.py`

### Separate PCAP Capture Policy

- Record mode defaults to IP filtering enabled unless explicitly overridden with `--no-ipFilter`.
- This keeps pcap size/replay time manageable by dropping unrelated system traffic.

## Parsing Pipeline

Main modules:

- `logger/src/parser.py`: normal log emission path
- `logger/src/options/analyzer.py`: analyzer stream path
- `logger/src/core_heuristics.py`: shared extraction/quality/offset heuristics
- `logger/src/packet_decode.py`: decode strategy implementation

Key design points:

- shared heuristics between parser and analyzer reduce divergence
- duplicate suppression uses signature + near-time window
- latin1 legacy path and utf16 path both include dedupe protections

## UI Calibration Flow

Primary component:

- `ui/src/components/create-config/logger.svelte`

Key behavior:

- derives candidate name offsets from analyzer stream
- derives candidate kill offsets from packet markers
- applies confidence-based early hold to avoid noisy early drift
- supports manual override from config modal

Related files:

- `ui/src/components/create-config/config.ts`
- `ui/src/components/create-config/config.modal.svelte`

## Build and Packaging Notes

- root `build.bat` / `deploy.bat` orchestrate app builds
- `logger/build.bat` builds Python backend executable
- `scripts/` contains update/deploy/install helpers

## Recommended Change Workflow

1. Update Python source in `logger/src/...`
2. Run backend checks (`status`, targeted replay/open test)
3. Rebuild backend executable if behavior changed
4. Validate UI path if analyzer/calibration output changed
5. Re-run packaging only after runtime verification

## Fast File Lookup

- Runtime CLI routing: `logger/logger.py`
- Live capture parser output: `logger/src/options/sniff.py`
- Separate pcap capture: `logger/src/options/record.py`
- Pcap analyzer replay: `logger/src/options/analyzer.py`
- Offline parse replay: `logger/src/options/open.py`
- Shared discovery loop: `logger/src/options/live_ip_discovery.py`
- Core extraction logic: `logger/src/core_heuristics.py`
- Decode behavior: `logger/src/packet_decode.py`
- Calibration UI: `ui/src/components/create-config/logger.svelte`
