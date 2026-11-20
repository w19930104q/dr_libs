#!/usr/bin/env python3
"""Generate AIFF/AIFC/WAV test files for sequential-mode verification."""
import math
import os
import struct
import sys


def extended80(x):
    """Encode a positive number as an AIFF 80-bit IEEE extended float (10 bytes, big endian)."""
    if x == 0:
        return b"\x00" * 10
    e = math.floor(math.log2(x))
    m = x / (2 ** e)  # 1.0 <= m < 2.0
    exp = e + 16383
    mantissa = int(round(m * (2 ** 63)))
    if mantissa == 2 ** 64:  # rounding edge
        mantissa //= 2
        exp += 1
    return struct.pack(">HQ", exp, mantissa)


def pad_chunk(data):
    return data + (b"\x00" if len(data) % 2 else b"")


def chunk(fourcc, payload):
    out = fourcc.encode("ascii") + struct.pack(">I", len(payload)) + payload
    return pad_chunk(out)


def comm_aiff(channels, frames, bits, rate):
    payload = struct.pack(">hIh", channels, frames, bits) + extended80(rate)
    assert len(payload) == 18
    return chunk("COMM", payload)


def comm_aifc(channels, frames, bits, rate, codec):
    base = struct.pack(">hIh", channels, frames, bits) + extended80(rate)
    name = b""  # compression name as a Pascal string; empty is allowed
    pascal = bytes([len(name)]) + name
    if len(pascal) % 2:
        pascal += b"\x00"
    payload = base + codec.encode("ascii") + pascal
    return chunk("COMM", payload)


def ssnd(audio, offset=0, block_size=0):
    payload = struct.pack(">II", offset, block_size) + b"\x00" * offset + audio
    return chunk("SSND", payload)


def form(form_type, *chunks):
    body = form_type.encode("ascii") + b"".join(chunks)
    return b"FORM" + struct.pack(">I", len(body)) + body


def s16be(v):
    return struct.pack(">h", v)


def s16le(v):
    return struct.pack("<h", v)


def s24be(v):
    v &= 0xFFFFFF
    return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


def s8(v):
    return struct.pack(">b", v)


def f32be(v):
    return struct.pack(">f", v)


def f64be(v):
    return struct.pack(">d", v)


def sample_value(i, c, scale=16000):
    # Deterministic, covers positive and negative values.
    v = int((((i * 7 + c * 13) % 2001) - 1000) * scale / 1000)
    return v


def make_pcm(channels, frames, packer, maxv):
    out = bytearray()
    for i in range(frames):
        for c in range(channels):
            v = sample_value(i, c)
            v = max(-maxv, min(maxv - 1, v))
            out += packer(v)
    return bytes(out)


def make_float(channels, frames, packer):
    out = bytearray()
    for i in range(frames):
        for c in range(channels):
            v = (((i * 7 + c * 13) % 2001) - 1000) / 1000.0
            out += packer(v)
    return bytes(out)


RATE = 44100
FRAMES = 137
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)


def write(name, data):
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(data)
    print(f"wrote {name} ({len(data)} bytes)")


# 1. Standard AIFF, big-endian signed PCM s16, stereo.
audio = make_pcm(2, FRAMES, s16be, 32768)
write("aiff_pcm16be_st.aiff", form("AIFF", comm_aiff(2, FRAMES, 16, RATE), ssnd(audio)))

# 2. Standard AIFF, big-endian signed PCM s8, mono.
audio = make_pcm(1, FRAMES, s8, 128)
write("aiff_pcm8s_mono.aiff", form("AIFF", comm_aiff(1, FRAMES, 8, RATE), ssnd(audio)))

# 3. Standard AIFF, big-endian signed PCM s24, stereo (3 bytes/sample block alignment).
audio = make_pcm(2, FRAMES, s24be, 2 ** 23)
write("aiff_pcm24be_st.aiff", form("AIFF", comm_aiff(2, FRAMES, 24, RATE), ssnd(audio)))

# 4. AIFC sowt: little-endian signed PCM s16, stereo.
audio = make_pcm(2, FRAMES, s16le, 32768)
write("aifc_sowt16_st.aifc", form("AIFC", comm_aifc(2, FRAMES, 16, RATE, "sowt"), ssnd(audio)))

# 5. AIFC sowt: little-endian signed PCM s24, mono (3 bytes/sample block alignment).
def s24le(v):
    v &= 0xFFFFFF
    return bytes([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF])


