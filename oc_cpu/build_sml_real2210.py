#!/usr/bin/env python3
"""Build REAL 2.210 GHz SML image for Redmi A5 / POCO C71 (serenity).

Phát hiện then chốt (đo PMU trên thiết bị):
  - Bảng A75 của máy là grade 2, bin 2 (điện áp 750/750/750/780/820/870).
  - HW table có 8 dòng; bảng tần số có 7 nấc => ánh xạ freq[i] -> row[i+1].
  - Row 6 = 1690 MHz, Row 7 = 1820 MHz. Bản vá cũ đã sai: nó biến row6 thành
    row7 (1820) nên yêu cầu 1690 vẫn chạy 1.82 GHz.
  - Hàng 2.21 GHz factory KHÔNG phải `03 00 04 04 0a 04 05` (đó là 1820).
    Hàng đúng nằm trong bảng grade-4 (đã chứa sẵn 2210):
        03 00 07 07 0a 04 05
    (field2/field3 = 7 => kênh PLL 7, mult 85, cfg 6 = 2.210 GHz).

Cách vá:
  1. Mọi cặp (1820000, V) trong bảng tần số -> (2210000, 1050000).
  2. Chỉ sửa ROW 7 (nấc cao nhất) của 2 bảng A75 grade2/bin2:
       - bảng normal @0x16a18 (row7 = 0x16a49)
       - bảng hot    @0x195f0 (row7 = 0x19621)
     thành 03 00 07 07 0a 04 05. Row 6 giữ nguyên.
  3. KHÔNG đụng vào MPLL channel 4 (đo thực tế: patch channel 4 không đổi xung).
     Kênh 7 (reg 0x94, mult 85, cfg 6) đã là 2.210 GHz từ factory.
"""

import struct
import hashlib
import sys

sys.path.insert(0, '/home/hoang/Downloads/oc_gpu/oc_cpu')
import build_sml_clean_oc as base

STOCK = base.STOCK_INPUT
KNOWN_PAYLOAD_SHA256 = base.KNOWN_PAYLOAD_SHA256
LOAD_BASE = base.LOAD_BASE

ROW_2210 = bytes([0x03, 0x00, 0x07, 0x07, 0x0A, 0x04, 0x05])
ROW_1690_STOCK = bytes([0x03, 0x00, 0x03, 0x03, 0x08, 0x04, 0x05])

# g2 bin2: normal HW table @0x16a18, hot HW table @0x195f0
HW_TABLES = [0x16A18, 0x195F0]
FREQ_NORMAL = 0x17DC8
FREQ_HOT = 0x1A0D8


def apply_patch(payload, groups, off, data):
    """Ghi data tại off, nhưng pack_magic chỉ nhận block 4-byte aligned."""
    aligned = off & ~3
    block = bytearray(payload[aligned:aligned + 16])
    inner = off - aligned
    block[inner:inner + len(data)] = data
    groups[aligned] = bytes(block)


def build(target_khz=2210000, target_volt=1050000, out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_real2210mhz.img'):
    stock = open(STOCK, 'rb').read()
    payload = stock[0x200:0x200 + 0x20240]
    assert hashlib.sha256(payload).hexdigest() == KNOWN_PAYLOAD_SHA256, 'stock payload hash mismatch'

    groups = {}

    # 1. Freq tables: 1820000 -> target
    freq_count = 0
    for i in range(0, len(payload) - 8, 4):
        f, v = struct.unpack_from('<II', payload, i)
        if f == 1820000 and 700000 <= v <= 1200000:
            groups[i] = struct.pack('<2I', target_khz, target_volt)
            freq_count += 1

    # 2. HW tables: row7 -> real 2210 row, row6 untouched
    hw_count = 0
    for tab in HW_TABLES:
        row6 = tab + 6 * 7
        row7 = tab + 7 * 7
        assert payload[row6:row6 + 7] == ROW_1690_STOCK, \
            f'row6 unexpected @0x{row6:x}: {payload[row6:row6+7].hex()}'
        apply_patch(payload, groups, row7, ROW_2210)
        hw_count += 1

    # Không đụng MPLL channel 4 (0x15ab0 CFG, 0x15ac0 MULT, 0x1594c CFG, 0x1595c MULT)

    sorted_offs = sorted(groups.keys())
    for a, b in zip(sorted_offs, sorted_offs[1:]):
        assert a + len(groups[a]) <= b, f'overlap 0x{a:x} / 0x{b:x}'

    print(f'Target: {target_khz // 1000} MHz @ {target_volt // 1000} mV')
    print(f'  Patch groups: {len(groups)}')
    print(f'  Freq tables patched: {freq_count}')
    print(f'  HW top rows patched: {hw_count}')

    out = base.pack_magic(stock, 0x20240, groups, LOAD_BASE, add_len=0x800)
    if len(out) < base.PART_SIZE:
        out += b'\x00' * (base.PART_SIZE - len(out))

    # --- Verify bằng mô phỏng shellcode ---
    ram = bytearray(out[0x210:0x210 + 0x20240])
    assert hashlib.sha256(bytes(ram)).hexdigest() == KNOWN_PAYLOAD_SHA256
    magic_off = 0x210 + 0x20240
    curr = magic_off + 0x70
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
    print(f'  Simulated: {applied} blocks applied')

    ok = True
    def check(name, off, exp):
        nonlocal ok
        act = bytes(ram[off:off + len(exp)])
        status = 'OK' if act == exp else 'FAIL'
        if act != exp:
            ok = False
        print(f'  [{status}] {name} @0x{off:05x}: {act.hex(" ")}')

    for tab, label in [(HW_TABLES[0], 'normal'), (HW_TABLES[1], 'hot')]:
        check(f'{label} row6 (giữ 1690)', tab + 6 * 7, ROW_1690_STOCK)
        check(f'{label} row7 (2.21GHz)', tab + 7 * 7, ROW_2210)
    check('freq normal step6', FREQ_NORMAL + 6 * 8, struct.pack('<2I', target_khz, target_volt))
    check('freq hot step6', FREQ_HOT + 6 * 8, struct.pack('<2I', target_khz, target_volt))
    # MPLL channel 4 giữ stock
    check('MPLL1 ch4 CFG (stock 4)', 0x15AB0, struct.pack('<I', 4))
    check('MPLL1 ch4 MULT (stock 70)', 0x15AC0, struct.pack('<I', 70))
    check('ANLG ch4 CFG (stock 4)', 0x1594C, struct.pack('<I', 4))
    check('ANLG ch4 MULT (stock 70)', 0x1595C, struct.pack('<I', 70))
    # MPLL channel 7 = factory 2.21
    check('MPLL1 ch7 MULT (factory 85)', 0x15B50, struct.pack('<I', 85))
    check('MPLL1 ch7 CFG (factory 6)', 0x15B40, struct.pack('<I', 6))

    if not ok:
        raise SystemExit('VERIFICATION FAILED')

    with open(out_path, 'wb') as f:
        f.write(out)
    print(f'SUCCESS: {out_path}')
    print(f'  SHA256: {hashlib.sha256(out).hexdigest()}')
    print(f'  Size: {len(out)}')


if __name__ == '__main__':
    build()
