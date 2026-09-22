# SPDX-License-Identifier: Apache-2.0
"""Pure mapping from board records to tracking-sheet cell changes. No I/O here.

The tracking sheet is the human-curated inventory; a machine may propose changes
to it but never applies them without a person looking at the proposal first. So
this module only *computes* the proposal:

    result = compute_updates(records, header, rows)

and the CLI shows it, asks, and then writes exactly what was shown.

Rules (Tim, 2026-09-22):

- A row is a board. It is found by the FPGA's Device DNA first and by the RPi's
  serial number second. Switch port, IP address and hostname are volatile and
  are never used to find a row.
- Columns are found by header *name* (case-insensitive), never by letter. A
  header this tool needs that the sheet lacks is appended on the right.
- Identity cells (DNA, serial, MACs, part, board, HAT, flash) that are filled
  in and differ from the record are CONFLICTS: reported, never overwritten. A
  differing identity means a board was swapped or a record is wrong, and a
  human has to say which.
- Human-entered columns (cable colour, PCB revision, location, status, notes)
  are never written, whatever the record says.
- A record with no matching row goes into the first placeholder row for its
  site (a row with neither DNA nor serial), else becomes a new row.

The shape is copied from mithro/gwifi-openwrt tools/fleet/galeflash/sheetmap.py.
"""

import re
from dataclasses import dataclass, field

# Record field -> sheet header. Order matters: missing headers are appended in
# this order. Every header here is machine-owned.
FIELD_TO_HEADER = {
    "switch_port": "Port",  # the first "Port" column: switch/port, e.g. sw2/48
    "site": "Site",
    "name": "Name",
    "ip": "IP",
    "rpi_uplink_mac": "RPi Uplink MAC",
    "rpi_wlan_mac": "RPi WLAN MAC",
    "rpi_serial": "RPi Serial Number",
    "rpi_type_memory": "RPi Type + Memory",
    "rpi_camera": "RPi Camera",
    "fpga_device_dna": "FPGA Device DNA",
    "fpga_part": "FPGA Part",
    "fpga_memory": "FPGA Memory",
    "fpga_spi_flash": "FPGA SPI Flash",
    # --- columns the sheet did not have on 2026-09-22; appended on first use ---
    "rpi_hat": "RPi HAT",
    "rpi_bootloader": "RPi Bootloader",
    "fpga_board": "FPGA Board",
    "flash_unique_id": "Flash Unique ID",
    "pcie": "PCIe",
    "flash_contents": "Flash Contents",
    "backup_path": "Backup",  # big-storage path of the pre-flash capture
    "backup_sha256": "Backup SHA256",
    "image_archive": "Image Archive",  # big-storage path of the flashed image(s)
    "image_sha256": "Image SHA256",
    "jtag": "JTAG",
    "p2_wiring": "P2 Wiring",
    "uartbone": "UART",
    "p2_gpio": "GPIO",
    "cold_boot": "Cold Boot",
    "checked": "Last Checked",
    "labels": "Labels",
}

# Headers a person owns. Never written, whatever a record contains.
HUMAN_HEADERS = frozenset({"cable color", "location", "fpga board pcb revision", "status", "notes"})

# Fields whose cells, once filled, only a person may change.
IDENTITY_FIELDS = frozenset(
    {
        "fpga_device_dna",
        "rpi_serial",
        "rpi_uplink_mac",
        "rpi_wlan_mac",
        "rpi_type_memory",
        "fpga_part",
        "fpga_board",
        "fpga_memory",
        "fpga_spi_flash",
        "flash_unique_id",
        "rpi_hat",
    }
)

DNA_RE = re.compile(r"(?<![0-9a-f])(?:0x)?([0-9a-f]{16})(?![0-9a-f])", re.IGNORECASE)
SERIAL_RE = re.compile(r"^\s*([0-9a-f]{16})\s*$", re.IGNORECASE)
MAC_RE = re.compile(r"^\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})\s*$", re.IGNORECASE)


