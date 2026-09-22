# SPDX-License-Identifier: Apache-2.0
"""sheetmap: records -> sheet cell updates, with the rules Tim set on 2026-09-22.

- rows are keyed by FPGA Device DNA first, RPi serial second; port / IP / name never
- identity cells that are non-empty and differ are conflicts, never overwritten
- human-entered columns are never written
- a record with no row goes into a placeholder row for its site, else a new row
"""

import pytest

from fleetsheet import sheetmap as sm

HEADER = [
    "Port",
    "Site",
    "Name",
    "Port",
    "IP",
    "RPi Uplink MAC",
    "RPi WLAN MAC",
    "RPi Serial Number",
    "Cable Color",
    "Location",
    "RPi Type + Memory",
    "RPi Camera",
    "FPGA Board PCB Revision",
    "FPGA Device DNA",
    "FPGA Part",
    "FPGA Memory",
    "FPGA SPI Flash",
]
# A real placeholder row from the sheet: no DNA, no serial, junk in some identity cells.
PLACEHOLDER = [
    "",
    "welland",
    "pi.welland.fpgas.mithis.com",
    "1022",
    "10.21.0.10",
    "",
    "",
    "",
    "",
    "",
    "Raspberry Pi 5 ?????",
    "",
    "",
    "",
    "XC7A35TICSG324-1L",
]


def blank():
    return [""] * len(HEADER)


P48 = {
    "site": "welland",
    "name": "pi-sw2-p48",
    "switch_port": "sw2/48",
    "ip": "10.21.2.48",
    "rpi_uplink_mac": "88:a2:9e:45:85:77",
    "rpi_serial": "0cd35697db04a4ab",
    "rpi_type_memory": "Raspberry Pi 5 Model B Rev 1.1, 2 GB",
    "rpi_camera": "ov5647",
    "fpga_device_dna": "0x0054b48664b04854",
    "fpga_part": "XC7A200T",
    "fpga_memory": "1 GiB DDR3",
    "fpga_spi_flash": "S25FL256S 32 MiB",
    "cable_color": "should never be written",
    "location": "should never be written",
}


def test_normalise_dna_accepts_the_forms_we_have_seen():
    assert sm.normalise_dna("0x0054b48664b04854") == "0054b48664b04854"
    assert sm.normalise_dna("0054B48664B04854") == "0054b48664b04854"
    assert sm.normalise_dna("0x0054b48664b04854 (DNA_PORT via UART and PCIe)") == "0054b48664b04854"
    assert sm.normalise_dna("") is None
    assert sm.normalise_dna("XC7A200T") is None
    assert sm.normalise_dna("not a dna") is None


def test_normalise_serial():
    assert sm.normalise_serial("0CD35697DB04A4AB") == "0cd35697db04a4ab"
    assert sm.normalise_serial(" 0cd35697db04a4ab ") == "0cd35697db04a4ab"
    assert sm.normalise_serial("") is None


def test_every_record_field_has_a_header_and_no_header_is_claimed_twice():
    headers = list(sm.FIELD_TO_HEADER.values())
    assert len(headers) == len({h.lower() for h in headers})
    assert sm.HUMAN_HEADERS.isdisjoint(h.lower() for h in headers)
    assert sm.IDENTITY_FIELDS <= set(sm.FIELD_TO_HEADER)


def test_duplicate_header_names_map_to_their_first_column_only():
    cols = sm.header_columns(HEADER)
    assert cols["port"] == 0, "the second 'Port' (legacy SSH port) is never written"
    assert cols["fpga device dna"] == 13


def test_missing_headers_are_appended_in_field_order():
    ext = sm.extended_header(HEADER, [P48])
    assert ext[: len(HEADER)] == HEADER
    added = ext[len(HEADER) :]
    assert added == [
        sm.FIELD_TO_HEADER[f] for f in sm.FIELD_TO_HEADER if f in P48 and sm.FIELD_TO_HEADER[f] not in HEADER
    ]
    assert "Cable Color" not in added


def test_new_record_takes_the_first_placeholder_row_for_its_site():
    rows = [PLACEHOLDER[:], ["", "ps1"] + PLACEHOLDER[2:], PLACEHOLDER[:]]
    result = sm.compute_updates([P48], HEADER, rows)
    assert result.conflicts == [] and result.unmatched_rows == [], "placeholder rows carry no board"
    assert [u.row for u in result.updates] and all(u.row == 2 for u in result.updates), (
        "row 2 = first welland placeholder (1-based, header is row 1)"
    )
    written = {u.header: u.new for u in result.updates}
    assert written["FPGA Device DNA"] == "0x0054b48664b04854"
    assert written["RPi Serial Number"] == "0cd35697db04a4ab"
    assert written["Port"] == "sw2/48"
    assert "Cable Color" not in written and "Location" not in written
    assert written["RPi Type + Memory"] == P48["rpi_type_memory"], (
        "placeholder junk is overwritten, the row had no board"
    )
    assert written["FPGA Part"] == "XC7A200T"
    assert result.new_rows == []


