# SPDX-License-Identifier: Apache-2.0
"""Load board records to compare against the sheet.

Today a record is a JSON file written during a board's bring-up (one file per
board, keyed by its RPi uplink MAC). The site's registration export will be a
second source with the same field names.
"""

import json
import pathlib

from . import sheetmap


class RecordError(Exception):
    pass


def load_file(path):
    path = pathlib.Path(path)
    with open(path) as f:
        rec = json.load(f)
    if not isinstance(rec, dict):
        raise RecordError(f"{path}: not a JSON object")
    rec = dict(rec)
    rec.setdefault("_source", str(path))
    if "switch_port" not in rec and rec.get("switch") and rec.get("port"):
        rec["switch_port"] = f"{rec['switch']}/{rec['port']}"
    if sheetmap.normalise_dna(rec.get("fpga_device_dna")) is None:
        raise RecordError(f"{path}: no usable fpga_device_dna")
    return rec


def load(paths):
    """Files, or directories of *.json files."""
    out = []
    for p in map(pathlib.Path, paths):
        files = sorted(p.glob("*.json")) if p.is_dir() else [p]
        if not files:
            raise RecordError(f"{p}: no records")
        out.extend(load_file(f) for f in files)
    return out