class SheetMapError(Exception):
    pass


@dataclass(frozen=True)
class Update:
    row: int  # 1-based sheet row (the header is row 1)
    column: int  # 0-based column index into the extended header
    header: str
    field: str
    old: str
    new: str


Conflict = Update


@dataclass
class Result:
    header: list
    updates: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    new_rows: list = field(default_factory=list)
    unmatched_rows: list = field(default_factory=list)  # 0-based indices of rows with an identity and no record
    matched: dict = field(default_factory=dict)  # 0-based row index -> record index

    @property
    def empty(self):
        return not (self.updates or self.conflicts or self.new_rows)


def normalise_dna(text):
    """'0x0054B48664B04854 (via UART)' -> '0054b48664b04854'; None if there is no 16-hex-digit token."""
    m = DNA_RE.search(str(text or ""))
    return m.group(1).lower() if m else None


def normalise_serial(text):
    m = SERIAL_RE.match(str(text or ""))
    return m.group(1).lower() if m else None


def _equivalent(fld, old, new):
    if fld == "fpga_device_dna":
        return normalise_dna(old) == normalise_dna(new)
    if fld == "rpi_serial":
        return normalise_serial(old) == normalise_serial(new)
    if fld in ("rpi_uplink_mac", "rpi_wlan_mac"):
        return str(old).strip().lower() == str(new).strip().lower()
    return str(old).strip().casefold() == str(new).strip().casefold()


def header_columns(header):
    """Lower-cased header name -> column index of its FIRST occurrence."""
    cols = {}
    for i, h in enumerate(header):
        cols.setdefault(str(h).strip().lower(), i)
    return cols


def extended_header(header, records):
    """The sheet's header plus every header a record needs that it lacks, in FIELD_TO_HEADER order."""
    present = set(header_columns(header))
    out = list(header)
    used = {f for r in records for f in r}
    for fld, h in FIELD_TO_HEADER.items():
        if fld in used and h.lower() not in present:
            out.append(h)
            present.add(h.lower())
    return out


def _cell(row, col):
    return str(row[col]).strip() if col < len(row) and row[col] is not None else ""


def _identity_index(header, rows):
    cols = header_columns(header)
    dna_col, serial_col = cols.get("fpga device dna"), cols.get("rpi serial number")
    by_dna, by_serial = {}, {}
    for i, row in enumerate(rows):
        dna = normalise_dna(_cell(row, dna_col)) if dna_col is not None else None
        serial = normalise_serial(_cell(row, serial_col)) if serial_col is not None else None
        if dna is not None:
            if dna in by_dna:
                raise SheetMapError(f"rows {by_dna[dna] + 2} and {i + 2} both carry DNA {dna}")
            by_dna[dna] = i
        if serial is not None:
            if serial in by_serial:
                raise SheetMapError(f"rows {by_serial[serial] + 2} and {i + 2} both carry RPi serial {serial}")
            by_serial[serial] = i
    return by_dna, by_serial


def _placeholder(rows, header, site, taken):
    cols = header_columns(header)
    dna_col, serial_col, site_col = cols.get("fpga device dna"), cols.get("rpi serial number"), cols.get("site")
    for i, row in enumerate(rows):
        if i in taken:
            continue
        if dna_col is not None and _cell(row, dna_col):
            continue
        if serial_col is not None and _cell(row, serial_col):
            continue
        if site and site_col is not None and _cell(row, site_col).lower() != site.lower():
            continue
        return i
    return None


