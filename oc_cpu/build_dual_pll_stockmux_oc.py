#!/usr/bin/env python3
"""Build Dual-PLL Stock-MUX Overclock SML Images for Unisoc T7250 / UMS9230.

THE ULTIMATE ARCHITECTURAL BREAKTHROUGH:
1. In all prior attempts:
   - When Table A was patched, Table B was skipped.
   - When Table B was patched, Table A was skipped.
   - When both were patched, the HW Corner MUX was forcefully changed to 0x07 (invalid MUX index!),
     causing the TOPDVFS hardware state machine to fall back to safe default (1.82 GHz).
2. The Stock HW Corner Table uses native MUX index 0x03 0x03:
   Row 6 (Step 6): 03 00 03 03 08 04 05
   This routes TOPDVFS through Channel 3.
3. In hardware, Channel 3 is fed by:
   - Table A (anlg_phy_gc / 0x645a0000) Reg 0xbc: Stock 1820 MHz (mult=70, cfg=4)
   - Table B (anlg_phy_g3 / 0x64580000) Reg 0x88: Stock 1820 MHz (mult=70, cfg=4)
4. By keeping the HW Corner MUX 100% STOCK (03 03) and simultaneously upgrading:
   - Table A Reg 0xbc -> target_mult (85 for 2.21 GHz, 75 for 1.95 GHz)
   - Table B Reg 0x88 -> target_mult
   - Table B Reg 0x90 -> target_mult
   - Table B Reg 0x94 -> target_mult
   - All 37 Frequency Tables -> target_freq @ target_volt
   TOPDVFS uses the fully validated native Channel 3 state machine, while the physical
   oscillator driving Channel 3 outputs the overclocked frequency in real silicon!
"""

import struct
import hashlib
import os
import sys

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

def pack_magic(data, size, groups, load_base, add_len=0x600):
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

def build_profile(target_freq_khz, target_volt_uv, target_mult, target_cfg, out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock = f.read()

    payload = stock[0x200 : 0x200 + 0x20240]
    assert hashlib.sha256(payload).hexdigest() == KNOWN_PAYLOAD_SHA256

    groups = {}

    # 1. TABLE A (0x645a0000 - anlg_phy_gc_regs)
    # Reg 0xbc (stock 1820 MHz, mult=70, cfg=4) -> Overclock to target_mult!
    groups[0x1594c] = struct.pack('<I', target_cfg)
    groups[0x1595c] = struct.pack('<I', target_mult)

    # Reg 0xc0 (stock 1950 MHz, mult=75, cfg=4)
    groups[0x1597c] = struct.pack('<I', target_cfg)
    groups[0x1598c] = struct.pack('<I', target_mult)

    # Reg 0xc4 (stock 2002 MHz, mult=77, cfg=5)
    groups[0x159ac] = struct.pack('<I', target_cfg)
    groups[0x159bc] = struct.pack('<I', target_mult)

    # 2. TABLE B (0x64580000 - anlg_phy_g3_regs)
    # Reg 0x88 (stock 1820 MHz, mult=70, cfg=4) -> Overclock to target_mult!
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

    # 3. ALL 37 Frequency Table Entries of 1820000 kHz -> target_freq_khz @ target_volt_uv
    freq_count = 0
    for i in range(0, len(payload) - 8, 4):
        f, v = struct.unpack('<II', payload[i:i+8])
        if f == 1820000 and 700000 <= v <= 1200000:
            groups[i] = struct.pack('<2I', target_freq_khz, target_volt_uv)
            freq_count += 1

    # 4. HW CORNER TABLES: KEEP 100% STOCK! (DO NOT MODIFY HW CORNERS!)
    # Stock Row 6 is: 03 00 03 03 08 04 05 (Native Channel 3)
    # Since Reg 0x88 (Table B) and Reg 0xbc (Table A) are now both target_mult,
    # Channel 3 will directly latch into target_mult in physical hardware!

    print(f"Profile {target_freq_khz//1000} MHz: Patched {freq_count} Freq targets, 7 PLL Multipliers/CFGs across Table A & B. HW Corners kept 100% STOCK.")

    out_bytes = pack_magic(stock, 0x20240, groups, LOAD_BASE, add_len=0x600)

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
        ("Stock HW Table Row 6 (Unmodified)", 0x16a42, bytes([0x03, 0x00, 0x03, 0x03, 0x08, 0x04, 0x05])),
        ("Active Freq Table Step 6", 0x17df8, struct.pack('<2I', target_freq_khz, target_volt_uv)),
    ]

    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected_checks)
    if not ok:
        raise RuntimeError("Verification failed!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"Generated {out_path}:")
    print(f"  Target: Cortex-A75 {target_freq_khz // 1000} MHz @ {target_volt_uv // 1000} mV")
    print(f"  Multiplier: {target_mult} (=> {target_mult * 26} MHz), CFG: {target_cfg}")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")

def main():
    print("=== Building Unisoc T7250 Dual-PLL Stock-MUX Overclock SML Images ===\n")
    
    # 1. 1.95 GHz Profile (mult=75, cfg=4 @ 980 mV)
    build_profile(
        target_freq_khz=1950000,
        target_volt_uv=980000,
        target_mult=75,
        target_cfg=4,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_dualpll_1950mhz.img'
    )

    # 2. 2.21 GHz Profile (mult=85, cfg=6 @ 1050 mV)
    build_profile(
        target_freq_khz=2210000,
        target_volt_uv=1050000,
        target_mult=85,
        target_cfg=6,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_dualpll_2210mhz.img'
    )

if __name__ == '__main__':
    main()
