"""Hand-craft Ogg FLAC files with multi-page metadata so the open-path
divergence is directly observable.

Layout:
  page 0  BOS: FLAC mapping header (51 B packet)
  page 1  VORBIS_COMMENT packet (small), NOT last metadata block
  page 2  PADDING packet, part 1/2 (fresh page, full 255x255 segments)
  page 3  PADDING packet, part 2/2 (continued page), last metadata block
  page 4+ audio pages spliced from the ffmpeg-generated reference

Run with: python3 -I craft_multiblock.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oggtool import parse_pages  # noqa: E402

GEN = "/home/liiing/feedback/uid28350/work/gen"
CASES = "/home/liiing/feedback/uid28350/work/cases"


def crc_ogg(page_bytes_with_zero_crc):
    from oggtool import ogg_crc32
    return ogg_crc32(page_bytes_with_zero_crc)


def make_page(serial, sequence, header_type, granule, packet_chunks, continues=False):
    """packet_chunks: bytes pieces concatenated into this page's body.
    continues=True means the packet carries on into the next page (no terminator)."""
    body = b"".join(packet_chunks)
    n = len(body)
    q, r = divmod(n, 255)
    seg = [255] * q
    if not continues:
        # Terminating segment (<255; zero when size is a multiple of 255).
        assert q + 1 <= 255
        seg.append(r)
    else:
        assert q == 255 and r == 0, "a continuing page must be exactly full"
    assert len(seg) <= 255
    header = b"OggS" + bytes([0, header_type]) + struct.pack("<q", granule)
    header += struct.pack("<II", serial, sequence)
    header += struct.pack("<I", 0)            # checksum placeholder
    header += bytes([len(seg)]) + bytes(seg)
    page = bytearray(header + body)
    crc = crc_ogg(bytes(page))
    struct.pack_into("<I", page, 22, crc)
    return page


def flac_block_header(block_type, size, last):
    b = (0x80 if last else 0x00) | (block_type & 0x7F)
    return bytes([b]) + struct.pack(">I", size)[1:]


def main():
    ref = open(os.path.join(GEN, "tone.oga"), "rb").read()
    ref_pages = parse_pages(ref)
    bos = ref_pages[0]
    audio_pages = [p.raw for p in ref_pages[2:]]   # EOS audio page(s)

    serial = bos.serial
    seq = 0

    # Page 0: BOS packet verbatim from reference.
    p0 = bytes(bos.raw)
    seq += 1

    # Page 1: VORBIS_COMMENT (block type 4), not last.
    vendor = b"drflac-test"
    comment = b"ARTIST=harness"
    vc = struct.pack("<I", len(vendor)) + vendor
    vc += struct.pack("<I", 1) + struct.pack("<I", len(comment)) + comment
    pkt1 = flac_block_header(4, len(vc), last=False) + vc
    p1 = make_page(serial, seq, 0x00, 0, [pkt1])
    seq += 1

    # PADDING block (type 1), split across two pages, NOT the last metadata block.
    # Page 2 (fresh): block header + padding bytes filling the page exactly
    # (255 lacing values of 255 = 65025 body bytes); the packet continues so the
    # page has no terminating segment.
    # Page 3 (continued): the remaining padding bytes; its last lacing value
    # terminates the packet (zero when the length is a multiple of 255).
    part1_len = 255 * 255            # 65025, exactly fills page 2
    part2_len = 5000
    # Payload bytes: page 2 holds the 4-byte block header plus (part1_len - 4)
    # padding bytes; page 3 holds part2_len more padding bytes.
    pad_payload = (part1_len - 4) + part2_len
    pad_total = pad_payload          # block size field counts payload only
    pkt2_hdr = flac_block_header(1, pad_total, last=False)
    p2 = make_page(serial, seq, 0x00, 0, [pkt2_hdr + b"\x00" * (part1_len - 4)], continues=True)
    seq += 1
    p3 = make_page(serial, seq, 0x01, 0, [b"\x00" * part2_len])  # continued, final piece
    seq += 1

    # Page 4: a second, valid VORBIS_COMMENT, last metadata block. This gives the
    # read-based recovery path a valid block header to resync on after a skipped
    # (CRC-bad) padding page, while the seek-based path fails on that page.
    vendor2 = b"drflac-test-2"
    comment2 = b"ALBUM=recovery"
    vc2 = struct.pack("<I", len(vendor2)) + vendor2
    vc2 += struct.pack("<I", 1) + struct.pack("<I", len(comment2)) + comment2
    pkt3 = flac_block_header(4, len(vc2), last=True) + vc2
    p4 = make_page(serial, seq, 0x00, 0, [pkt3])
    seq += 1

    # Re-number and re-checksum the spliced audio pages, preserving the original
    # segment table so the page's packet boundaries are unchanged.
    rebuilt_audio = []
    for ap in ref_pages[2:]:
        seg = ap.seg_table
        header = b"OggS" + bytes([0, ap.header_type]) + struct.pack("<q", ap.granule)
        header += struct.pack("<II", serial, seq) + struct.pack("<I", 0)
        header += bytes([len(seg)]) + bytes(seg)
        rebuilt = bytearray(header + bytes(ap.body))
        struct.pack_into("<I", rebuilt, 22, crc_ogg(bytes(rebuilt)))
        rebuilt_audio.append(bytes(rebuilt))
        seq += 1

    clean = b"".join([p0, bytes(p1), bytes(p2), bytes(p3), bytes(p4)] + rebuilt_audio)
    clean_path = os.path.join(CASES, "g_multiblock_clean.oga")
    open(clean_path, "wb").write(clean)

    # Corrupt page 2 (first page of the multi-page PADDING block), stale CRC.
    pages = parse_pages(clean)
    pages[2].raw[pages[2].body_off + 100] ^= 0xFF
    open(os.path.join(CASES, "g_pad_crc_firstpage.oga"), "wb").write(
        b"".join(bytes(p.raw) for p in pages))

    # Corrupt page 3 (last/continued page of PADDING), stale CRC.
    pages = parse_pages(clean)
    pages[3].raw[pages[3].body_off + 100] ^= 0xFF
    open(os.path.join(CASES, "g_pad_crc_lastpage.oga"), "wb").write(
        b"".join(bytes(p.raw) for p in pages))

    # Same corruption but with a *valid* CRC (pure content corruption inside padding;
    # padding content is ignored, so both should always agree).
    pages = parse_pages(clean)
    pages[2].raw[pages[2].body_off + 100] ^= 0xFF
    pages[2].recalc_crc()
    open(os.path.join(CASES, "g_pad_content_validcrc.oga"), "wb").write(
        b"".join(bytes(p.raw) for p in pages))

    print("crafted:", clean_path, len(clean), "bytes")
    for p in parse_pages(clean):
        print(f"  seq={p.sequence} type={p.header_type:#x} segs={p.seg_count} body={len(p.body)}")


if __name__ == "__main__":
    main()