def compute_updates(records, header, rows):
    """Work out what the sheet would need to say to agree with `records`. Changes nothing."""
    seen = {}
    for n, rec in enumerate(records):
        dna = normalise_dna(rec.get("fpga_device_dna"))
        if dna is None:
            raise SheetMapError(f"record {n} has no usable fpga_device_dna: {rec.get('fpga_device_dna')!r}")
        if dna in seen:
            raise SheetMapError(f"records {seen[dna]} and {n} both have DNA {dna}")
        seen[dna] = n

    header = extended_header(header, records)
    cols = header_columns(header)
    by_dna, by_serial = _identity_index(header, rows)
    result = Result(header=header)
    claimed = set()

    for n, rec in enumerate(records):
        dna = normalise_dna(rec["fpga_device_dna"])
        serial = normalise_serial(rec.get("rpi_serial"))
        idx = by_dna.get(dna)
        fresh = False  # True when the row had no board: its junk may be overwritten
        if idx is None and serial is not None:
            idx = by_serial.get(serial)
            dna_col = cols["fpga device dna"]
            if idx is not None and _cell(rows[idx], dna_col):
                # Same Pi, a different FPGA on record. Either the FPGA was swapped or the
                # record belongs to another row; a person decides, so propose nothing else.
                result.conflicts.append(
                    Conflict(
                        idx + 2,
                        dna_col,
                        header[dna_col],
                        "fpga_device_dna",
                        _cell(rows[idx], dna_col),
                        str(rec["fpga_device_dna"]),
                    )
                )
                claimed.add(idx)
                result.matched[idx] = n
                continue
        if idx is None:
            idx = _placeholder(rows, header, str(rec.get("site") or ""), claimed)
            fresh = idx is not None
        if idx is None:
            new = [""] * len(header)
            for fld, value in rec.items():
                h = FIELD_TO_HEADER.get(fld)
                if h is None or h.lower() in HUMAN_HEADERS or value in (None, ""):
                    continue
                new[cols[h.lower()]] = str(value)
            result.new_rows.append(new)
            continue
        if idx in claimed:
            raise SheetMapError(f"records {result.matched[idx]} and {n} both land on row {idx + 2}")
        claimed.add(idx)
        result.matched[idx] = n
        row = rows[idx]
        for fld, value in rec.items():
            h = FIELD_TO_HEADER.get(fld)
            if h is None or h.lower() in HUMAN_HEADERS or value in (None, ""):
                continue
            col = cols[h.lower()]
            old, new = _cell(row, col), str(value)
            if old == "":
                result.updates.append(Update(idx + 2, col, header[col], fld, old, new))
            elif _equivalent(fld, old, new):
                continue
            elif fld in IDENTITY_FIELDS and not fresh:
                result.conflicts.append(Conflict(idx + 2, col, header[col], fld, old, new))
            else:
                result.updates.append(Update(idx + 2, col, header[col], fld, old, new))

    for i, row in enumerate(rows):
        if i in claimed:
            continue
        has_dna = cols.get("fpga device dna") is not None and _cell(row, cols["fpga device dna"])
        has_serial = cols.get("rpi serial number") is not None and _cell(row, cols["rpi serial number"])
        if has_dna or has_serial:
            result.unmatched_rows.append(i)
    return result


def render(result):
    lines = []
    for c in result.conflicts:
        lines.append(f"CONFLICT row {c.row} {c.header}: sheet says {c.old!r}, record says {c.new!r} (not changed)")
    for u in result.updates:
        arrow = f"{u.old!r} -> {u.new!r}" if u.old else f"{u.new!r}"
        lines.append(f"UPDATE   row {u.row} {u.header}: {arrow}")
    for new in result.new_rows:
        cols = header_columns(result.header)
        dna = new[cols["fpga device dna"]] if "fpga device dna" in cols else "?"
        lines.append(f"NEW ROW  DNA {dna}: " + "; ".join(f"{h}={v}" for h, v in zip(result.header, new) if v))
    if result.unmatched_rows:
        lines.append(
            "rows with a board but no record (left alone): " + ", ".join(str(i + 2) for i in result.unmatched_rows)
        )
    if not lines:
        lines.append("sheet already agrees with the records")
    return "\n".join(lines)
