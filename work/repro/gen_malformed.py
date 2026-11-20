#!/usr/bin/env python3
"""Generate malformed/truncated AIFF files for failure-path testing."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
from gen_aiff import form, ssnd, comm_aifc, comm_aiff, make_float, make_pcm, s16le, f32be, RATE, FRAMES, chunk

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)


def write(name, data):
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(data)
    print(f"wrote {name} ({len(data)} bytes)")


# 1. SSND-first, truncated inside the audio payload (read returns short).
audio = make_float(2, FRAMES, f32be)
full = form("AIFC", ssnd(audio), comm_aifc(2, FRAMES, 32, RATE, "fl32"))
write("mal_ssndfirst_truncated.aifc", full[: len(full) - 40])

# 2. SSND-first with no COMM anywhere (chunk loop ends via AT_END).
write("mal_ssndfirst_nocomm.aifc", form("AIFC", ssnd(audio)))

# 3. SSND-first with an absurd SSND size to trigger the 1GB cap.
huge = b"SSND" + struct.pack(">I", 0x50000000) + struct.pack(">II", 0, 0) + b"\x00" * 16
body = b"AIFC" + huge
write("mal_ssnd_huge.aifc", b"FORM" + struct.pack(">I", len(body)) + body)

# 4. SSND-first where the declared offset exceeds the chunk size.
bad_ssnd = b"SSND" + struct.pack(">I", 16) + struct.pack(">II", 9999, 0) + b"\x00" * 8
body = b"AIFC" + bad_ssnd + comm_aifc(2, FRAMES, 32, RATE, "fl32")
write("mal_ssnd_badoffset.aifc", b"FORM" + struct.pack(">I", len(body)) + body)

# 5. Truncated right after the SSND header's offset/block fields.
head = b"FORM"
# Build a proper prefix then cut.
full2 = form("AIFC", ssnd(make_pcm(2, FRAMES, s16le, 32768)), comm_aifc(2, FRAMES, 16, RATE, "sowt"))
# Find the SSND payload start and cut 4 bytes into it.
idx = full2.find(b"SSND")
write("mal_ssnd_cut_early.aifc", full2[: idx + 8 + 8 + 4])

# 6. SSND-first with odd-sized payload (padding byte present).
odd_audio = make_pcm(2, 3, s16le, 32768)  # 12 bytes, even; force odd via raw chunk below
odd_payload = struct.pack(">II", 0, 0) + b"\x01\x02\x03"  # 8 + 3 = 11 (odd)
odd_ssnd = b"SSND" + struct.pack(">I", 11) + odd_payload + b"\x00"  # padding
body = b"AIFC" + odd_ssnd + comm_aifc(2, 3, 16, RATE, "sowt")
write("mal_ssnd_odd_padding.aifc", b"FORM" + struct.pack(">I", len(body)) + body)

# 7. Empty SSND-first (zero-length payload).
empty_ssnd = b"SSND" + struct.pack(">I", 8) + struct.pack(">II", 0, 0)
body = b"AIFC" + empty_ssnd + comm_aifc(2, FRAMES, 16, RATE, "sowt")
write("mal_ssnd_empty.aifc", b"FORM" + struct.pack(">I", len(body)) + body)
