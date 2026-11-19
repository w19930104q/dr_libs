"""Minimal Ogg bitstream parser/editor for building dr_flac corruption cases.

Run with: python3 -I oggtool.py ...
"""
import struct
import sys


def ogg_crc32(data):
    """Ogg page checksum: non-reflected CRC-32, poly 0x04C11DB7, init 0, no final XOR."""
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _OGG_CRC_TABLE[((crc >> 24) & 0xFF) ^ b]
    return crc


def _build_table():
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (r & 0x80000000) else (r << 1) & 0xFFFFFFFF
        table.append(r)
    return table


_OGG_CRC_TABLE = _build_table()


class Page:
    def __init__(self, raw, header_len, seg_table, body_off):
        self.raw = bytearray(raw)
        self.header_len = header_len
        self.seg_table = seg_table          # list of lacing values
        self.body_off = body_off            # offset of body in raw
        self.body = bytearray(raw[body_off:])
        self.version = raw[4]
        self.header_type = raw[5]
        self.granule = struct.unpack_from("<q", raw, 6)[0]
        self.serial = struct.unpack_from("<I", raw, 14)[0]
        self.sequence = struct.unpack_from("<I", raw, 18)[0]
        self.checksum = struct.unpack_from("<I", raw, 22)[0]
        self.seg_count = raw[26]

    def recalc_crc(self):
        struct.pack_into("<I", self.raw, 22, 0)
        crc = ogg_crc32(bytes(self.raw))
        struct.pack_into("<I", self.raw, 22, crc)
        self.checksum = crc
        return crc

    def packets(self):
        """Yield (start, end_exclusive) packet byte ranges within body, honoring lacing."""
        start = 0
        i = 0
        n = len(self.seg_table)
        while i < n:
            total = 0
            j = i
            while j < n and self.seg_table[j] == 255:
                total += 255
                j += 1
            if j < n:
                total += self.seg_table[j]   # terminating segment (<255)
                j += 1
            yield (start, start + total, j == n and self.seg_table[j - 1] < 255)
            start += total
            i = j


def parse_pages(data):
    pages = []
    off = 0
    while off < len(data):
        if data[off:off + 4] != b"OggS":
            raise ValueError(f"missing capture pattern at {off}")
        seg_count = data[off + 26]
        header_len = 27 + seg_count
        seg_table = list(data[off + 27:off + header_len])
        body_size = sum(seg_table)
        raw = data[off:off + header_len + body_size]
        pages.append(Page(raw, header_len, seg_table, header_len))
        off += header_len + body_size
    return pages


def dump(path):
    data = open(path, "rb").read()
    pages = parse_pages(data)
    print(f"{path}: {len(pages)} pages, {len(data)} bytes")
    for p in pages:
        flags = []
        if p.header_type & 0x01: flags.append("CONT")
        if p.header_type & 0x02: flags.append("BOS")
        if p.header_type & 0x04: flags.append("EOS")
        pkts = list(p.packets())
        first = bytes(p.body[:8])
        print(f"  seq={p.sequence:3d} flags={','.join(flags) or '-':11s} "
              f"gran={p.granule:8d} segs={p.seg_count:3d} body={len(p.body):6d} "
              f"pkts={len(pkts)} head={first.hex()} crc={p.checksum:08x}")
        for k, (s, e, complete) in enumerate(pkts):
            print(f"      pkt[{k}] {s}..{e} ({e-s} bytes){'' if complete else ' (continues)'}")


if __name__ == "__main__":
    dump(sys.argv[1])
