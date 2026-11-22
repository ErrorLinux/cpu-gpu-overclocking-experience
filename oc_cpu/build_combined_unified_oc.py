#!/usr/bin/env python3
"""Build Combined Unified Real Hardware Overclock SML Images for Unisoc T7250.

Combines:
1. All 37 Frequency Tables: Step 6 -> target_freq_khz @ target_volt_uv
2. All 8 Process Corners: Rows 6 & 7 -> Factory Row (03 00 xx xx 0a 04 05)
3. Table A (0x645a0000 - anlg_phy_gc): Reg 0xbc, 0xc0, 0xc4 -> target_mult & target_cfg
4. Table B (0x64580000 - anlg_phy_g3 / mpll1): Reg 0x88, 0x8c, 0x90, 0x94 -> target_mult & target_cfg
"""

import struct
import hashlib
import os
import re

STOCK_INPUT = '/home/hoang/Downloads/serenity_global_images_A15.0.33.0.VGWMIXM_15.0/images/sml-sign.bin'
KNOWN_PAYLOAD_SHA256 = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'
LOAD_BASE = 0xB0000000
PART_SIZE = 0x100000  # 1 MB

_SHELLCODE_TEMPLATE = [
    0x90000009, 0x9100412a, 0xd2a0004b, 0xf280000b, 0xd280000c, 0xeb0b018d,
    0x540000e2, 0xf86c794d, 0xf82c792d, 0xd508711f, 0xd5033fdf, 0x9100058c,
    0x17fffff9, 0x90000009, 0x91020129, 0xb840452a, 0xb400016a, 0xb840452b,
    0xd280000c, 0xeb0b018d, 0x54ffff62, 0xb840452d, 0xb800454d, 0xd508711f,
    0xd5033fdf, 0x9100058c, 0x17fffff9, 0x17fbffe1,
]

def build_shellcode(size):
    n = size // 8
    w = list(_SHELLCODE_TEMPLATE)
    imm = 0x200 - (0x210 + size)
    w[0] = (0x10000000 | ((imm & 3) << 29)
            | (((imm >> 2) & 0x7FFFF) << 5) | 9)
    w[2] = 0xD2A00000 | (((n >> 16) & 0xFFFF) << 5) | 11
    w[3] = 0xF2800000 | ((n & 0xFFFF) << 5) | 11
    w[13] = (0x10000000 | ((0x3C & 3) << 29)
             | (((0x3C >> 2) & 0x7FFFF) << 5) | 9)
    w[14] = 0xD503201F
    off = -(size + 0x7C)
    w[27] = 0x14000000 | ((off >> 2) & 0x3FFFFFF)
    return struct.pack('<28I', *w)

