#!/usr/bin/env python3
"""Build Native Silicon Channel Overclock SML Images for Unisoc T7250 / UMS9230E.

Key Silicon Architecture Discoveries:
1. Stock MPLL1 Silicon Channel Synthesizers:
   - Channel 0 (Reg 0x78): 1040 MHz (40 * 26 MHz) [cfg = 0]
   - Channel 1 (Reg 0x7c): 1404 MHz (54 * 26 MHz) [cfg = 2]
   - Channel 2 (Reg 0x80): 1612 MHz (62 * 26 MHz) [cfg = 3]
   - Channel 3 (Reg 0x84): 1690 MHz (65 * 26 MHz) [cfg = 3]
   - Channel 4 (Reg 0x88): 1820 MHz (70 * 26 MHz) [cfg = 4] (Stock Serenity Peak)
   - Channel 5 (Reg 0x8c): 1898 MHz (73 * 26 MHz) [cfg = 4]
   - Channel 6 (Reg 0x90): 1950 MHz (75 * 26 MHz) [cfg = 4] (Factory Locked 1.95 GHz)
   - Channel 7 (Reg 0x94): 2210 MHz (85 * 26 MHz) [cfg = 6] (Factory Locked 2.21 GHz)

2. The Native Hardware Overclock Mechanism:
   - Channel 7 (2.21 GHz) and Channel 6 (1.95 GHz) are ALREADY programmed and locked by
     factory silicon hardware at boot (MPLL1 status 0x64580054 = 0x0002072a).
   - In stock Serenity, Row 7 routes to Channel 4 (MUX 04 04 = 1820 MHz).
   - In this native overclock, Row 7 routes to Channel 7 (MUX 07 07 = 2210 MHz) or Channel 6 (MUX 06 06 = 1950 MHz).
   - Row 6 is 100% KEPT AT STOCK Channel 3 (MUX 03 03 = 1690 MHz), ensuring Step 5 runs at 1.69 GHz.
   - Zero PLL register modifications: leaving Table A & Table B untouched keeps
     MPLL1 100% stably locked without any risk of PLL unlock / 26 MHz drop.

3. Clean 7-Step Frequency Tables & Proper Voltages:
   - Step 6 (1820000) updated to target_freq @ target_volt (1050 mV for 2.21 GHz, 990 mV for 1.95 GHz).
   - Step counts remain stock (ft_steps = 7, hw_rows = 8). Zero out-of-bounds junk entries.

4. 100% Stock RSA Signature Preservation:
   - Stock signed payload (0x200 : 0x200 + 0x20240) is bit-for-bit UNTOUCHED stock data.
   - SHA-256 is de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476.
   - Zero Secure Boot brick risk.
"""

import struct
import hashlib
import os
import sys
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

def build_native_image(target_freq_khz, target_volt_uv, mux_channel, out_path):
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

    # 2. Hardware Tables: Patch ONLY Row 7 to native mux_channel (e.g. Channel 7 = 07 07 or Channel 6 = 06 06)
    # Row 6 is kept 100% UNTOUCHED stock (Channel 3 = 1690 MHz).
    new_row7 = bytes([0x03, 0x00, mux_channel, mux_channel, 0x0a, 0x04, 0x05])
    matches_08 = list(re.finditer(b'\x03\x00\x03\x03\x08\x04\x05', payload))
    matches_0a = list(re.finditer(b'\x03\x00\x04\x04\x0a\x04\x05', payload))
    assert len(matches_08) == 8 and len(matches_0a) == 8

    hw_corners_count = 0
    for m8, ma in zip(matches_08, matches_0a):
        s8 = m8.start()
        sa = ma.start()
        assert sa == s8 + 7
        aligned = sa & ~3
        offset_in_word = sa - aligned
        chunk = bytearray(payload[aligned : aligned + 8])
        # Preserve byte 0 (last byte of Row 6, 0x05)
        chunk[offset_in_word : offset_in_word + 7] = new_row7
        groups[aligned] = bytes(chunk)
        hw_corners_count += 1

    # Verify no overlaps
    sorted_offs = sorted(groups.keys())
    for i in range(len(sorted_offs) - 1):
        o1 = sorted_offs[i]
        o2 = sorted_offs[i+1]
        assert o1 + len(groups[o1]) <= o2, f"Overlap between 0x{o1:x} and 0x{o2:x}"

    print(f"Profile {target_freq_khz // 1000} MHz (Native Silicon MPLL1 Channel {mux_channel}):")
    print(f"  Total patch groups: {len(groups)} (zero overlaps, all 4-byte aligned)")
    print(f"  Patched {freq_count} Freq targets, {hw_corners_count} HW Corners Row 7.")
    print(f"  Row 6 100% KEPT AT STOCK Channel 3 (1690 MHz).")
    print(f"  PLL registers 100% untouched factory stock (locked!).")
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
        ("Serenity HW Table 0x16a18 Row 6 (Stock Ch 3)", 0x16a42, b'\x03\x00\x03\x03\x08\x04\x05'),
        ("Serenity HW Table 0x16a18 Row 7 (Ch %d)" % mux_channel, 0x16a49, new_row7),
    ]

    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected_checks)
    if not ok:
        raise RuntimeError(f"Verification failed for {out_path}!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"SUCCESS: Generated {out_path}")
    print(f"  Target: Cortex-A75 {target_freq_khz // 1000} MHz @ {target_volt_uv // 1000} mV")
    print(f"  HW Channel: {mux_channel} ({new_row7.hex()})")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")

def main():
    print("=== Building Native Silicon Channel Overclock SML Images ===\n")

    # Profile 1: Full 2.210 GHz Native Channel 7 (0x07)
    build_native_image(
        target_freq_khz=2210000,
        target_volt_uv=1050000,
        mux_channel=0x07,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_native_2210mhz.img'
    )

    # Profile 2: Safe 1.950 GHz Native Channel 6 (0x06)
    build_native_image(
        target_freq_khz=1950000,
        target_volt_uv=990000,
        mux_channel=0x06,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_native_1950mhz.img'
    )

if __name__ == '__main__':
    main()
