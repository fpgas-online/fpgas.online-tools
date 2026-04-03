# fpgas.online-tools

Miscellaneous utility scripts for fpgas.online FPGA-as-a-Service infrastructure.

## Overview

This repository contains standalone diagnostic and monitoring tools used in the fpgas.online platform. These scripts are used ad-hoc by operators or deployed to specific hosts by Ansible.

## Tools

### DHCP Utilities (`dhcp/`)

- **`dhcp-vc.py`** -- Analyzes DHCP vendor class identifiers to identify device types on the network.
- **`dhcp-logger.py`** -- Logs DHCP events (leases, requests, releases) for monitoring and debugging.
- **`log_lookie.py`** -- Parses and analyzes DHCP log files to extract patterns and statistics.

### Netconsole (`netconsole/`)

- **`ncc.py`** -- Netconsole client that runs on a Pi to forward kernel messages over the network. Useful for capturing boot-time diagnostics and kernel panics from headless Pi nodes.

## Directory Structure

```
dhcp/         DHCP monitoring and analysis tools
netconsole/   Netconsole client for kernel message forwarding
notes.txt     Operational notes
ruff.toml     Python linter configuration
```

## Usage

These tools are standalone Python scripts. Run them directly:

```
python3 dhcp/dhcp-vc.py
python3 dhcp/dhcp-logger.py
python3 netconsole/ncc.py
```

Refer to each script for specific arguments and options.

## Linting

- Python: [ruff](https://docs.astral.sh/ruff/)

## Related Repositories

- [fpgas.online-infra](https://github.com/fpgas-online/fpgas.online-infra) -- Ansible playbooks that may deploy these tools
- [fpgas.online-setup-pi](https://github.com/fpgas-online/fpgas.online-setup-pi) -- On-Pi configuration
- [fpgas.online-netboot-pi](https://github.com/fpgas-online/fpgas.online-netboot-pi) -- Netboot filesystem preparation

## License

See [LICENSE](LICENSE).
