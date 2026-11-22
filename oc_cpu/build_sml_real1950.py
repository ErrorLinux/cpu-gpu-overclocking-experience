#!/usr/bin/env python3
"""Build REAL 1.950 GHz SML image (thử xem index 6 có chạy 1.95 không).

Dùng hàng 1.95 GHz factory từ bảng grade-4:
  03 00 06 06 0a 04 05
và bảng tần số top = 1950000 @ 990000 uV.
Chỉ sửa row7 của 2 bảng A75 g2/bin2 (normal 0x16a18, hot 0x195f0).
"""

import struct, hashlib, sys
sys.path.insert(0, '/home/hoang/Downloads/oc_gpu/oc_cpu')
import build_sml_clean_oc as base

STOCK = base.STOCK_INPUT
KNOWN = base.KNOWN_PAYLOAD_SHA256
LOAD_BASE = base.LOAD_BASE

ROW_1950 = bytes([0x03, 0x00, 0x06, 0x06, 0x0A, 0x04, 0x05])
ROW_1690 = bytes([0x03, 0x00, 0x03, 0x03, 0x08, 0x04, 0x05])
HW_TABLES = [0x16A18, 0x195F0]
FREQ_NORMAL = 0x17DC8
FREQ_HOT = 0x1A0D8
TARGET_KHZ = 1950000
TARGET_VOLT = 990000

def apply_patch(payload, groups, off, data):
    aligned = off & ~3
    block = bytearray(payload[aligned:aligned + 16])
    inner = off - aligned
    block[inner:inner + len(data)] = data
    groups[aligned] = bytes(block)

def build():
    stock = open(STOCK, 'rb').read()
    payload = stock[0x200:0x200 + 0x20240]
    assert hashlib.sha256(payload).hexdigest() == KNOWN
    groups = {}
    for i in range(0, len(payload) - 8, 4):
        f, v = struct.unpack_from('<II', payload, i)
        if f == 1820000 and 700000 <= v <= 1200000:
            groups[i] = struct.pack('<2I', TARGET_KHZ, TARGET_VOLT)
    for tab in HW_TABLES:
        row6 = tab + 6 * 7
        row7 = tab + 7 * 7
        assert payload[row6:row6 + 7] == ROW_1690, hex(tab)
        apply_patch(payload, groups, row7, ROW_1950)
    sorted_offs = sorted(groups.keys())
    for a, b in zip(sorted_offs, sorted_offs[1:]):
        assert a + len(groups[a]) <= b
    out = base.pack_magic(stock, 0x20240, groups, LOAD_BASE, add_len=0x800)
    if len(out) < base.PART_SIZE:
        out += b'\x00' * (base.PART_SIZE - len(out))
    # verify
    ram = bytearray(out[0x210:0x210 + 0x20240])
    assert hashlib.sha256(bytes(ram)).hexdigest() == KNOWN
    curr = 0x210 + 0x20240 + 0x70
    applied = 0
    while True:
        addr, cnt = struct.unpack_from('<II', out, curr)
        curr += 8
        if addr == 0 or cnt == 0:
            break
        words = struct.unpack_from(f'<{cnt}I', out, curr)
        curr += 4 * cnt
        o = addr - LOAD_BASE
        for i, w in enumerate(words):
            struct.pack_into('<I', ram, o + i * 4, w)
        applied += 1
    print(f'simulated {applied} blocks')
    for tab, lab in [(HW_TABLES[0], 'normal'), (HW_TABLES[1], 'hot')]:
        assert bytes(ram[tab + 6 * 7:tab + 6 * 7 + 7]) == ROW_1690
        assert bytes(ram[tab + 7 * 7:tab + 7 * 7 + 7]) == ROW_1950
        print(f'  {lab}: row6={bytes(ram[tab+6*7:tab+6*7+7]).hex(" ")} row7={bytes(ram[tab+7*7:tab+7*7+7]).hex(" ")} OK')
    assert bytes(ram[FREQ_NORMAL + 6 * 8:FREQ_NORMAL + 6 * 8 + 8]) == struct.pack('<2I', TARGET_KHZ, TARGET_VOLT)
    print(f'  freq step6 = {struct.unpack_from("<2I", ram, FREQ_NORMAL + 6*8)} OK')
    path = '/home/hoang/Downloads/oc_gpu/oc_cpu/sml_real1950mhz.img'
    with open(path, 'wb') as f:
        f.write(out)
    print(f'SUCCESS {path} sha256={hashlib.sha256(out).hexdigest()}')

if __name__ == '__main__':
    build()
EOF
cd /home/hoang/Downloads/oc_gpu/oc_cpu && python3 build_sml_real1950.py