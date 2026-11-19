"""Definitive divergence reproduction: a large UNKNOWN metadata block spanning
three Ogg pages, with the *middle* page CRC-corrupted, followed by a valid
metadata block and then audio.

  page 0 BOS/STREAMINFO
  page 1 VORBIS_COMMENT (not last)
  page 2 unknown block, piece 1/3 (fresh, full page)
  page 3 unknown block, piece 2/3 (continued, full page) <- CRC corrupted
  page 4 unknown block, piece 3/3 (continued)
  page 5 VORBIS_COMMENT (last metadata block)
  page 6 audio (spliced)

Run with: python3 -I craft_divergence.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oggtool import parse_pages              # noqa: E402
from craft_multiblock import make_page, crc_ogg, flac_block_header  # noqa: E402

GEN = "/home/liiing/feedback/uid28350/work/gen"
CASES = "/home/liiing/feedback/uid28350/work/cases"


def splice_audio(ref_pages, serial, seq):
    out = []
    for ap in ref_pages[2:]:
        seg = ap.seg_table
        header = b"OggS" + bytes([0, ap.header_type]) + struct.pack("<q", ap.granule)
        header += struct.pack("<II", serial, seq) + struct.pack("<I", 0)
        header += bytes([len(seg)]) + bytes(seg)
        rebuilt = bytearray(header + bytes(ap.body))
        struct.pack_into("<I", rebuilt, 22, crc_ogg(bytes(rebuilt)))
        out.append(bytes(rebuilt))
        seq += 1
    return out, seq


def main():
    ref = open(os.path.join(GEN, "tone.oga"), "rb").read()
    ref_pages = parse_pages(ref)
    serial = ref_pages[0].serial
    seq = 0

    p0 = bytes(ref_pages[0].raw)
    seq += 1

    # Page 1: VORBIS_COMMENT, not last.
    vendor = b"drflac-test"
    comment = b"ARTIST=harness"
    vc = struct.pack("<I", len(vendor)) + vendor
    vc += struct.pack("<I", 1) + struct.pack("<I", len(comment)) + comment
    p1 = make_page(serial, seq, 0x00, 0, [flac_block_header(4, len(vc), False) + vc])
    seq += 1

    # Unknown block (type 100) across two pages. Piece 1 fills a page exactly
    # (continuation); piece 2 terminates. Corrupting piece 2 (the final page of
    # the block) makes read-recovery skip it and land exactly on the next valid
    # metadata block, while seek-based skipping fails on the CRC.
    FULL = 255 * 255                 # 65025
    piece2_len = 6000
    payload_len = (FULL - 4) + piece2_len   # header rides in piece 1
    hdr = flac_block_header(100, payload_len, last=False)
    body_marker = b"\xAA"
    p2 = make_page(serial, seq, 0x00, 0,
                   [hdr + body_marker * (FULL - 4)], continues=True)
    seq += 1
    p3 = make_page(serial, seq, 0x01, 0, [body_marker * piece2_len])
    seq += 1

    # Trailing valid VORBIS_COMMENT, last metadata block.
    vendor2 = b"drflac-test-2"
    comment2 = b"ALBUM=recovery"
    vc2 = struct.pack("<I", len(vendor2)) + vendor2
    vc2 += struct.pack("<I", 1) + struct.pack("<I", len(comment2)) + comment2
    p5 = make_page(serial, seq, 0x00, 0, [flac_block_header(4, len(vc2), True) + vc2])
    seq += 1

    audio, seq = splice_audio(ref_pages, serial, seq)

    clean = b"".join([p0, bytes(p1), bytes(p2), bytes(p3), bytes(p5)] + audio)
    open(os.path.join(CASES, "h_unknown_clean.oga"), "wb").write(clean)

    # Corrupt the LAST page of the unknown block (continued page, index 3).
    # Read-recovery skips it and lands on the valid VORBIS_COMMENT; seek fails.
    pages = parse_pages(clean)
    pages[3].raw[pages[3].body_off + 100] ^= 0xFF
    open(os.path.join(CASES, "h_unknown_lastpage_crc.oga"), "wb").write(
        b"".join(bytes(p.raw) for p in pages))

    # Corrupt the FIRST page (index 2) of the unknown block instead.
    pages = parse_pages(clean)
    pages[2].raw[pages[2].body_off + 12345] ^= 0xFF
    open(os.path.join(CASES, "h_unknown_firstpage_crc.oga"), "wb").write(
        b"".join(bytes(p.raw) for p in pages))

    print("crafted unknown-block cases")
    for p in parse_pages(clean):
        print(f"  seq={p.sequence} type={p.header_type:#x} segs={p.seg_count} body={len(p.body)}")


if __name__ == "__main__":
    main()
