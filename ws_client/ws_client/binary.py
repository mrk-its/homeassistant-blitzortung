"""Binary strike format consumed by the Home Assistant integration."""

import struct

# Bump the version on any payload change, so old clients don't misparse new messages.
TOPIC_PREFIX = "b/1"

# lat, lon (float32, ~1 m precision), strike time in ns since epoch
STRIKE = struct.Struct("<ffq")


def encode(lat: float, lon: float, time_ns: int) -> bytes:
    """Pack a strike into the binary payload."""
    return STRIKE.pack(lat, lon, time_ns)
