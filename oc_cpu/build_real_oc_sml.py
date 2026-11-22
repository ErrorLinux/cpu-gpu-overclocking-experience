#!/usr/bin/env python3
"""Build real overclock SML images for Unisoc T7250 (Redmi A5 / serenity).

Applies:
1. DVFS Table Patch (Freq @ Voltage for PMIC and Kernel reporting)
2. CPUDVFS Hardware Register Table Patch (MUX & MPLL Source Selector)
   Stock Index 6: selects MPLL Entry 4 (70 * 26 = 1820 MHz)
   Real OC Index 6: selects MPLL Entry 7 (85 * 26 = 2210 MHz)
"""

import struct
import hashlib
import sys
import os

STOCK_INPUT = '/home/hoang/Downloads/serenity_global_images_A15.0.33.0.VGWMIXM_15.0/images/sml-sign.bin'
KNOWN_PAYLOAD_SHA256 = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'
LOAD_BASE = 0xB0000000
PART_SIZE = 0x100000  # 1 MB (1048576 bytes)

# Offsets in SML payload (relative to payload start at 0x200)
C0_OFF = 0x199d8       # Cluster 0 (A55) freq/volt table (8 rows)
C1_OFF = 0x17dc8       # Cluster 1 (A75) freq/volt table (7 rows)
C1_HW_OFF = 0x19e54    # Cluster 1 HW row 6 word start (row 6 bytes start at 0x19e56)

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

def pack_magic(data, size, groups, load_base, add_len=0x200):
    foot_off = 0x200 + size
    footer = bytearray(data[foot_off:foot_off + 0x60])
    if footer[0:7] != b'SIMGHDR' or struct.unpack_from('<Q', footer, 0x18)[0] != 0x200:
        raise SystemExit('SIMGHDR footer not found / already patched')
    
    patch_data = b''
    for off, words in groups:
        patch_data += struct.pack('<II', load_base + off, len(words))
        patch_data += struct.pack('<%dI' % len(words), *words)
    patch_data += struct.pack('<I', 0)
    
    shell = build_shellcode(size)
    if len(shell) + len(patch_data) > add_len - 0x10:
        raise ValueError('add_len %#x too small' % add_len)
    
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

def simulate_and_verify(image_bytes, load_base, expected_patches):
    """Simulate shellcode execution in RAM to verify patched memory state."""
    raw = bytearray(image_bytes)
    size = struct.unpack_from('<I', raw, 0x30)[0]
    payload = raw[0x210 : 0x210 + size]
    
    # In RAM, payload is loaded at load_base
    ram = bytearray(payload)
    
    # Locate magic block (shellcode + patch_data)
    magic_off = 0x210 + 0x20240  # original size
    patch_data_off = magic_off + 0x70
    
    # Parse patch_data
    curr = patch_data_off
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
            
    print("Simulated shellcode runtime memory verification:")
    for name, offset, expected in expected_patches:
        actual = bytes(ram[offset:offset+len(expected)])
        if actual == expected:
            print(f"  [OK] {name} at 0x{offset:x}: {actual.hex()}")
        else:
            print(f"  [FAIL] {name} at 0x{offset:x}: actual {actual.hex()} != expected {expected.hex()}")
            return False
    return True