audio = make_pcm(1, FRAMES, s24le, 2 ** 23)
write("aifc_sowt24_mono.aifc", form("AIFC", comm_aifc(1, FRAMES, 24, RATE, "sowt"), ssnd(audio)))

# 6. AIFC fl32: big-endian IEEE float32, stereo.
audio = make_float(2, FRAMES, f32be)
write("aifc_fl32_st.aifc", form("AIFC", comm_aifc(2, FRAMES, 32, RATE, "fl32"), ssnd(audio)))

# 7. AIFC fl64: big-endian IEEE float64, mono (8 bytes/sample block alignment).
audio = make_float(1, FRAMES, f64be)
write("aifc_fl64_mono.aifc", form("AIFC", comm_aifc(1, FRAMES, 64, RATE, "fl64"), ssnd(audio)))

# 8. Standard AIFF s16 stereo with a non-zero SSND offset (8 bytes).
audio = make_pcm(2, FRAMES, s16be, 32768)
write("aiff_pcm16be_offset.aiff", form("AIFF", comm_aiff(2, FRAMES, 16, RATE), ssnd(audio, offset=8)))

# 9. AIFC fl32 stereo with SSND offset 4.
audio = make_float(2, FRAMES, f32be)
write("aifc_fl32_offset.aifc", form("AIFC", comm_aifc(2, FRAMES, 32, RATE, "fl32"), ssnd(audio, offset=4)))

# 10. AIFC sowt s16 with SSND before COMM (chunk order stress).
audio = make_pcm(2, FRAMES, s16le, 32768)
write("aifc_sowt16_ssndfirst.aifc", form("AIFC", ssnd(audio), comm_aifc(2, FRAMES, 16, RATE, "sowt")))

# 11. AIFC fl32 with SSND before COMM.
audio = make_float(2, FRAMES, f32be)
write("aifc_fl32_ssndfirst.aifc", form("AIFC", ssnd(audio), comm_aifc(2, FRAMES, 32, RATE, "fl32")))

# 11b. Standard AIFF s16 SSND-first with a non-zero offset.
audio = make_pcm(2, FRAMES, s16be, 32768)
write("aiff_pcm16be_ssndfirst_offset.aiff", form("AIFF", ssnd(audio, offset=8), comm_aiff(2, FRAMES, 16, RATE)))

# 11c. AIFC sowt s24 SSND-first, mono.
audio = make_pcm(1, FRAMES, s24le, 2 ** 23)
write("aifc_sowt24_ssndfirst.aifc", form("AIFC", ssnd(audio), comm_aifc(1, FRAMES, 24, RATE, "sowt")))

# 11d. AIFC fl64 SSND-first, mono.
audio = make_float(1, FRAMES, f64be)
write("aifc_fl64_ssndfirst.aifc", form("AIFC", ssnd(audio), comm_aifc(1, FRAMES, 64, RATE, "fl64")))

# 11e. Standard AIFF signed s8 SSND-first, mono.
audio = make_pcm(1, FRAMES, s8, 128)
write("aiff_pcm8s_ssndfirst.aiff", form("AIFF", ssnd(audio), comm_aiff(1, FRAMES, 8, RATE)))

# 11f. SSND-first with extra unknown chunks between SSND and COMM.
def unknown_chunk(fourcc, payload):
    return chunk(fourcc, payload)

audio = make_float(2, FRAMES, f32be)
write("aifc_fl32_ssndfirst_extra.aifc", form("AIFC", ssnd(audio),
      unknown_chunk("NAME", b"test name"), unknown_chunk("(c) ", b"no copyright"),
      comm_aifc(2, FRAMES, 32, RATE, "fl32")))

# 12. Plain RIFF WAV, PCM s16 stereo (regression guard for the normal WAV path).
wav = bytearray()
wav += b"RIFF" + struct.pack("<I", 0) + b"WAVE"
fmt = struct.pack("<HHIIHH", 1, 2, RATE, RATE * 2 * 2, 4, 16)
wav += b"fmt " + struct.pack("<I", len(fmt)) + fmt
audio = make_pcm(2, FRAMES, s16le, 32768)
wav += b"data" + struct.pack("<I", len(audio)) + audio
struct.pack_into("<I", wav, 4, len(wav) - 8)
write("wav_pcm16le_st.wav", bytes(wav))
