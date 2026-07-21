"""
Real HL7v2 pipe-delimited message parser (Active_File.md task 11).

Scoped, not full-spec: this correctly tokenizes segment/field/component/
repetition structure for *any* segment type, using the message's own
self-declared separators (MSH-1 field separator, MSH-2 encoding characters)
rather than hardcoded assumptions -- that's the actually-correct way to
parse HL7v2, not a shortcut. It does not implement the full HL7v2 standard
(no Z-segments, no escape-sequence decoding, no message-type-specific
validation) -- it implements the generic envelope every message shares.

Segment *semantics* (what PID-5 means, what makes a message an ORU^R01) are
the caller's job (see synapse/extraction.py's _extract_hl7_oru), not this
module's -- this module only tokenizes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class Hl7ParseError(ValueError):
    pass


@dataclass
class Hl7Field:
    """A field's raw text, decomposable into repetitions -> components."""

    raw: str
    component_sep: str
    repetition_sep: str
    subcomponent_sep: str

    def repetitions(self) -> list[str]:
        if not self.raw:
            return [""]
        return self.raw.split(self.repetition_sep)

    def component(self, index: int, *, repetition: int = 0) -> str:
        """1-based component index within the given (0-based) repetition."""
        reps = self.repetitions()
        if repetition >= len(reps):
            return ""
        comps = reps[repetition].split(self.component_sep)
        if index < 1 or index > len(comps):
            return ""
        return comps[index - 1]

    def __str__(self) -> str:
        return self.raw

    def __bool__(self) -> bool:
        return bool(self.raw)


@dataclass
class Hl7Segment:
    name: str
    fields: list[Hl7Field]

    def field(self, index: int) -> Optional[Hl7Field]:
        """1-based field index (field name's own segment id is `.name`)."""
        if index < 1 or index > len(self.fields):
            return None
        return self.fields[index - 1]

    def value(self, index: int, component: int = 0) -> str:
        """Convenience: raw field text, or a specific 1-based component."""
        f = self.field(index)
        if f is None:
            return ""
        if component <= 0:
            return f.raw
        return f.component(component)


@dataclass
class Hl7Message:
    segments: list[Hl7Segment]
    field_sep: str
    component_sep: str
    repetition_sep: str
    escape_char: str
    subcomponent_sep: str

    def get(self, name: str) -> list[Hl7Segment]:
        return [s for s in self.segments if s.name == name]

    def first(self, name: str) -> Optional[Hl7Segment]:
        rows = self.get(name)
        return rows[0] if rows else None


def looks_like_hl7(text: str) -> bool:
    return text.lstrip().startswith("MSH")


def extract_nte_free_text(msg: Hl7Message) -> str:
    """
    Genuinely unstructured free text from a message -- the NTE (Notes and
    Comments) segment, NTE-3, present in any HL7v2 message type. Used to
    scope the residual/LLM path to text no deterministic parser already
    consumed, instead of the whole already-structured pipe-delimited
    message (every OBX/PID/OBR field already has a dedicated, correctly-
    typed extraction path -- re-feeding them to an LLM as "free text"
    both wastes a call and invites the model to reinterpret a value that
    was already read precisely).
    """
    lines: list[str] = []
    for seg in msg.get("NTE"):
        text = seg.value(3).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def parse_hl7_message(text: str) -> Hl7Message:
    """
    Parse a single HL7v2 pipe-delimited message using its own declared
    separators. Raises Hl7ParseError on anything not shaped like a message
    (caller should treat that as "not this format", not crash).
    """
    if not text or not text.strip():
        raise Hl7ParseError("empty message")

    raw_segments = [
        line
        for line in text.replace("\r\n", "\r").replace("\n", "\r").split("\r")
        if line.strip()
    ]
    if not raw_segments or not raw_segments[0].startswith("MSH"):
        raise Hl7ParseError("message does not start with an MSH segment")

    msh_line = raw_segments[0]
    if len(msh_line) < 8:
        raise Hl7ParseError("MSH segment too short to declare separators")

    field_sep = msh_line[3]
    encoding = msh_line[4:8]  # conventionally ^~\& = component/repetition/escape/subcomponent
    component_sep = encoding[0] if len(encoding) > 0 else "^"
    repetition_sep = encoding[1] if len(encoding) > 1 else "~"
    escape_char = encoding[2] if len(encoding) > 2 else "\\"
    subcomponent_sep = encoding[3] if len(encoding) > 3 else "&"

    segments: list[Hl7Segment] = []
    for line in raw_segments:
        parts = line.split(field_sep)
        name = parts[0]
        if name == "MSH":
            # MSH-1 is the separator character itself, consumed by split()
            # rather than appearing as a token; MSH-2 is the encoding-chars
            # field, which *does* appear as parts[1].
            raw_fields = [field_sep, encoding] + parts[2:]
        else:
            raw_fields = parts[1:]
        fields = [
            Hl7Field(
                raw=raw,
                component_sep=component_sep,
                repetition_sep=repetition_sep,
                subcomponent_sep=subcomponent_sep,
            )
            for raw in raw_fields
        ]
        segments.append(Hl7Segment(name=name, fields=fields))

    return Hl7Message(
        segments=segments,
        field_sep=field_sep,
        component_sep=component_sep,
        repetition_sep=repetition_sep,
        escape_char=escape_char,
        subcomponent_sep=subcomponent_sep,
    )
