#!/usr/bin/env python3
"""Build Hardware Channel 4 Overclock SML Images for Unisoc T7250 / UMS9230E.

Silicon Architecture Resolution:
1. In UMS9230E silicon, the Cortex-A75 hardware clock MUX physically selects
   MPLL1 Channel 4 (Reg 0x64580088) for the maximum performance state (Step 6).
2. The MPLL1 Channel Synthesizer table in SML (at payload offset 0x159d4 - 0x15b64)
   programs each channel at boot:
   - Channel 4 (Reg 0x88) stock: cfg = 4, mult = 70 (70 * 26 MHz = 1820 MHz)
   - Overclocked Channel 4:
       * 2.210 GHz: cfg = 6, mult = 85 (85 * 26 MHz = 2210 MHz) @ 1050 mV
       * 1.950 GHz: cfg = 4, mult = 75 (75 * 26 MHz = 1950 MHz) @ 990 mV
3. Stock MUX routing (Row 7 = 03 00 04 04 0a 04 05) routes directly to Channel 4.
4. Stock Row 6 (03 00 03 03 08 04 05) routes to Channel 3 (1690 MHz).
5. All 37 frequency tables updated with target_freq @ target_volt.
6. 100% Stock RSA Signature Preservation via magic append shellcode.
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
    # Payload is 100% UNTOUCHED stock data!
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

ORIGINAL_PAYLOAD_SIZE = 0x20240

def simulate_and_verify(image_bytes, load_base, expected_checks):
    raw = bytearray(image_bytes)
    payload = raw[0x210 : 0x210 + ORIGINAL_PAYLOAD_SIZE]
    assert hashlib.sha256(payload).hexdigest() == KNOWN_PAYLOAD_SHA256, "Payload altered!"

    ram = bytearray(payload)
    magic_off = 0x210 + ORIGINAL_PAYLOAD_SIZE
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

def build_hardware_image(target_freq_khz, target_volt_uv, pll_bias, pll_mult, out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock = f.read()

    payload = stock[0x200 : 0x200 + 0x20240]
    assert hashlib.sha256(payload).hexdigest() == KNOWN_PAYLOAD_SHA256

    groups = {}

    # 1. Frequency Tables: Patch all 37 entries of 1820000 to target_freq @ target_volt
    freq_count = 0
    for i in range(0, len(payload) - 8, 4):
        f, v = struct.unpack('<II', payload[i:i+8])
        if f == 1820000 and 700000 <= v <= 1200000:
            groups[i] = struct.pack('<2I', target_freq_khz, target_volt_uv)
            freq_count += 1

    # 2. MPLL1 Channel 4 Configuration:
    # 0x15aa4: reg=0x88, shift=0, mask=7, val=pll_bias (cfg)
    # 0x15ab4: reg=0x88, shift=4, mask=0x7ff, val=pll_mult (multiplier)
    ch4_words = [
        0x00000088, 0x00000000, 0x00000007, pll_bias,
        0x00000088, 0x00000004, 0x000007ff, pll_mult
    ]
    groups[0x15aa4] = struct.pack('<8I', *ch4_words)

    # Verify no overlaps
    sorted_offs = sorted(groups.keys())
    for i in range(len(sorted_offs) - 1):
        o1 = sorted_offs[i]
        o2 = sorted_offs[i+1]
        assert o1 + len(groups[o1]) <= o2, f"Overlap between 0x{o1:x} and 0x{o2:x}"

    print(f"Profile {target_freq_khz // 1000} MHz (Hardware MPLL1 Channel 4 mult={pll_mult}, cfg={pll_bias}):")
    print(f"  Total patch groups: {len(groups)} (zero overlaps, all 4-byte aligned)")
    print(f"  Patched {freq_count} Freq targets, Channel 4 at 0x15aa4 (8 words).")
    print(f"  Hardware MUX Row 7 KEPT AT STOCK Channel 4 (04 04).")
    print(f"  Hardware MUX Row 6 KEPT AT STOCK Channel 3 (03 03 = 1690 MHz).")
    print(f"  Step counts 100% untouched stock (7 steps, 8 rows).")

    # Pack with magic shellcode
    out_bytes = pack_magic(stock, 0x20240, groups, LOAD_BASE, add_len=0x800)

    # Pad to partition size (1 MB)
    if len(out_bytes) > PART_SIZE:
        out_bytes = out_bytes[:PART_SIZE]
    elif len(out_bytes) < PART_SIZE:
        out_bytes = out_bytes + b'\x00' * (PART_SIZE - len(out_bytes))

    # Verification checks
    expected_checks = [
        ("Serenity Freq Table 0x17dc8 Step 6", 0x17df8, struct.pack('<2I', target_freq_khz, target_volt_uv)),
        ("MPLL1 Ch4 cfg at 0x15ab0", 0x15ab0, struct.pack('<I', pll_bias)),
        ("MPLL1 Ch4 mult at 0x15ac0", 0x15ac0, struct.pack('<I', pll_mult)),
        ("Serenity HW Table 0x16a18 Row 6 (Stock Ch 3)", 0x16a42, b'\x03\x00\x03\x03\x08\x04\x05'),
        ("Serenity HW Table 0x16a18 Row 7 (Stock Ch 4)", 0x16a49, b'\x03\x00\x04\x04\x0a\x04\x05'),
    ]

    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected_checks)
    if not ok:
        raise RuntimeError(f"Verification failed for {out_path}!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"SUCCESS: Generated {out_path}")
    print(f"  Target: Cortex-A75 {target_freq_khz // 1000} MHz @ {target_volt_uv // 1000} mV")
    print(f"  MPLL1 Channel 4: mult = {pll_mult} (0x{pll_mult:02x}), cfg = {pll_bias}")
    print(f"  Expected 0x64580088 register: 0x{(pll_mult << 4) | pll_bias:08x}")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")

def main():
    print("=== Building Hardware MPLL1 Channel 4 Overclock SML Images ===\n")

    # Profile 1: Full 2.210 GHz (mult = 85, cfg = 6, 1050 mV)
    build_hardware_image(
        target_freq_khz=2210000,
        target_volt_uv=1050000,
        pll_bias=6,
        pll_mult=85,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_hardware_2210mhz.img'
    )

    # Profile 2: Rock-solid 1.950 GHz (mult = 75, cfg = 4, 990 mV)
    build_hardware_image(
        target_freq_khz=1950000,
        target_volt_uv=990000,
        pll_bias=4,
        pll_mult=75,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_hardware_1950mhz.img'
    )

if __name__ == '__main__':
    main()
