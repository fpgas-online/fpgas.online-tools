# SPDX-License-Identifier: Apache-2.0
"""The only module that talks to Google Sheets.

Reads a tab as (header, rows); writes exactly the cells a sheetmap.Result names.
Credentials: a Google service-account key file for an account with Editor on the
sheet, from --key or GOOGLE_APPLICATION_CREDENTIALS. There is no default path:
where the key lives is the operator's business, not this repository's. The key's
contents are never printed.
"""

import json
import os

SHEET_ID = "1CY38U9o4KPCZvfdblJWgpEBKLCnMhlQipjTqfH6QVOw"  # "fpgas.online - FPGA Board Tracking Info"
KEY_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class MissingKey(Exception):
    pass


def resolve_key(key_path=None, environ=os.environ):
    """The key file to use: an explicit path wins, then $GOOGLE_APPLICATION_CREDENTIALS."""
    path = key_path or environ.get(KEY_ENV)
    if not path:
        raise MissingKey(f"no service-account key: pass --key PATH or set {KEY_ENV}")
    return path


def col_letter(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    if index < 0:
        raise ValueError(index)
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def plan_writes(result, tab):
    """The value ranges an apply has to write for a sheetmap.Result: one per changed cell, plus
    the header cells for any appended columns. New rows are appended separately."""
    data = []
    for u in result.updates:
        data.append({"range": f"'{tab}'!{col_letter(u.column)}{u.row}", "values": [[u.new]]})
    return data


def header_writes(old_header, new_header, tab):
    if len(new_header) <= len(old_header):
        return []
    start = len(old_header)
    return [{"range": f"'{tab}'!{col_letter(start)}1", "values": [list(new_header[start:])]}]


class Sheet:
    def __init__(self, key_path=None, sheet_id=SHEET_ID):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        with open(resolve_key(key_path)) as f:
            info = json.load(f)
        self.account = info.get("client_email", "?")
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        self.api = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()
        self.sheet_id = sheet_id

    def tabs(self):
        meta = self.api.get(spreadsheetId=self.sheet_id, fields="properties.title,sheets.properties").execute()
        return meta["properties"]["title"], {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}

    def read(self, tab):
        got = self.api.values().get(spreadsheetId=self.sheet_id, range=f"'{tab}'").execute().get("values", [])
        if not got:
            raise RuntimeError(f"tab {tab!r} is empty (no header row)")
        return got[0], got[1:]

    def ensure_columns(self, tab, count):
        _, props = self.tabs()
        p = props[tab]
        have = p["gridProperties"]["columnCount"]
        if have >= count:
            return 0
        self.api.batchUpdate(
            spreadsheetId=self.sheet_id,
            body={
                "requests": [
                    {"appendDimension": {"sheetId": p["sheetId"], "dimension": "COLUMNS", "length": count - have}}
                ]
            },
        ).execute()
        return count - have

    def write(self, tab, data):
        if not data:
            return 0
        r = (
            self.api.values()
            .batchUpdate(spreadsheetId=self.sheet_id, body={"valueInputOption": "RAW", "data": data})
            .execute()
        )
        return r.get("totalUpdatedCells", 0)

    def append_rows(self, tab, rows):
        if not rows:
            return 0
        r = (
            self.api.values()
            .append(
                spreadsheetId=self.sheet_id,
                range=f"'{tab}'",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            )
            .execute()
        )
        return r.get("updates", {}).get("updatedRows", 0)
