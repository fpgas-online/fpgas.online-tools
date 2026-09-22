# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from fleetsheet import cli, records, sheet_io, sheetmap


def test_col_letter():
    assert [sheet_io.col_letter(i) for i in (0, 1, 25, 26, 27, 51, 52, 701, 702)] == [
        "A",
        "B",
        "Z",
        "AA",
        "AB",
        "AZ",
        "BA",
        "ZZ",
        "AAA",
    ]
    with pytest.raises(ValueError):
        sheet_io.col_letter(-1)


def test_plan_writes_is_one_range_per_changed_cell_and_nothing_for_conflicts():
    result = sheetmap.Result(header=["A", "B"])
    result.updates.append(sheetmap.Update(2, 1, "B", "ip", "", "10.21.2.48"))
    result.updates.append(sheetmap.Update(5, 27, "Labels", "labels", "old", "new"))
    result.conflicts.append(sheetmap.Conflict(2, 0, "A", "rpi_serial", "x", "y"))
    assert sheet_io.plan_writes(result, "Tab/One") == [
        {"range": "'Tab/One'!B2", "values": [["10.21.2.48"]]},
        {"range": "'Tab/One'!AB5", "values": [["new"]]},
    ]


def test_header_writes_only_for_appended_columns():
    assert sheet_io.header_writes(["A", "B"], ["A", "B"], "T") == []
    assert sheet_io.header_writes(["A", "B"], ["A", "B", "JTAG", "UART"], "T") == [
        {"range": "'T'!C1", "values": [["JTAG", "UART"]]}
    ]


def test_records_load_bringup_json_and_derive_switch_port(tmp_path):
    rec = {"fpga_device_dna": "0x0054b48664b04854", "switch": "sw-netgear-s3300-1 (sw2)", "port": 48}
    (tmp_path / "88a29e458577.json").write_text(json.dumps(rec))
    [got] = records.load([tmp_path])
    assert got["switch_port"] == "sw2/48"
    assert got["_source"].endswith("88a29e458577.json")


def test_records_without_a_dna_are_refused(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({"rpi_serial": "0cd35697db04a4ab"}))
    with pytest.raises(records.RecordError, match="fpga_device_dna"):
        records.load([tmp_path / "x.json"])


def test_records_empty_directory_is_an_error(tmp_path):
    with pytest.raises(records.RecordError, match="no records"):
        records.load([tmp_path])


class FakeSheet:
    def __init__(self, header, rows):
        self.header, self.rows = header, rows
        self.account = "fake@example"
        self.written = []
        self.appended = []
        self.columns = len(header)

    def tabs(self):
        return "Fake", {"Acorn/LiteFury/NiteFury": {"sheetId": 1, "gridProperties": {"columnCount": self.columns}}}

    def read(self, tab):
        return list(self.header), [list(r) for r in self.rows]

    def ensure_columns(self, tab, count):
        grew = max(0, count - self.columns)
        self.columns = max(self.columns, count)
        return grew

    def write(self, tab, data):
        self.written += data
        for d in data:
            cell = d["range"].split("!")[1]
            col = (
                sum((ord(c) - 64) * 26**i for i, c in enumerate(reversed("".join(ch for ch in cell if ch.isalpha()))))
                - 1
            )
            row = int("".join(ch for ch in cell if ch.isdigit()))
            target = self.header if row == 1 else self.rows[row - 2]
            for j, v in enumerate(d["values"][0]):
                while len(target) <= col + j:
                    target.append("")
                target[col + j] = v
        return sum(len(d["values"][0]) for d in data)

    def append_rows(self, tab, rows):
        self.appended += rows
        self.rows += [list(r) for r in rows]
        return len(rows)


HEADER = ["Site", "RPi Serial Number", "FPGA Device DNA", "IP", "Cable Color"]


def test_apply_writes_only_the_proposal_then_verifies(tmp_path, monkeypatch, capsys):
    rec = {
        "fpga_device_dna": "0x0054b48664b04854",
        "rpi_serial": "0cd35697db04a4ab",
        "ip": "10.21.2.48",
        "site": "welland",
        "cable_color": "never",
        "jtag": "PASS",
    }
    (tmp_path / "r.json").write_text(json.dumps(rec))
    fake = FakeSheet(HEADER, [["welland", "", "", "", "red"]])
    monkeypatch.setattr(cli.sheet_io, "Sheet", lambda key: fake)
    rc = cli.main(["apply", "--yes", str(tmp_path / "r.json")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert fake.columns == 6 and fake.header[5] == "JTAG"
    assert fake.rows[0] == ["welland", "0cd35697db04a4ab", "0x0054b48664b04854", "10.21.2.48", "red", "PASS"]
    assert "verified" in out
    ranges = [d["range"] for d in fake.written]
    assert "'Acorn/LiteFury/NiteFury'!E2" not in ranges, "the human column was never written"


def test_diff_writes_nothing_and_exits_nonzero_on_conflict(tmp_path, monkeypatch, capsys):
    rec = {"fpga_device_dna": "0x0054b48664b04854", "rpi_serial": "0cd35697db04a4ab"}
    (tmp_path / "r.json").write_text(json.dumps(rec))
    fake = FakeSheet(HEADER, [["welland", "ffffffffffffffff", "0x0054b48664b04854", "", ""]])
    monkeypatch.setattr(cli.sheet_io, "Sheet", lambda key: fake)
    rc = cli.main(["diff", str(tmp_path / "r.json")])
    assert rc == 1
    assert fake.written == [] and fake.appended == []
    assert "CONFLICT" in capsys.readouterr().out


def test_apply_without_yes_asks_and_a_non_yes_writes_nothing(tmp_path, monkeypatch, capsys):
    rec = {"fpga_device_dna": "0x0054b48664b04854", "ip": "10.21.2.48", "site": "welland"}
    (tmp_path / "r.json").write_text(json.dumps(rec))
    fake = FakeSheet(HEADER, [["welland", "", "", "", ""]])
    monkeypatch.setattr(cli.sheet_io, "Sheet", lambda key: fake)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert cli.main(["apply", str(tmp_path / "r.json")]) == 2
    assert fake.written == []
    assert "nothing written" in capsys.readouterr().out


def test_key_comes_from_the_flag_then_the_environment_and_has_no_default():
    assert sheet_io.resolve_key("a.json", {"GOOGLE_APPLICATION_CREDENTIALS": "b.json"}) == "a.json"
    assert sheet_io.resolve_key(None, {"GOOGLE_APPLICATION_CREDENTIALS": "b.json"}) == "b.json"
    with pytest.raises(sheet_io.MissingKey, match="--key"):
        sheet_io.resolve_key(None, {})


def test_cli_without_a_key_exits_with_the_reason(tmp_path, monkeypatch):
    (tmp_path / "r.json").write_text(json.dumps({"fpga_device_dna": "0x0054b48664b04854"}))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(SystemExit, match="no service-account key"):
        cli.main(["diff", str(tmp_path / "r.json")])
