"""Shared type aliases for Frigate protocol constants."""

from typing import Literal

ReviewType = Literal["new", "update", "end"]
Severity = Literal["alert", "detection"]
