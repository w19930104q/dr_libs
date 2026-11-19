"""Generate corrupted Ogg-FLAC cases for dr_flac open-path consistency testing.

Run with: python3 -I make_cases.py
"""
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oggtool import parse_pages  # noqa: E402

GEN = "/home/liiing/feedback/uid28350/work/gen"
CASES = "/home/liiing/feedback/uid28350/work/cases"


def write_pages(path, pages):
    with open(path, "wb") as f:
        for p in pages:
            f.write(bytes(p.raw))


def flip_body_byte(page, body_index):
    page.raw[page.body_off + body_index] ^= 0xFF
    # Deliberately do NOT recalc CRC -> page checksum now mismatches.


def flip_header_byte(page, header_index):
    page.raw[header_index] ^= 0xFF


def make_big_comment():
    """Encode an Ogg FLAC whose VORBIS_COMMENT spans multiple Ogg pages."""
    wav = os.path.join(GEN, "tone.wav")
    # ~100KB tag value -> vorbiscomment packet ~100KB -> spans >=2 Ogg pages (max page body 65025).
    big = "X" * 100000
    out = os.path.join(GEN, "tone_bigcomment.oga")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav,
         "-c:a", "flac", "-f", "ogg", "-metadata", f"title={big}", out],
        check=True)
    return out


def main():
    os.makedirs(CASES, exist_ok=True)

    # ---- Base: simple 3-page file ----
    base = open(os.path.join(GEN, "tone.oga"), "rb").read()

    # Case A: corrupt the VORBIS_COMMENT page (page 1) body, stale CRC.
    pages = parse_pages(base)
    flip_body_byte(pages[1], 10)
    write_pages(os.path.join(CASES, "a_meta_crc.oga"), pages)

    # Case A2: corrupt page 1 body but fix the CRC (content corruption only,
    # e.g. bogus vendor length) - both APIs see garbage content but valid page.
    pages = parse_pages(base)
    pages[1].raw[pages[1].body_off + 4] = 0xFF  # vendor length low byte huge
    pages[1].recalc_crc()
    write_pages(os.path.join(CASES, "a2_meta_content_validcrc.oga"), pages)

    # Case B: corrupt a header byte of the metadata page (segment table), stale CRC.
    pages = parse_pages(base)
    flip_header_byte(pages[1], 27)  # first (only) lacing value
    write_pages(os.path.join(CASES, "b_meta_header_crc.oga"), pages)

    # Case C: truncation points on the simple file.
    for name, cut in [
        ("c_trunc_in_bos_header", 20),
        ("c_trunc_in_bos_body", 60),
        ("c_trunc_at_bos_end", 87),                 # exactly through page 0
        ("c_trunc_in_meta_header", 90),
        ("c_trunc_in_meta_body", 100),
        ("c_trunc_at_meta_end", 87 + 27 + 1 + 54),  # through page 1, no audio
        ("c_trunc_audio_firstbyte", 87 + 27 + 1 + 54 + 1),
        ("c_trunc_mid_audio_page", len(base) - 100),
    ]:
        with open(os.path.join(CASES, name + ".oga"), "wb") as f:
            f.write(base[:cut])

    # Case D: EOS/audio page CRC corrupt (closing CRC pattern).
    pages = parse_pages(base)
    flip_body_byte(pages[2], 5000)
    write_pages(os.path.join(CASES, "d_eos_crc.oga"), pages)

    # Case D2: last audio packet's tail corrupted, stale CRC.
    pages = parse_pages(base)
    flip_body_byte(pages[2], len(pages[2].body) - 1)
    write_pages(os.path.join(CASES, "d2_eos_tail_crc.oga"), pages)

    # ---- Cross-page metadata ----
    big_path = make_big_comment()
    big = open(big_path, "rb").read()
    pages = parse_pages(big)
    print("big-comment layout:")
    for p in pages[:4]:
        print(f"  seq={p.sequence} type={p.header_type:#x} segs={p.seg_count} body={len(p.body)}")

    # Case E: CRC-corrupt the SECOND page of the multi-page metadata packet.
    pages = parse_pages(big)
    flip_body_byte(pages[1], 100)
    write_pages(os.path.join(CASES, "e_crosspage_meta_crc_p1.oga"), pages)

    # Case E2: CRC-corrupt the BOS page (shared init phase; index must fit its 51-byte body).
    pages = parse_pages(big)
    flip_body_byte(pages[0], 40)
    write_pages(os.path.join(CASES, "e_bos_crc.oga"), pages)

    # Case E3: CRC-corrupt the last metadata page (the one ending the packet).
    # Find first audio page: first page whose body starts with 0xFF (FLAC frame sync).
    audio_idx = next(i for i, p in enumerate(parse_pages(big))
                     if p.body and p.body[0] == 0xFF)
    pages = parse_pages(big)
    flip_body_byte(pages[audio_idx - 1], 50)
    write_pages(os.path.join(CASES, "e_crosspage_meta_crc_last.oga"), pages)

    # Case F: truncate the big-comment stream at several positions.
    for name, cut in [
        ("f_trunc_meta_page0_end", sum(len(p.raw) for p in parse_pages(big)[:1])),
        ("f_trunc_meta_mid_page1", sum(len(p.raw) for p in parse_pages(big)[:1]) + 50),
        ("f_trunc_meta_lastpage_mid", sum(len(p.raw) for p in parse_pages(big)[:audio_idx - 1]) + 50),
        ("f_trunc_before_audio", sum(len(p.raw) for p in parse_pages(big)[:audio_idx])),
    ]:
        with open(os.path.join(CASES, name + ".oga"), "wb") as f:
            f.write(big[:cut])

    print("cases written to", CASES)


if __name__ == "__main__":
    main()
