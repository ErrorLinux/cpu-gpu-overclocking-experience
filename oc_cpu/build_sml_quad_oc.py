#!/usr/bin/env python3
"""Build Quad-Layer Redundant Real Hardware Overclock SML Images for Unisoc T7250 / UMS9230E.

This script implements the complete, definitive 4-layer overclock architecture:
  Layer 1 (.rela.dyn): Relocates Serenity chip profile IDs (0x0212feee / 0x02120041)
                       directly to Unisoc official factory OPP descriptors.
  Layer 2 (Master LUT): Directly overrides master lookup table descriptors in RAM.
  Layer 3 (Descriptors): Patches Serenity active descriptors (0x19e08 / 0x19fe0) in-place.
  Layer 4 (Hardware Tables & Freq Tables): Patches Serenity active HW tables (0x16a18 / 0x195f0)
                       and Freq tables (0x17dc8 / 0x1a0d8) in-place to physical Channel 7 (2.21 GHz)
                       or Channel 6 (1.95 GHz).
  + Table A & Table B PLL register multipliers and configs.
  + All 37 frequency table entries and all 8 corner hardware tables.
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
        raise ValueError(f'add_len 0x{add_len:x} too small (needs {len(shell) + len(patch_data) + 0x10})')
    
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
    all_ok = True
    for name, offset, expected in expected_checks:
        actual = bytes(ram[offset:offset+len(expected)])
        if actual == expected:
            print(f"  [OK] {name} at 0x{offset:x}: {actual.hex()}")
        else:
            print(f"  [FAIL] {name} at 0x{offset:x}: actual {actual.hex()} != expected {expected.hex()}")
            all_ok = False
    return all_ok

def build_quad_profile(target_freq_khz, target_volt_uv, factory_row_bytes,
                       target_mult, target_cfg,
                       target_desc_norm_off, target_desc_high_off,
                       target_ft_norm_off, target_ft_norm_steps,
                       target_hw_norm_off, target_hw_norm_rows,
                       target_ft_high_off, target_ft_high_steps,
                       target_hw_high_off, target_hw_high_rows,
                       out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock = bytearray(f.read())

    payload = stock[0x200 : 0x200 + 0x20240]
    assert hashlib.sha256(payload).hexdigest() == KNOWN_PAYLOAD_SHA256
    assert len(factory_row_bytes) == 7

    # Modifiable copy of payload to be packed
    mod_payload = bytearray(payload)
    groups = {}

    # =========================================================================
    # LAYER 1: .rela.dyn (Relocation Table) direct patch in payload
    # =========================================================================
    # 0x1e920: Cluster 1 Normal Temp (0x0212feee) -> target_desc_norm_off
    struct.pack_into('<q', mod_payload, 0x1e920 + 16, target_desc_norm_off)
    # 0x1e950: Cluster 1 High Temp (0x02120041) -> target_desc_high_off
    struct.pack_into('<q', mod_payload, 0x1e950 + 16, target_desc_high_off)
    # 0x1e908: Cluster 0 Normal Temp (0x0202feee) -> 0x18200 (Version 4 Bin 2 Cortex-A55 1.82 GHz)
    struct.pack_into('<q', mod_payload, 0x1e908 + 16, 0x18200)
    # 0x1e938: Cluster 0 High Temp (0x02020041) -> 0x188d0 (Version 4 Bin 2 Cortex-A55 1.82 GHz High Temp)
    struct.pack_into('<q', mod_payload, 0x1e938 + 16, 0x188d0)
    # 0x1fe68: Serenity stock desc 0x19e08 Freq Table pointer
    struct.pack_into('<q', mod_payload, 0x1fe68 + 16, target_ft_norm_off)
    # 0x1fe80: Serenity stock desc 0x19e08 HW Table pointer
    struct.pack_into('<q', mod_payload, 0x1fe80 + 16, target_hw_norm_off)
    # 0x1ff40: Serenity stock high desc 0x19fe0 Freq Table pointer
    struct.pack_into('<q', mod_payload, 0x1ff40 + 16, target_ft_high_off)
    # 0x1ff58: Serenity stock high desc 0x19fe0 HW Table pointer
    struct.pack_into('<q', mod_payload, 0x1ff58 + 16, target_hw_high_off)

    # =========================================================================
    # LAYER 2: Master Lookup Table (0x16ea8) pointers in RAM & payload
    # =========================================================================
    # Cluster 0 Normal: 0x17050 -> 0x18200
    groups[0x17050] = struct.pack('<Q', LOAD_BASE + 0x18200)
    # Cluster 1 Normal: 0x17060 -> target_desc_norm_off
    groups[0x17060] = struct.pack('<Q', LOAD_BASE + target_desc_norm_off)
    # Cluster 0 High: 0x17070 -> 0x188d0
    groups[0x17070] = struct.pack('<Q', LOAD_BASE + 0x188d0)
    # Cluster 1 High: 0x17080 -> target_desc_high_off
    groups[0x17080] = struct.pack('<Q', LOAD_BASE + target_desc_high_off)

    # =========================================================================
    # LAYER 3: Descriptors in-place override (0x19e08 & 0x19fe0)
    # =========================================================================
    # Normal desc 0x19e08: [ft_ptr (8B), ft_steps (4B), pad (4B), hw_ptr (8B), hw_rows (4B), pad (4B)]
    groups[0x19e08] = struct.pack('<QI', LOAD_BASE + target_ft_norm_off, target_ft_norm_steps)
    groups[0x19e18] = struct.pack('<QI', LOAD_BASE + target_hw_norm_off, target_hw_norm_rows)
    # High temp desc 0x19fe0:
    groups[0x19fe0] = struct.pack('<QI', LOAD_BASE + target_ft_high_off, target_ft_high_steps)
    groups[0x19ff0] = struct.pack('<QI', LOAD_BASE + target_hw_high_off, target_hw_high_rows)

    # =========================================================================
    # LAYER 4: Serenity Active Tables In-Place (0x16a18, 0x195f0, 0x17dc8, 0x1a0d8)
    # =========================================================================
    # Serenity Normal HW table 0x16a18:
    # Row 7 starts at 0x16a18 + 7*7 = 0x16a49.
    # Align to 4 bytes: 0x16a48
    # At 0x16a48: 1 byte of Row 6 (byte 6) + 7 bytes of Row 7 = 8 bytes
    r6_last = mod_payload[0x16a48]
    groups[0x16a48] = bytes([r6_last]) + factory_row_bytes

    # Serenity High HW table 0x195f0:
    # Row 7 starts at 0x195f0 + 7*7 = 0x19621. Align to 0x19620 (8 bytes)
    # Row 7 for high temp = Channel 6 (1.95 GHz) = [03 00 06 06 0a 04 05]
    r6_high_last = mod_payload[0x19620]
    high_row_bytes = bytes([0x03, 0x00, 0x06, 0x06, 0x0a, 0x04, 0x05])
    groups[0x19620] = bytes([r6_high_last]) + high_row_bytes

    # Serenity Normal Freq table 0x17dc8 Step 6 (starts at 0x17dc8 + 6*8 = 0x17df8):
    groups[0x17df8] = struct.pack('<2I', target_freq_khz, target_volt_uv)

    # Serenity High Freq table 0x1a0d8 Step 6 (starts at 0x1a0d8 + 6*8 = 0x1a108):
    groups[0x1a108] = struct.pack('<2I', 1950000, 990000)

    # =========================================================================
    # Table A (0x645a0000) & Table B (0x64580000) PLL Registers
    # =========================================================================
    # Table A Reg 0xbc, 0xc0, 0xc4
    groups[0x1594c] = struct.pack('<I', target_cfg)
    groups[0x1595c] = struct.pack('<I', target_mult)
    groups[0x1597c] = struct.pack('<I', target_cfg)
    groups[0x1598c] = struct.pack('<I', target_mult)
    groups[0x159ac] = struct.pack('<I', target_cfg)
    groups[0x159bc] = struct.pack('<I', target_mult)

    # Table B Reg 0x88, 0x8c, 0x90, 0x94
    groups[0x15ab0] = struct.pack('<I', target_cfg)
    groups[0x15ac0] = struct.pack('<I', target_mult)
    groups[0x15ae0] = struct.pack('<I', target_cfg)
    groups[0x15af0] = struct.pack('<I', target_mult)
    groups[0x15b10] = struct.pack('<I', target_cfg)
    groups[0x15b20] = struct.pack('<I', target_mult)
    groups[0x15b40] = struct.pack('<I', target_cfg)
    groups[0x15b50] = struct.pack('<I', target_mult)

    # =========================================================================
    # All 37 Frequency Tables (Step 6) & All 8 Chip Process Corners
    # =========================================================================
    freq_count = 0
    for i in range(0, len(payload) - 8, 4):
        f, v = struct.unpack('<II', payload[i:i+8])
        if f == 1820000 and 700000 <= v <= 1200000:
            groups[i] = struct.pack('<2I', target_freq_khz, target_volt_uv)
            freq_count += 1

    matches_08 = list(re.finditer(b'\x03\x00\x03\x03\x08\x04\x05', payload))
    matches_0a = list(re.finditer(b'\x03\x00\x04\x04\x0a\x04\x05', payload))
    hw_corners_count = 0
    for m8, ma in zip(matches_08, matches_0a):
        s8 = m8.start()
        sa = ma.start()
        if sa == s8 + 7:
            aligned = s8 & ~3
            raw_16 = bytearray(payload[aligned : aligned + 16])
            raw_16[2:9] = factory_row_bytes
            raw_16[9:16] = factory_row_bytes
            groups[aligned] = bytes(raw_16)
            hw_corners_count += 1

    print(f"Profile {target_freq_khz//1000} MHz:")
    print(f"  Patched {freq_count} Freq targets, {hw_corners_count} HW Corners, 14 PLL Mult/Cfg registers.")
    print(f"  Patched 8 .rela.dyn relocations.")
    print(f"  Patched 4 Master LUT pointers, 2 Active Descriptors, 2 Active HW Tables.")

    # Put mod_payload back into stock structure
    stock[0x200 : 0x200 + 0x20240] = mod_payload

    # Pack with magic shellcode
    out_bytes = pack_magic(stock, 0x20240, groups, LOAD_BASE, add_len=0x800)

    # Pad to partition size (1 MB)
    if len(out_bytes) > PART_SIZE:
        out_bytes = out_bytes[:PART_SIZE]
    elif len(out_bytes) < PART_SIZE:
        out_bytes = out_bytes + b'\x00' * (PART_SIZE - len(out_bytes))

    # Verification checks
    expected_checks = [
        ("Master LUT Cluster 1 Norm Pointer", 0x17060, struct.pack('<Q', LOAD_BASE + target_desc_norm_off)),
        ("Master LUT Cluster 1 High Pointer", 0x17080, struct.pack('<Q', LOAD_BASE + target_desc_high_off)),
        ("Serenity Desc 0x19e08 Freq Ptr",   0x19e08, struct.pack('<QI', LOAD_BASE + target_ft_norm_off, target_ft_norm_steps)),
        ("Serenity Desc 0x19e08 HW Ptr",     0x19e18, struct.pack('<QI', LOAD_BASE + target_hw_norm_off, target_hw_norm_rows)),
        ("Serenity HW Table 0x16a18 Row 7",   0x16a49, factory_row_bytes),
        ("Serenity Freq Table 0x17dc8 Step 6", 0x17df8, struct.pack('<2I', target_freq_khz, target_volt_uv)),
        ("Table B Reg 0x88 Mult",             0x15ac0, struct.pack('<I', target_mult)),
        ("Table B Reg 0x94 Mult",             0x15b50, struct.pack('<I', target_mult)),
    ]

    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected_checks)
    if not ok:
        raise RuntimeError(f"Verification failed for {out_path}!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"SUCCESS: Generated {out_path}")
    print(f"  Target: Cortex-A75 {target_freq_khz // 1000} MHz @ {target_volt_uv // 1000} mV")
    print(f"  Factory Row Bytes: {factory_row_bytes.hex()}")
    print(f"  Multiplier: {target_mult} (=> {target_mult * 26} MHz), CFG: {target_cfg}")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")

def main():
    print("=== Building Quad-Layer Overclock SML Images for Unisoc T7250 ===\n")
    
    # Profile 1: Full 2.21 GHz Quad Overclock
    # Targets Unisoc Factory 2.21 GHz Profile (0x18f50, 10 steps, 11 rows)
    # Channel 7: [03 00 07 07 0a 04 05]
    build_quad_profile(
        target_freq_khz=2210000,
        target_volt_uv=1050000,
        factory_row_bytes=bytes([0x03, 0x00, 0x07, 0x07, 0x0a, 0x04, 0x05]),
        target_mult=85,
        target_cfg=6,
        target_desc_norm_off=0x18f50,  # 2.21 GHz Factory Profile (10 steps up to 2.21 GHz @ 1050 mV)
        target_desc_high_off=0x19668,  # 1.95 GHz Factory Profile (9 steps up to 1.95 GHz @ 990 mV)
        target_ft_norm_off=0x174f8,    # 10 steps
        target_ft_norm_steps=10,
        target_hw_norm_off=0x17938,    # 11 rows (Row 10 = Channel 7)
        target_hw_norm_rows=11,
        target_ft_high_off=0x18e38,    # 9 steps
        target_ft_high_steps=9,
        target_hw_high_off=0x187b0,    # 10 rows (Row 9 = Channel 6)
        target_hw_high_rows=10,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_quad_2210mhz.img'
    )

    # Profile 2: Safe 1.95 GHz Quad Overclock
    # Targets Unisoc Factory 1.95 GHz Profile (0x19668, 9 steps, 10 rows)
    # Channel 6: [03 00 06 06 0a 04 05]
    build_quad_profile(
        target_freq_khz=1950000,
        target_volt_uv=990000,
        factory_row_bytes=bytes([0x03, 0x00, 0x06, 0x06, 0x0a, 0x04, 0x05]),
        target_mult=75,
        target_cfg=4,
        target_desc_norm_off=0x19668,  # 1.95 GHz Factory Profile (9 steps up to 1.95 GHz @ 990 mV)
        target_desc_high_off=0x19668,  # 1.95 GHz
        target_ft_norm_off=0x18e38,    # 9 steps
        target_ft_norm_steps=9,
        target_hw_norm_off=0x187b0,    # 10 rows (Row 9 = Channel 6)
        target_hw_norm_rows=10,
        target_ft_high_off=0x18e38,    # 9 steps
        target_ft_high_steps=9,
        target_hw_high_off=0x187b0,    # 10 rows
        target_hw_high_rows=10,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_quad_1950mhz.img'
    )

if __name__ == '__main__':
    main()
