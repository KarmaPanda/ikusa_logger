# Ikusa Logger

A tool for Black Desert Online to log combat messages.

This fork is originally based on [Ikusa 1.8.7+](https://github.com/sch-28/ikusa_logger) and was built for ASIA server compatibility and contains logger improvements for accuracy and stability. Additionally, it comes with UI improvements for high resolution monitors and etc.

WIP, can use official [website](https://ikusa.site/) for NA/EU logs or other alternatives at the moment.
~~Visualize your captured logs with this [website]().~~

## Prerequisites

- [Npcap - 1.7.8+](https://npcap.com/dist/)

Automatically installed when using the installer executable `ikusa-logger-installer.exe` found [in releases](https://github.com/KarmaPanda/ikusa_logger/releases)

#### Optional: Only needed for manual builds.

- [Node.js - 16+](https://nodejs.org/en/download/)
- [Python - 3+](https://www.python.org/downloads/)
  - In the installer, make sure to check "Add Python to environment variables"

## Installation

1. Download the latest build [in releases](https://github.com/KarmaPanda/ikusa_logger/releases)
2. Unzip the `ikusa-logger-{version}.zip` to any destination folder of your choice. Alternatively you can run the installer executable `ikusa-logger-installer.exe` to install the logger to the folder the installer is in.
3. Make sure you have the prerequisite installed (Npcap - 1.7.8+)

## Manual Build

1. Clone the repository
2. Make sure you have the prerequisites installed (Node.js and Python)
3. Run `build.bat`

## Usage

1. Start `ikusa-logger-win_x64.exe` located in `/dist/ikusa-logger/` or in the folder you extracted the archive to.
2. Click on the `Record` button
3. Select the decoding strategy UTF-16LE (ASIA) or Latin-1 (NA/EU). Optional: You can select to `Record Separate PCAP file` if you want to reprocess the logs at a later time without affecting the live logger.
4. After you are done recording, make sure to order the names of the players in the correct order!
   The order should be: `Family-Name-1 killed/died to Family-Name-2 from Enemy-Guild (Character-Name-1, Character-Name-2)`
5. Save the logs locally by clicking `Save` or upload the logs ~~directly to the website by clicking Upload~~ _temporarily disabled until the website fork is completed._

If you noticed that you have chosen the wrong name order, you can open the `.log` file again with the logger and adjust the names.

## Startup Issue

If you are unable to start the regular ikusa-logger. Try to start it using the `--mode=browser` argument.

## Need help?

If you have any questions, feel free to add me on Discord: karmapanda or add the original dev: sch.28 if you have any questions about the original fork.
