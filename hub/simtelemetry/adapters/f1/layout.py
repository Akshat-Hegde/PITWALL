"""Declarative packed-struct layouts mirroring the C structs in the spec files.

A layout is written as (type, name, count) tuples using the spec's own type and field
names, so tests can compare it field-for-field against docs/*.txt. All layouts are
little-endian and packed ("<" in the struct module: no alignment padding).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Iterator, Union as TypingUnion

PRIMITIVES: dict[str, str] = {
    "uint8": "B",
    "int8": "b",
    "uint16": "H",
    "int16": "h",
    "uint32": "I",
    "uint": "I",  # TimeTrialDataSet uses plain "uint"; 32-bit per the documented sizes
    "float": "f",
    "double": "d",
    "uint64": "Q",
    "char": "s",  # char[N] unpacks as N raw bytes
}

FieldType = TypingUnion[str, "Layout", "Union"]


@dataclass(frozen=True, slots=True)
class Field:
    type: FieldType
    name: str
    count: int = 1

    @property
    def type_name(self) -> str:
        return self.type if isinstance(self.type, str) else self.type.name

    @property
    def fmt(self) -> str:
        if isinstance(self.type, str):
            code = PRIMITIVES[self.type]
            if code == "s":
                return f"{self.count}s"
            return code if self.count == 1 else f"{self.count}{code}"
        return self.type.fmt * self.count


class Union:
    """C union: occupies the size of its largest member; unpacked as raw bytes."""

    def __init__(self, name: str, members: dict[str, Layout]) -> None:
        self.name = name
        self.members = members
        self.size = max(m.size for m in members.values())
        self.fmt = f"{self.size}s"


class Layout:
    def __init__(self, name: str, fields: list[tuple]) -> None:
        self.name = name
        self.fields: tuple[Field, ...] = tuple(Field(*f) for f in fields)
        self.fmt = "".join(f.fmt for f in self.fields)
        self.struct = struct.Struct("<" + self.fmt)
        self.size = self.struct.size
        self._offsets: dict[str, int] = {}
        offset = 0
        for f in self.fields:
            self._offsets[f.name] = offset
            offset += struct.calcsize("<" + f.fmt)
        assert offset == self.size

    def offset_of(self, field_name: str) -> int:
        return self._offsets[field_name]

    def unpack_from(self, buffer: bytes | bytearray | memoryview, offset: int = 0) -> dict[str, Any]:
        return self._consume(iter(self.struct.unpack_from(buffer, offset)))

    def pack(self, values: dict[str, Any] | None = None) -> bytes:
        """The inverse of unpack_from: fields missing from `values` are zero (the demo simulator uses this)."""
        flat: list[Any] = []
        self._flatten(values or {}, flat)
        return self.struct.pack(*flat)

    def _flatten(self, values: dict[str, Any], out: list[Any]) -> None:
        for f in self.fields:
            v = values.get(f.name)
            if isinstance(f.type, Layout):
                items = [v] if f.count == 1 else list(v or [])
                for i in range(f.count):
                    f.type._flatten(items[i] if i < len(items) and items[i] else {}, out)
            elif isinstance(f.type, Union) or f.type == "char":
                out.append(v if isinstance(v, (bytes, bytearray)) else b"")
            elif f.count == 1:
                out.append(v if v is not None else 0)
            else:
                items = list(v or [])
                out.extend(items[i] if i < len(items) else 0 for i in range(f.count))

    def _consume(self, values: Iterator[Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in self.fields:
            if isinstance(f.type, Layout):
                if f.count == 1:
                    out[f.name] = f.type._consume(values)
                else:
                    out[f.name] = [f.type._consume(values) for _ in range(f.count)]
            elif isinstance(f.type, Union) or f.type == "char" or f.count == 1:
                if isinstance(f.type, Union) and f.count != 1:
                    raise NotImplementedError("arrays of unions are not used by the spec")
                out[f.name] = next(values)
            else:
                out[f.name] = tuple(next(values) for _ in range(f.count))
        return out
