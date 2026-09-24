# Security

The client is open so you can read what it does before you run it.

- An exchange key is stored in the OS keychain when one is available. The file fallback is mode 0600 and stays on your machine.
- The key should have trade permission on and withdraw permission off.
- krellbot.dev receives a license key if you add packs. It does not receive the exchange key.
- This repository does not contain the paid packs.
- Paper fills stay on this machine, inside `$KRELLBOT_HOME/run/paper-<venue>.json`. No exchange sees a paper fill.
- A live order requires typing `LIVE` exactly at the first arm prompt and a key whose withdraw permission is off. The typed confirmation is a CLI-only path; the dashboard refuses live arm.
- Telemetry is off until the operator types `y`. See [docs/telemetry.md](docs/telemetry.md).

If you find a problem, open an issue on this repository. Do not send a key, a secret, or a license key in the issue.