def test_new_record_with_no_placeholder_becomes_a_new_row():
    rows = [["0", "ps1", "x", "", "", "", "", "aaaaaaaaaaaaaaaa", "", "", "", "", "", "0x1111111111111111", "", "", ""]]
    result = sm.compute_updates([P48], HEADER, rows)
    assert result.updates == []
    assert len(result.new_rows) == 1
    row = result.new_rows[0]
    assert row[HEADER.index("FPGA Device DNA")] == "0x0054b48664b04854"
    assert row[HEADER.index("Cable Color")] == ""


def test_matched_by_dna_fills_empty_cells_and_leaves_filled_identity_alone():
    row = blank()
    row[HEADER.index("FPGA Device DNA")] = "0054B48664B04854"
    row[HEADER.index("RPi Serial Number")] = "0cd35697db04a4ab"
    row[HEADER.index("Cable Color")] = "red"
    result = sm.compute_updates([P48], HEADER, [row])
    assert result.conflicts == [] and result.unmatched_rows == [] and result.new_rows == []
    headers = {u.header for u in result.updates}
    assert "FPGA Device DNA" not in headers, "same value in a different spelling is not an update"
    assert "Cable Color" not in headers
    assert "RPi Uplink MAC" in headers and "IP" in headers


def test_identity_cell_that_differs_is_a_conflict_not_an_update():
    row = blank()
    row[HEADER.index("FPGA Device DNA")] = "0x0054b48664b04854"
    row[HEADER.index("RPi Serial Number")] = "ffffffffffffffff"
    result = sm.compute_updates([P48], HEADER, [row])
    assert [(c.header, c.old, c.new) for c in result.conflicts] == [
        ("RPi Serial Number", "ffffffffffffffff", "0cd35697db04a4ab")
    ]
    assert not any(u.header == "RPi Serial Number" for u in result.updates)


def test_live_cell_that_differs_is_an_update():
    row = blank()
    row[HEADER.index("FPGA Device DNA")] = "0x0054b48664b04854"
    row[HEADER.index("IP")] = "10.21.2.46"
    result = sm.compute_updates([P48], HEADER, [row])
    ip = [u for u in result.updates if u.header == "IP"]
    assert [(u.old, u.new) for u in ip] == [("10.21.2.46", "10.21.2.48")]
    assert result.conflicts == []


def test_dna_wins_over_serial_when_they_disagree():
    by_dna = blank()
    by_dna[HEADER.index("FPGA Device DNA")] = "0x0054b48664b04854"
    by_serial = blank()
    by_serial[HEADER.index("RPi Serial Number")] = "0cd35697db04a4ab"
    by_serial[HEADER.index("FPGA Device DNA")] = "0x2222222222222222"
    result = sm.compute_updates([P48], HEADER, [by_serial, by_dna])
    assert all(u.row == 3 for u in result.updates)
    assert result.unmatched_rows == [0]


def test_serial_only_match_is_reported_as_a_swap_hint():
    row = blank()
    row[HEADER.index("RPi Serial Number")] = "0cd35697db04a4ab"
    row[HEADER.index("FPGA Device DNA")] = "0x2222222222222222"
    result = sm.compute_updates([P48], HEADER, [row])
    assert [(c.header, c.old, c.new) for c in result.conflicts] == [
        ("FPGA Device DNA", "0x2222222222222222", "0x0054b48664b04854")
    ]
    assert result.new_rows == [] and result.updates == []


def test_two_records_with_the_same_dna_is_an_error():
    with pytest.raises(sm.SheetMapError, match="0054b48664b04854"):
        sm.compute_updates([P48, dict(P48, rpi_serial="1111111111111111")], HEADER, [])


def test_record_without_a_dna_is_an_error():
    with pytest.raises(sm.SheetMapError, match="fpga_device_dna"):
        sm.compute_updates([{k: v for k, v in P48.items() if k != "fpga_device_dna"}], HEADER, [])


def test_two_rows_with_the_same_dna_is_an_error():
    row = blank()
    row[HEADER.index("FPGA Device DNA")] = "0x0054b48664b04854"
    with pytest.raises(sm.SheetMapError, match="rows 2 and 3"):
        sm.compute_updates([P48], HEADER, [row, row[:]])


def test_short_rows_are_padded():
    row = ["", "welland"]
    result = sm.compute_updates([P48], HEADER, [row])
    assert all(u.row == 2 for u in result.updates)


def test_updates_for_headers_beyond_the_current_grid_use_the_extended_header():
    rec = dict(P48, jtag="PASS")
    result = sm.compute_updates([rec], HEADER, [PLACEHOLDER[:]])
    jt = [u for u in result.updates if u.header == "JTAG"]
    assert len(jt) == 1 and jt[0].column == len(HEADER) and jt[0].new == "PASS"
    assert result.header[len(HEADER)] == "JTAG"


def test_render_is_stable_and_names_every_kind_of_change():
    row = blank()
    row[HEADER.index("FPGA Device DNA")] = "0x0054b48664b04854"
    row[HEADER.index("RPi Serial Number")] = "ffffffffffffffff"
    text = sm.render(sm.compute_updates([P48], HEADER, [row]))
    assert "CONFLICT" in text and "RPi Serial Number" in text
    assert "row 2" in text
    assert "UPDATE" in text
