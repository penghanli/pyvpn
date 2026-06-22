"""Replay protection for monotonically increasing packet sequence numbers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReplayWindow:
    size: int = 1024
    max_seq: int = 0
    bitmap: int = 0

    def accept(self, seq: int) -> bool:
        if seq <= 0:
            return False

        if self.max_seq == 0:
            self.max_seq = seq
            self.bitmap = 1
            return True

        if seq > self.max_seq:
            shift = seq - self.max_seq
            self.bitmap = 0 if shift >= self.size else (self.bitmap << shift)
            self.bitmap |= 1
            self.bitmap &= (1 << self.size) - 1
            self.max_seq = seq
            return True

        offset = self.max_seq - seq
        if offset >= self.size:
            return False
        mask = 1 << offset
        if self.bitmap & mask:
            return False
        self.bitmap |= mask
        return True
