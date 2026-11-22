#!/usr/bin/env python3
"""Build true PLL-reprogrammed SML images for Unisoc T7250 (Redmi A5 / serenity).

Breakthrough:
- Register 0x645a00bc is the active PLL register for Cortex-A75 top OPP (Index 6).
- Stock: SML programs reg 0xbc with 0x464 (multiplier 0x46 = 70 * 26 = 1820 MHz).
- Patch: Reprograms the PLL table at 0x1594c / 0x1595c so reg 0xbc receives:
  - 1950 MHz: multiplier 0x4b = 75 * 26 = 1950 MHz (0x4b4)
  - 2210 MHz: multiplier 0x55 = 85 * 26 = 2210 MHz (0x556)
- CPUDVFS Index 6 stays routed to reg 0xbc, but reg 0xbc now generates true OC frequency!
"""

import struct
import hashlib

STOCK_INPUT = '/home/hoang/Downloads/serenity_global_images_A15.0.33.0.VGWMIXM_15.0/images/sml-sign.bin'
KNOWN_PAYLOAD_SHA256 = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'
LOAD_BASE = 0xB0000000
PART_SIZE = 0x100000

# Payload offsets
C0_OFF = 0x199d8       # Cluster 0 (A55) freq/volt table
C1_OFF = 0x17dc8       # Cluster 1 (A75) freq/volt table
C1_HW_OFF = 0x19e54    # Cluster 1 HW row 6 word start
PLL_BC_OFF = 0x15948   # PLL reg 0xbc config group

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
    raw = bytearray(image_bytes)
    size = struct.unpack_from('<I', raw, 0x30)[0]
    payload = raw[0x210 : 0x210 + size]
    ram = bytearray(payload)
    
    magic_off = 0x210 + 0x20240
    patch_data_off = magic_off + 0x70
    
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

def build_profile(freq_khz, volt_uv, pll_sub1, pll_mult, out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock_file = f.read()

    if len(stock_file) < PART_SIZE:
        stock_padded = stock_file + b'\x00' * (PART_SIZE - len(stock_file))
    else:
        stock_padded = stock_file

    payload = stock_file[0x200 : 0x200 + 0x20240]
    p_sha = hashlib.sha256(payload).hexdigest()
    assert p_sha == KNOWN_PAYLOAD_SHA256

    # 1. C1 Table patch
    c1_rows = [
        (768000, 750000),
        (1040000, 750000),
        (1228800, 762500),
        (1404000, 780000),
        (1536000, 820000),
        (1690000, 870000),
        (freq_khz, volt_uv)
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

    # 3. Hardware Row 6 patch (keep byte 5=4, byte 6=4 -> points to reg 0xbc!)
    # Byte 0 becomes 0x0a (voltage level)
    # Row 6: [0x0a, 0x04, 0x05, 0x03, 0x00, 0x04, 0x04]
    hw_bytes = [0x0a, 0x04, 0x05, 0x03, 0x00, 0x04, 0x04]
    orig_w1, orig_w2, orig_w3 = struct.unpack_from('<3I', payload, C1_HW_OFF)
    new_w1 = (orig_w1 & 0x0000ffff) | (hw_bytes[0] << 16) | (hw_bytes[1] << 24)
    new_w2 = (hw_bytes[2] << 0) | (hw_bytes[3] << 8) | (hw_bytes[4] << 16) | (hw_bytes[5] << 24)
    new_w3 = (orig_w3 & 0xffffff00) | (hw_bytes[6] << 0)
    hw_words = [new_w1, new_w2, new_w3]

    # 4. PLL Reg 0xbc patch at PLL_BC_OFF (0x15948)
    # Contiguous 6 words:
    # 0x15948: mask = 7
    # 0x1594c: sub1 = pll_sub1 (e.g. 6 or 4)
    # 0x15950: reg = 0xbc
    # 0x15954: shift = 4
    # 0x15958: mask = 0x7ff
    # 0x1595c: mult = pll_mult (e.g. 85 for 2210 MHz, 75 for 1950 MHz)
    pll_words = [0x00000007, pll_sub1, 0x000000bc, 0x00000004, 0x000007ff, pll_mult]

    groups = [
        (C1_OFF, c1_words),
        (C0_OFF, c0_words),
        (C1_HW_OFF, hw_words),
        (PLL_BC_OFF, pll_words)
    ]

    out_bytes = pack_magic(stock_padded, 0x20240, groups, LOAD_BASE, add_len=0x200)

    if len(out_bytes) > PART_SIZE:
        out_bytes = out_bytes[:PART_SIZE]
    elif len(out_bytes) < PART_SIZE:
        out_bytes = out_bytes + b'\x00' * (PART_SIZE - len(out_bytes))

    expected = [
        ("C1 Freq/Volt Row 6", C1_OFF + 6*8, struct.pack('<2I', freq_khz, volt_uv)),
        ("C1 HW Row 6 (7 bytes)", 0x19e56, bytes(hw_bytes)),
        ("PLL reg 0xbc sub1", 0x1594c, struct.pack('<I', pll_sub1)),
        ("PLL reg 0xbc mult", 0x1595c, struct.pack('<I', pll_mult)),
    ]
    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected)
    if not ok:
        raise RuntimeError("Verification failed!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"Generated {out_path}:")
    print(f"  Target: Cortex-A75 {freq_khz // 1000} MHz @ {volt_uv // 1000} mV")
    print(f"  PLL Multiplier: {pll_mult} * 26 MHz = {pll_mult * 26} MHz (sub1={pll_sub1})")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")

def main():
    print("=== Building Real Hardware PLL Overclock SML Images ===\n")
    
    # 1. 2210 MHz @ 1050 mV (Multiplier 85 * 26 = 2210 MHz, sub1=6)
    build_profile(
        freq_khz=2210000,
        volt_uv=1050000,
        pll_sub1=6,
        pll_mult=85,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_real_pll_2210mhz.img'
    )

    # 2. 1950 MHz @ 980 mV (Multiplier 75 * 26 = 1950 MHz, sub1=4)
    build_profile(
        freq_khz=1950000,
        volt_uv=980000,
        pll_sub1=4,
        pll_mult=75,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_real_pll_1950mhz.img'
    )

if __name__ == '__main__':
    main()
