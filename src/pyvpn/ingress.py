"""Bounded, ordered delivery of decrypted UDP packets to a TUN device."""

from __future__ import annotations

import asyncio
import sys
import time

from .tun import TunDevice


TUN_WRITE_BATCH_SIZE = 64
TUN_WRITE_QUEUE_SIZE = 2048
DROP_LOG_INTERVAL = 5.0


class OrderedTunWriter:
    def __init__(self, tun: TunDevice, label: str):
        self.tun = tun
        self.label = label
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=TUN_WRITE_QUEUE_SIZE)
        self.dropped = 0
        self._last_drop_log = -DROP_LOG_INTERVAL

    def offer(self, packet: bytes) -> None:
        try:
            self.queue.put_nowait(packet)
        except asyncio.QueueFull:
            self.dropped += 1
            now = time.monotonic()
            if now - self._last_drop_log >= DROP_LOG_INTERVAL:
                print(
                    f"{self.label} UDP-to-TUN queue full; dropped {self.dropped} packets total",
                    file=sys.stderr,
                    flush=True,
                )
                self._last_drop_log = now

    async def run(self) -> None:
        while True:
            batch = [await self.queue.get()]
            while len(batch) < TUN_WRITE_BATCH_SIZE:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            await self.tun.write_batch(batch)
            await asyncio.sleep(0)
