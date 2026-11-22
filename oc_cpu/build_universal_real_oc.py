#!/usr/bin/env python3
"""Build universal real hardware overclock SML image for Unisoc T7250 (serenity).

CRITICAL BREAKTHROUGH:
- Unisoc T7250 SML contains 8 PROCESS CORNER HARDWARE TABLES.
- Each table defines the exact MUX routing for all OPPs.
- Row 6 (max OPP) in ALL 8 tables is:
    [0x08, 0x04, 0x05, 0x03, 0x00, 0x04, 0x04]
  where bytes 5 and 6 (0x04, 0x04) select MPLL1 Entry 4 (1820 MHz).
- MPLL1 already has:
    Entry 6 (0x64580090): 1950 MHz
    Entry 7 (0x64580094): 2210 MHz
  already initialized and running in silicon!
- By patching Row 6 across ALL 8 PROCESS CORNER TABLES to select Entry 7 (or Entry 6):
  NO MATTER WHICH SILICON CORNER THE CHIP CHOOSES AT BOOT,
  CPUDVFS WILL SELECT THE TRUE 2.21 GHz (OR 1.95 GHz) PLL CLOCK!
"""

import struct
import hashlib

STOCK_INPUT = '/home/hoang/Downloads/serenity_global_images_A15.0.33.0.VGWMIXM_15.0/images/sml-sign.bin'
KNOWN_PAYLOAD_SHA256 = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'
LOAD_BASE = 0xB0000000
PART_SIZE = 0x100000

# The 8 hardware table row 6 offsets in SML payload:
ALL_HW_OFFSETS = [
    0x16a46,
    0x17966,
    0x17b66,
    0x187de,
    0x18eae,
    0x1961e,
    0x19e56,
    0x1a66e
]

# Standard C0 (A55) and C1 (A75) OPP frequency/voltage table offsets
C0_OFF = 0x199d8
C1_OFF = 0x17dc8

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

def pack_magic(data, size, groups, load_base, add_len=0x300):
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

def build_profile(target_freq_khz, target_volt_uv, mpll_entry, out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock_file = f.read()

    if len(stock_file) < PART_SIZE:
        stock_padded = stock_file + b'\x00' * (PART_SIZE - len(stock_file))
    else:
        stock_padded = stock_file

    payload = stock_file[0x200 : 0x200 + 0x20240]
    p_sha = hashlib.sha256(payload).hexdigest()
    assert p_sha == KNOWN_PAYLOAD_SHA256

    groups = []
    expected_patches = []

    # 1. C1 Table patch
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
    groups.append((C1_OFF, c1_words))
    expected_patches.append(("C1 Freq/Volt Row 6", C1_OFF + 6*8, struct.pack('<2I', target_freq_khz, target_volt_uv)))

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
    groups.append((C0_OFF, c0_words))

    # 3. Patch ALL 8 Hardware Tables Row 6
    # Row 6 format: [volt_idx, 0x04, 0x05, 0x03, 0x00, mpll_entry, mpll_entry]
    hw_bytes = [0x0a, 0x04, 0x05, 0x03, 0x00, mpll_entry, mpll_entry]
    
    for idx, hw_off in enumerate(ALL_HW_OFFSETS):
        # We patch 7 contiguous bytes starting at hw_off.
        # Find 4-byte aligned boundary:
        # hw_off % 4:
        aligned_off = hw_off & ~3
        shift = hw_off - aligned_off # 2 bytes
        # We need 3 words (12 bytes) to cover 2 bytes prefix + 7 bytes row + 3 bytes suffix
        orig_w1, orig_w2, orig_w3 = struct.unpack_from('<3I', payload, aligned_off)
        raw_12 = bytearray(struct.pack('<3I', orig_w1, orig_w2, orig_w3))
        raw_12[shift : shift + 7] = bytes(hw_bytes)
        new_words = list(struct.unpack('<3I', raw_12))
        groups.append((aligned_off, new_words))
        expected_patches.append((f"HW Table {idx} Row 6", hw_off, bytes(hw_bytes)))

    out_bytes = pack_magic(stock_padded, 0x20240, groups, LOAD_BASE, add_len=0x300)

    if len(out_bytes) > PART_SIZE:
        out_bytes = out_bytes[:PART_SIZE]
    elif len(out_bytes) < PART_SIZE:
        out_bytes = out_bytes + b'\x00' * (PART_SIZE - len(out_bytes))

    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected_patches)
    if not ok:
        raise RuntimeError("Verification failed!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"Generated {out_path}:")
    print(f"  Target: Cortex-A75 {target_freq_khz // 1000} MHz @ {target_volt_uv // 1000} mV")
    print(f"  MPLL1 Entry: {mpll_entry} (0x{mpll_entry:02x})")
    print(f"  Patched ALL 8 Hardware Tables!")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")

def main():
    print("=== Building Universal Real Hardware Overclock SML Images ===\n")
    
    # 1. Profile 2.21 GHz (MPLL1 Entry 7: 85 * 26 = 2210 MHz @ 1050 mV)
    build_profile(
        target_freq_khz=2210000,
        target_volt_uv=1050000,
        mpll_entry=0x07,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_universal_2210mhz.img'
    )

    # 2. Profile 1.95 GHz (MPLL1 Entry 6: 75 * 26 = 1950 MHz @ 980 mV)
    build_profile(
        target_freq_khz=1950000,
        target_volt_uv=980000,
        mpll_entry=0x06,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_universal_1950mhz.img'
    )

if __name__ == '__main__':
    main()
