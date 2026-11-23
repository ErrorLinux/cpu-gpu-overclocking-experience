#!/usr/bin/env python3
import struct
"""SML patch: route A75 index-6 row from Channel 4 (1820 MHz) to Channel 7 (2210 MHz).

Finding (2026-11-23):
  - SMC 0x82000605(cluster=1, index) -> SML 0x58FC -> 0x4B7C is the real HW writer.
  - index 0 -> 0.768 GHz, index 6 -> 1.820 GHz, index 7/8/9 -> 1.690 GHz on stock.
    Therefore the 7-byte hardware rows are indexed directly by DVFS index:
      index 6 row = 03 00 04 04 0a 04 05  (Ch4 = 1820 MHz)
      index 7/8/9 rows are missing on several corner tables, so they fall back
      to Channel 3 (1690 MHz).  The old "definitive" builder patched at t+7*7,
      which is 0x10 bytes past the real row -- it never touched the live table.
  - This patch changes ONLY the index-6 row (which exists in all 8 corner
    tables) to Channel 7.  Runtime: call oc_index=6 -> true 2.21 GHz.

Signature: payload bytes are untouched; a shellcode in the padding applies the
word patches to RAM at boot, so the RSA-2048 signature stays valid.
"""
import re
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sml_dual_definitive_oc import pack_magic, simulate_and_verify  # noqa: E402

STOCK = '/home/hoang/Downloads/serenity_global_images_A15.0.33.0.VGWMIXM_15.0/images/sml-sign.bin'
OUT = '/home/hoang/Downloads/oc_gpu/oc_cpu/sml_a75_ch7_row6_v2.img'
PAYLOAD_SHA = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'
BASE = 0xB0000000
ROW = bytes.fromhex('030004040a0405')
NEW = bytes.fromhex('030007070a0405')


def main():
    stock = Path(STOCK).read_bytes()
    payload = stock[0x200:0x200 + 0x20240]
    assert hashlib.sha256(payload).hexdigest() == PAYLOAD_SHA, 'stock payload mismatch'

    ram = bytearray(payload)
    hits = [m.start() for m in re.finditer(re.escape(ROW), payload)]
    print('index-6 rows found:', [hex(h) for h in hits])
    if len(hits) != 8:
        raise SystemExit(f'expected 8 rows, got {len(hits)}')

    # A75 index-6 OPP: 1820 MHz @ 930 mV -> 2210 MHz @ 1050 mV.
    # Without the voltage bump the hardware can fall back from Ch7.
    opp = struct.pack('<II', 1820000, 930000)
    opp_hits = [m.start() for m in re.finditer(re.escape(opp), payload)]
    print('index-6 OPP found:', [hex(h) for h in opp_hits])
    if len(opp_hits) != 1:
        raise SystemExit(f'expected 1 OPP pair, got {len(opp_hits)}')
    for q in opp_hits:
        ram[q:q + 8] = struct.pack('<II', 2210000, 1050000)

    # collect every 4-byte aligned word that contains a byte we modify
    touched = set()
    for p in hits:
        ram[p:p + 7] = NEW
        for k in range(2, 4):
            touched.add((p + k) & ~3)
    for q in opp_hits:
        for k in range(8):
            touched.add((q + k) & ~3)
    words = {a: struct_word(ram, a) for a in sorted(touched)}

    groups = []
    for a in sorted(words):
        # merge contiguous words into groups (pack_magic takes byte blobs)
        if groups and a == groups[-1][0] + len(groups[-1][1]):
            groups[-1] = (groups[-1][0], groups[-1][1] + words[a])
        else:
            groups.append((a, words[a]))
    groups = {a: b for a, b in groups}
    for a, b in groups.items():
        print(f'patch @{a:#x}: {b.hex(" ")}')

    # mark every touched word in a copy and verify simulation
    modified = bytearray(len(payload))
    for a in touched:
        modified[a:a + 4] = b'\1\1\1\1'
    check = [(f'row6@{h:#x}', h, NEW) for h in hits]
    check += [(f'opp6@{q:#x}', q, struct.pack('<II', 2210000, 1050000)) for q in opp_hits]
    out = pack_magic(stock, 0x20240, groups, BASE)
    Path(OUT).write_bytes(out)
    print('wrote', OUT, len(out), 'bytes')
    print('sha256', hashlib.sha256(out).hexdigest())
    if not simulate_and_verify(out, BASE, check):
        raise SystemExit('verification failed')


def struct_word(buf, off):
    return bytes(buf[off:off + 4])


if __name__ == '__main__':
    main()