def build_profile(target_freq_khz, target_volt_uv, hw_bytes, out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock_file = f.read()

    # Pad to PART_SIZE first
    if len(stock_file) < PART_SIZE:
        stock_padded = stock_file + b'\x00' * (PART_SIZE - len(stock_file))
    else:
        stock_padded = stock_file

    payload = stock_file[0x200 : 0x200 + 0x20240]
    p_sha = hashlib.sha256(payload).hexdigest()
    assert p_sha == KNOWN_PAYLOAD_SHA256, f"Payload SHA mismatch: {p_sha}"

    # 1. C1 Table patch
    # Stock C1 has 7 rows: [(768000, 750000), ..., (1820000, 910000)]
    c1_rows = [
        (768000, 750000),
        (1040000, 750000),
        (1228800, 762500),
        (1404000, 780000),
        (1536000, 820000),
        (1690000, 870000),
        (target_freq_khz, target_volt_uv)
    ]
    c1_words = []
    for f, v in c1_rows:
        c1_words.extend([f, v])

    # 2. C0 Table patch (A55 up to 1820000 @ 1050000)
    c0_rows = [
        (614400, 700000),
        (768000, 700000),
        (884000, 700000),
        (1040000, 700000),
        (1228800, 762500),
        (1378000, 815625),
        (1612000, 975000),
        (1820000, 1050000)
    ]
    c0_words = []
    for f, v in c0_rows:
        c0_words.extend([f, v])

    # 3. Hardware Row 6 patch (3 words at C1_HW_OFF = 0x19e54)
    # Read original words at 0x19e54
    orig_w1, orig_w2, orig_w3 = struct.unpack_from('<3I', payload, C1_HW_OFF)
    # hw_bytes has 7 bytes: [b0, b1, b2, b3, b4, b5, b6]
    # In payload:
    # 0x19e54: [Row5 byte 5, Row5 byte 6, Row6 byte 0, Row6 byte 1]
    # 0x19e58: [Row6 byte 2, Row6 byte 3, Row6 byte 4, Row6 byte 5]
    # 0x19e5c: [Row6 byte 6, Row7 byte 0, Row7 byte 1, Row7 byte 2]
    new_w1 = (orig_w1 & 0x0000ffff) | (hw_bytes[0] << 16) | (hw_bytes[1] << 24)
    new_w2 = (hw_bytes[2] << 0) | (hw_bytes[3] << 8) | (hw_bytes[4] << 16) | (hw_bytes[5] << 24)
    new_w3 = (orig_w3 & 0xffffff00) | (hw_bytes[6] << 0)

    hw_words = [new_w1, new_w2, new_w3]

    groups = [
        (C1_OFF, c1_words),
        (C0_OFF, c0_words),
        (C1_HW_OFF, hw_words)
    ]

    out_bytes = pack_magic(stock_padded, 0x20240, groups, LOAD_BASE, add_len=0x200)

    # Pad output to PART_SIZE
    if len(out_bytes) > PART_SIZE:
        out_bytes = out_bytes[:PART_SIZE]
    elif len(out_bytes) < PART_SIZE:
        out_bytes = out_bytes + b'\x00' * (PART_SIZE - len(out_bytes))

    # Verify simulation
    expected = [
        ("C1 Freq/Volt Row 6", C1_OFF + 6*8, struct.pack('<2I', target_freq_khz, target_volt_uv)),
        ("C1 HW Row 6 (7 bytes)", 0x19e56, bytes(hw_bytes))
    ]
    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected)
    if not ok:
        raise RuntimeError("Verification failed!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"Generated {out_path}:")
    print(f"  Target: Cortex-A75 {target_freq_khz // 1000} MHz @ {target_volt_uv // 1000} mV")
    print(f"  HW Register bytes: {' '.join(f'0x{b:02x}' for b in hw_bytes)}")
    print(f"  File size: {len(out_bytes)} bytes ({hex(len(out_bytes))})")
    print(f"  SHA256: {out_sha}\n")
    return out_path

def main():
    print("=== Building Unisoc T7250 Real Hardware Overclock SML Images ===\n")
    
    # Profile 1: Maximum Performance Real OC (2.21 GHz @ 1050 mV)
    # HW Row 6 = [0x0a, 0x04, 0x05, 0x03, 0x00, 0x07, 0x07] -> MPLL Entry 7 (2210 MHz)
    build_profile(
        target_freq_khz=2210000,
        target_volt_uv=1050000,
        hw_bytes=[0x0a, 0x04, 0x05, 0x03, 0x00, 0x07, 0x07],
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_real_oc_2210mhz.img'
    )

    # Profile 2: Moderate Real OC (1.95 GHz @ 980 mV)
    # HW Row 6 = [0x0a, 0x04, 0x05, 0x03, 0x00, 0x06, 0x06] -> MPLL Entry 6 (1950 MHz)
    build_profile(
        target_freq_khz=1950000,
        target_volt_uv=980000,
        hw_bytes=[0x0a, 0x04, 0x05, 0x03, 0x00, 0x06, 0x06],
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_real_oc_1950mhz.img'
    )

if __name__ == '__main__':
    main()