def pack_magic(data, size, groups, load_base, add_len=0x800):
    foot_off = 0x200 + size
    footer = bytearray(data[foot_off:foot_off + 0x60])
    if footer[0:7] != b'SIMGHDR' or struct.unpack_from('<Q', footer, 0x18)[0] != 0x200:
        raise SystemExit('SIMGHDR footer not found / already patched')
    
    patch_data = b''
    for off in sorted(groups.keys()):
        raw_b = groups[off]
        words = struct.unpack(f'<{len(raw_b)//4}I', raw_b)
        patch_data += struct.pack('<II', load_base + off, len(words))
        patch_data += struct.pack('<%dI' % len(words), *words)
    patch_data += struct.pack('<I', 0)
    
    shell = build_shellcode(size)
    if len(shell) + len(patch_data) > add_len - 0x10:
        raise ValueError('add_len %#x too small (needs %d)' % (add_len, len(shell) + len(patch_data) + 0x10))
    
    out = bytearray()
    hdr = bytearray(data[0:0x200])
    struct.pack_into('<I', hdr, 0x30, size + add_len)
    out += hdr
    jump = 0x14000000 | (((size + 0x10) // 4) & 0x3FFFFFF)
    out += struct.pack('<I', jump) + b'\x00' * 0x0C
    out += data[0x200:0x200 + size]
    magic = bytearray(add_len - 0x10)
    magic[0:len(shell)] = shell
    magic[len(shell):len(shell) + len(patch_data)] = patch_data
    out += magic
    struct.pack_into('<Q', footer, 0x18, 0x210)
    for so, oo in [(0x20, 0x28), (0x30, 0x38), (0x40, 0x48), (0x50, 0x58)]:
        if struct.unpack_from('<Q', footer, so)[0]:
            struct.pack_into('<Q', footer, oo,
                             struct.unpack_from('<Q', footer, oo)[0] + add_len)
    out += footer
    out += data[foot_off + 0x60:]
    return bytes(out)

def simulate_and_verify(image_bytes, load_base, expected_checks):
    raw = bytearray(image_bytes)
    size = struct.unpack_from('<I', raw, 0x30)[0]
    payload = raw[0x210 : 0x210 + size]
    ram = bytearray(payload)
    
    magic_off = 0x210 + 0x20240
    patch_data_off = magic_off + 0x70
    
    curr = patch_data_off
    count_applied = 0
    while True:
        target_addr, count = struct.unpack_from('<II', raw, curr)
        curr += 8
        if target_addr == 0 or count == 0:
            break
        words = struct.unpack_from(f'<{count}I', raw, curr)
        curr += 4 * count
        ram_off = target_addr - load_base
        for i, w in enumerate(words):
            struct.pack_into('<I', ram, ram_off + i*4, w)
        count_applied += 1
            
    print(f"Simulated execution: {count_applied} patch blocks applied successfully.")
    for name, offset, expected in expected_checks:
        actual = bytes(ram[offset:offset+len(expected)])
        if actual == expected:
            print(f"  [OK] {name} at 0x{offset:x}: {actual.hex()}")
        else:
            print(f"  [FAIL] {name} at 0x{offset:x}: actual {actual.hex()} != expected {expected.hex()}")
            return False
    return True

def build_profile(target_freq_khz, target_volt_uv, factory_row_bytes, target_mult, target_cfg, out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock = f.read()

    payload = stock[0x200 : 0x200 + 0x20240]
    assert hashlib.sha256(payload).hexdigest() == KNOWN_PAYLOAD_SHA256
    assert len(factory_row_bytes) == 7

    groups = {}

    # 1. TABLE A (0x645a0000 - anlg_phy_gc_regs)
    # Reg 0xbc (stock 1820 MHz, mult=70, cfg=4)
    groups[0x1594c] = struct.pack('<I', target_cfg)
    groups[0x1595c] = struct.pack('<I', target_mult)
    # Reg 0xc0 (stock 1950 MHz, mult=75, cfg=4)
    groups[0x1597c] = struct.pack('<I', target_cfg)
    groups[0x1598c] = struct.pack('<I', target_mult)
    # Reg 0xc4 (stock 2002 MHz, mult=77, cfg=5)
    groups[0x159ac] = struct.pack('<I', target_cfg)
    groups[0x159bc] = struct.pack('<I', target_mult)

    # 2. TABLE B (0x64580000 - anlg_phy_g3_regs / mpll1)
    # Reg 0x88 (stock 1820 MHz, mult=70, cfg=4)
    groups[0x15ab0] = struct.pack('<I', target_cfg)
    groups[0x15ac0] = struct.pack('<I', target_mult)
    # Reg 0x8c (stock 1898 MHz, mult=73, cfg=4)
    groups[0x15ae0] = struct.pack('<I', target_cfg)
    groups[0x15af0] = struct.pack('<I', target_mult)
    # Reg 0x90 (stock 1950 MHz, mult=75, cfg=4)
    groups[0x15b10] = struct.pack('<I', target_cfg)
    groups[0x15b20] = struct.pack('<I', target_mult)
    # Reg 0x94 (stock 2210 MHz, mult=85, cfg=6)
    groups[0x15b40] = struct.pack('<I', target_cfg)
    groups[0x15b50] = struct.pack('<I', target_mult)

    # 3. ALL 37 Frequency Table Entries of 1820000 kHz
    freq_count = 0
    for i in range(0, len(payload) - 8, 4):
        f, v = struct.unpack('<II', payload[i:i+8])
        if f == 1820000 and 700000 <= v <= 1200000:
            groups[i] = struct.pack('<2I', target_freq_khz, target_volt_uv)
            freq_count += 1

    # 4. ALL 8 Chip Corner Hardware Tables (Rows 6 & 7)
    matches_08 = list(re.finditer(b'\x03\x00\x03\x03\x08\x04\x05', payload))
    matches_0a = list(re.finditer(b'\x03\x00\x04\x04\x0a\x04\x05', payload))
    assert len(matches_08) == 8 and len(matches_0a) == 8, f"Expected 8 corners, found {len(matches_08)} and {len(matches_0a)}"

    hw_corners_count = 0
    for m8, ma in zip(matches_08, matches_0a):
        s8 = m8.start()
        sa = ma.start()
        assert sa == s8 + 7, f"Misaligned corner: 0x{s8:x} vs 0x{sa:x}"
        aligned = s8 & ~3
        raw_16 = bytearray(payload[aligned : aligned + 16])
        raw_16[2:9] = factory_row_bytes
        raw_16[9:16] = factory_row_bytes
        groups[aligned] = bytes(raw_16)
        hw_corners_count += 1

    print(f"Profile {target_freq_khz//1000} MHz: Patched {freq_count} Freq targets, {hw_corners_count} HW Corners, 14 PLL Mult/Cfg registers.")

    out_bytes = pack_magic(stock, 0x20240, groups, LOAD_BASE, add_len=0x800)

    # Pad to partition size (1 MB)
    if len(out_bytes) > PART_SIZE:
        out_bytes = out_bytes[:PART_SIZE]
    elif len(out_bytes) < PART_SIZE:
        out_bytes = out_bytes + b'\x00' * (PART_SIZE - len(out_bytes))

    # Verify simulation
    expected_checks = [
        ("Table A Reg 0xbc Cfg",  0x1594c, struct.pack('<I', target_cfg)),
        ("Table A Reg 0xbc Mult", 0x1595c, struct.pack('<I', target_mult)),
        ("Table B Reg 0x88 Cfg",  0x15ab0, struct.pack('<I', target_cfg)),
        ("Table B Reg 0x88 Mult", 0x15ac0, struct.pack('<I', target_mult)),
        ("Table B Reg 0x90 Mult", 0x15b20, struct.pack('<I', target_mult)),
        ("Table B Reg 0x94 Mult", 0x15b50, struct.pack('<I', target_mult)),
        ("Active HW Table Row 6", 0x19e52, factory_row_bytes),
        ("Active HW Table Row 7", 0x19e59, factory_row_bytes),
        ("Active Freq Table Step 6", 0x19ea0, struct.pack('<2I', target_freq_khz, target_volt_uv)),
    ]

    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected_checks)
    if not ok:
        raise RuntimeError("Verification failed!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"Generated {out_path}:")
    print(f"  Target: Cortex-A75 {target_freq_khz // 1000} MHz @ {target_volt_uv // 1000} mV")
    print(f"  Factory Row Bytes: {factory_row_bytes.hex()}")
    print(f"  Multiplier: {target_mult} (=> {target_mult * 26} MHz), CFG: {target_cfg}")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")

def main():
    print("=== Building Unisoc T7250 Combined Unified Overclock SML Images ===\n")
    
    # 1. 2.21 GHz Combined Profile (mult=85, cfg=6 @ 1050 mV, Row 9 MUX 06 06)
    build_profile(
        target_freq_khz=2210000,
        target_volt_uv=1050000,
        factory_row_bytes=bytes([0x03, 0x00, 0x06, 0x06, 0x0a, 0x04, 0x05]),
        target_mult=85,
        target_cfg=6,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_combined_2210mhz.img'
    )

    # 2. 1.95 GHz Combined Profile (mult=75, cfg=4 @ 980 mV, Row 8 MUX 05 05)
    build_profile(
        target_freq_khz=1950000,
        target_volt_uv=980000,
        factory_row_bytes=bytes([0x03, 0x00, 0x05, 0x05, 0x0a, 0x04, 0x05]),
        target_mult=75,
        target_cfg=4,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_combined_1950mhz.img'
    )

if __name__ == '__main__':
    main()
