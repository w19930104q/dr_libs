"""Construct the minimal deterministic case where the two ORIGINAL open paths
diverge in outcome.

Key idea: make the block header itself sit on the corrupted page so that:
  - read path (recover mode): skips the bad page, and the NEXT page begins with
    a valid block header -> resyncs and opens successfully.
  - seek path (fail mode): the same skip hits fail-on-CRC -> open fails.

Layout:
  page 0 BOS/STREAMINFO
  page 1 VORBIS_COMMENT (not last)
  page 2 a full-page unknown block piece (continues)
  page 3 block terminator + an ENTIRE valid VORBIS_COMMENT block on one page
  page 4 audio
We CRC-corrupt page 3's first byte (the terminator region) with stale CRC.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oggtool import parse_pages
from craft_multiblock import make_page, crc_ogg, flac_block_header

GEN = "/home/liiing/feedback/uid28350/work/gen"
CASES = "/home/liiing/feedback/uid28350/work/cases"


def main():
    ref = open(os.path.join(GEN, "tone.oga"), "rb").read()
    ref_pages = parse_pages(ref)
    serial = ref_pages[0].serial
    seq = 0
    p0 = bytes(ref_pages[0].raw)
    seq += 1

    vc = struct.pack("<I", 5) + b"hello" + struct.pack("<I", 0)
    p1 = make_page(serial, seq, 0x00, 0, [flac_block_header(4, len(vc), False) + vc])
    seq += 1

    # Unknown block (type 100): piece 1 fills a page exactly and continues.
    FULL = 255 * 255
    piece2_len = 100
    payload = (FULL - 4) + piece2_len
    hdr = flac_block_header(100, payload, last=False)
    p2 = make_page(serial, seq, 0x00, 0, [hdr + b"\x55" * (FULL - 4)], continues=True)
    seq += 1

    # Page 3: tiny terminator of the unknown block, then a complete valid
    # VORBIS_COMMENT (last metadata block) in the SAME page via two packets.
    vc2 = struct.pack("<I", 3) + b"bye" + struct.pack("<I", 0)
    vc2_pkt = flac_block_header(4, len(vc2), True) + vc2
    # Two packets on one page: piece A (unknown terminator) + piece B (comment).
    body_a = b"\x55" * piece2_len
    body_b = vc2_pkt
    # Build the segment table manually for two terminating packets.
    def lacing_for(n):
        q, r = divmod(n, 255)
        assert q + 1 <= 255
        return [255] * q + [r]
    seg = lacing_for(len(body_a)) + lacing_for(len(body_b))
    assert len(seg) <= 255
    header = b"OggS" + bytes([0, 0x01]) + struct.pack("<q", 0)  # CONT (page continues prior packet)
    header += struct.pack("<II", serial, seq) + struct.pack("<I", 0)
    header += bytes([len(seg)]) + bytes(seg)
    p3 = bytearray(header + body_a + body_b)
    struct.pack_into("<I", p3, 22, crc_ogg(bytes(p3)))
    seq += 1

    # Audio pages spliced.
    audio = []
    for ap in ref_pages[2:]:
        h = b"OggS" + bytes([0, ap.header_type]) + struct.pack("<q", ap.granule)
        h += struct.pack("<II", serial, seq) + struct.pack("<I", 0)
        h += bytes([len(ap.seg_table)]) + bytes(ap.seg_table)
        pg = bytearray(h + bytes(ap.body))
        struct.pack_into("<I", pg, 22, crc_ogg(bytes(pg)))
        audio.append(bytes(pg))
        seq += 1

    clean = b"".join([p0, bytes(p1), bytes(p2), bytes(p3)] + audio)
    open(os.path.join(CASES, "i_boundary_clean.oga"), "wb").write(clean)

    # Corrupt the FIRST body byte of page 3 (start of unknown-block terminator).
    pages = parse_pages(clean)
    pages[3].raw[pages[3].body_off] ^= 0xFF
    open(os.path.join(CASES, "i_boundary_crc.oga"), "wb").write(
        b"".join(bytes(p.raw) for p in pages))

    print("crafted boundary case")
    for p in parse_pages(clean):
        print(f"  seq={p.sequence} type={p.header_type:#x} segs={p.seg_count} body={len(p.body)} pkts={len(list(p.packets()))}")


if __name__ == "__main__":
    main()
