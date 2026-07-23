"""
Beckman Coulter AU5800 RS-232 serial stream semantics.

Real vendor wire format (not HL7v2, not ASTM, not JSON): each line is one
flat analyte-result record framed by literal "[STX]"/"[ETX]" markers,
pipe-delimited, with a fixed 9-field body -- 5 bare positional fields
(sample/rack/tube/channel/assay identity) followed by 4 fields where 3 are
"KEY:VALUE" tokens and one (units) is bare. Confirmed against the real
sample file: all 516 data lines share exactly this 11-token shape
(STX + 9 fields + ETX), so this is straightforward positional parsing, not
a schema that needs per-line sniffing like HL7's variable segment types.

Unlike HL7 (MSH envelope + PID/ORC/OBR/OBX segments needing structural
links between them) or ASTM (H/P/O/R record hierarchy), a Beckman stream
has no envelope/segment hierarchy at all -- every line is already a
complete, self-contained result record. No STRUCTURAL_LINKS table is
needed here for the same reason HL7 and ASTM need one and this doesn't.
"""

from __future__ import annotations

import re
from collections import defaultdict

# Real Beckman AU5800 RS232 body field order, confirmed against the sample
# file's own documented "# FORMAT:" comment and verified positionally
# against all 516 data lines (fixed shape, no variation observed).
_BODY_FIELD_NAMES = (
    "sample_id",
    "rack_no",
    "tube_pos",
    "channel_id",
    "assay_abbr",
    "raw_absorbance",  # ABS:<value>
    "calculated_value",  # VAL:<value>
    "units",  # bare, no KEY: prefix
    "reagent_flag",  # FLAG:<value>
)

_LINE_RE = re.compile(r"^\[STX\]\|(.*)\|\[ETX\]\s*$")
_KV_TOKEN_RE = re.compile(r"^[A-Z]+:(.*)$")


def looks_like_beckman(payload: str) -> bool:
    """Cheap format sniff, mirroring hl7v2.looks_like_hl7's role: does this
    payload's first non-blank, non-comment line look like a Beckman RS232
    record? Comment lines (the file's own "# FORMAT:" header) are skipped
    since they're documentation, not data."""
    for line in payload.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return line.startswith("[STX]|")
    return False


def _parse_record(line: str) -> dict[str, str] | None:
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    tokens = m.group(1).split("|")
    if len(tokens) != len(_BODY_FIELD_NAMES):
        return None
    row: dict[str, str] = {}
    for name, token in zip(_BODY_FIELD_NAMES, tokens):
        kv = _KV_TOKEN_RE.match(token)
        row[name] = kv.group(1) if kv else token
    return row


def extract_beckman_rows(payload: str) -> list[dict[str, str]]:
    """Row-oriented extraction: one dict per [STX]...[ETX] line -- already
    the correct grain (one result per line), no HL7-style multi-segment
    grouping needed."""
    rows: list[dict[str, str]] = []
    for line in payload.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = _parse_record(line)
        if row:
            rows.append(row)
    return rows


def extract_beckman_fields(payload: str) -> dict[str, list[str]]:
    """Column-oriented counterpart for schema profiling (Explore/Schema
    View/matching) -- field_name -> every observed value, same shape
    _extract_field_values returns for every other format."""
    field_values: dict[str, list[str]] = defaultdict(list)
    for row in extract_beckman_rows(payload):
        for key, val in row.items():
            if val:
                field_values[key].append(val)
    return dict(field_values)
