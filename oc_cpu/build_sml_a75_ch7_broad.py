#!/usr/bin/env python3
"""Broad A75 MUX probe: every hardware row within 0x300 of an A75 2210-kHz
frequency table is rewritten to Channel 7 (03 00 07 07 ...). Also bumps the
index-6 OPP to 2210 MHz @ 1050 mV. Diagnostic build: if PMU hits 2.21 GHz the
exact live row family is identified and can be narrowed in a follow-up."""
import re
import struct
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sml_dual_definitive_oc import pack_magic, simulate_and_verify  # noqa: E402

STOCK = '/home/hoang/Downloads/serenity_global_images_A15.0.33.0.VGWMIXM_15.0/images/sml-sign.bin'
OUT = '/home/hoang/Downloads/oc_gpu/oc_cpu/sml_a75_ch7_broad.img'
PAYLOAD_SHA = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'
BASE = 0xB0000000


def main():
    stock = Path(STOCK).read_bytes()
    payload = bytearray(stock[0x200:0x200 + 0x20240])
    assert hashlib.sha256(payload).hexdigest() == PAYLOAD_SHA

    # offsets below are in the 0x210-based analysis frame; payload frame = +0x10
    a75 = [m.start() for m in re.finditer(struct.pack('<I', 2210000), payload)]
    rows = []
    for m in re.finditer(rb'\x03\x00..[\x08\x09\x0a]\x04\x05', payload, re.S):
        o = m.start()
        if min(abs(o - x) for x in a75) <= 0x300:
            rows.append(o)
    print('rows to patch:', len(rows), [hex(x) for x in rows])

    opp = struct.pack('<II', 1820000, 930000)
    opp_hits = [m.start() for m in re.finditer(re.escape(opp), payload)]
    print('opp hits:', [hex(x) for x in opp_hits])

    ram = bytearray(payload)
    for o in rows:
        ram[o + 2] = 0x07
        ram[o + 3] = 0x07
    for q in opp_hits:
        ram[q:q + 8] = struct.pack('<II', 2210000, 1050000)

    touched = set()
    for o in rows:
        for k in (2, 3):
            touched.add((o + k) & ~3)
    for q in opp_hits:
        for k in range(8):
            touched.add((q + k) & ~3)
    groups = {}
    for a in sorted(touched):
        groups[a] = bytes(ram[a:a + 4])
    print('groups:', len(groups))

    checks = []
    for o in rows:
        checks.append((f'row@{o:#x}', o, b'\x03\x00\x07\x07' + payload[o+4:o+7]))
    for q in opp_hits:
        checks.append((f'opp@{q:#x}', q, struct.pack('<II', 2210000, 1050000)))
    out = pack_magic(stock, 0x20240, groups, BASE)
    Path(OUT).write_bytes(out)
    print('wrote', OUT, len(out), 'bytes')
    print('sha256', hashlib.sha256(out).hexdigest())
    ok = simulate_and_verify(out, BASE, checks[:40])
    print('verify ok:', ok)


if __name__ == '__main__':
    main()
