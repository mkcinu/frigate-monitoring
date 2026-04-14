"""Shared type aliases for Frigate protocol constants."""

from __future__ import annotations

from enum import IntEnum
from typing import Literal

ReviewType = Literal["new", "update", "end"]
Severity = Literal["alert", "detection"]
Trigger = Literal["start", "best"]


class Weekday(IntEnum):
    """Enumeration of week days, starting from 0 (Monday) to match datetime.weekday()."""

    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6

    @classmethod
    def from_str(cls, s: str) -> Weekday:
        """Parse a string into a Weekday (case-insensitive, supports long/short names)."""
        s = s.lower()
        if s.isdigit():
            return cls(int(s))
        mapping = {
            "mon": cls.MON,
            "monday": cls.MON,
            "tue": cls.TUE,
            "tuesday": cls.TUE,
            "wed": cls.WED,
            "wednesday": cls.WED,
            "thu": cls.THU,
            "thursday": cls.THU,
            "fri": cls.FRI,
            "friday": cls.FRI,
            "sat": cls.SAT,
            "saturday": cls.SAT,
            "sun": cls.SUN,
            "sunday": cls.SUN,
        }
        if s not in mapping:
            raise ValueError(f"Unknown weekday: {s!r}")
        return mapping[s]
