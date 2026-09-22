# fleet-sheet

Diff board records against the [FPGA Board Tracking
sheet](https://docs.google.com/spreadsheets/d/1CY38U9o4KPCZvfdblJWgpEBKLCnMhlQipjTqfH6QVOw/edit)
and apply what a person accepts.

The sheet is the slow-moving, human-curated inventory: people edit it directly,
it lists boards that are offline or decommissioned, and nothing updates it
automatically. This tool proposes changes from machine-gathered records and
writes them only when someone runs `apply` and says `yes`.

## Rules

- A row is a board. It is found by **FPGA Device DNA** first and **RPi Serial
  Number** second. Switch port, IP and hostname are volatile and never keys.
- Columns are matched by header *name*, never by letter. A needed header the
  tab lacks is appended on the right (`RPi HAT`, `Backup SHA256`, `JTAG`, …).
- Filled **identity** cells (DNA, serial, MACs, part, board, HAT, flash, memory)
  that differ from the record are **conflicts**: printed, never overwritten.
  That is what a swapped board looks like, and a person decides.
- **Human** columns (`Cable Color`, `Location`, `FPGA Board PCB Revision`,
  `Status`, `Notes`) are never written, whatever the record says.
- A record with no row goes into the first placeholder row for its site (a row
  with neither DNA nor serial; its junk is overwritten), else a new row.

## Use

The service-account key lives on ten64 at `/opt/gdoc2netcfg/service_account.json`
(root only), so run with `sudo`:

```
cd fleet
sudo uv run --project . fleet-sheet diff  ~/github/fpgas-online/acorn-bringup-records/
sudo uv run --project . fleet-sheet apply ~/github/fpgas-online/acorn-bringup-records/88a29e458577.json
```

`diff` writes nothing and exits 1 if there are conflicts. `apply` prints the
same proposal, asks for a literal `yes`, writes exactly those cells, re-reads
the tab and checks it now agrees (exit 3 if not). `--tab arty|netv2|<name>`
selects another tab; `--yes` skips the prompt for scripted seeding — a person
is still the one running it.

Records are the per-board bring-up JSON files (see
`fpgas.online-test-designs`), one per board; the site's registration export
will be a second source with the same field names (`fleetsheet/sheetmap.py`
`FIELD_TO_HEADER`).

## Tests

```
cd fleet && uv run --group dev pytest
```

The mapping logic (`sheetmap.py`) has no I/O and is tested on fake headers and
rows; the CLI is tested against a fake sheet that replays the writes.
