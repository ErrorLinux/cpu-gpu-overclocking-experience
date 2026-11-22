#!/usr/bin/env python3
"""Build Dual-Cluster Overclock SML Images (Cortex-A75 + Cortex-A55) for Unisoc T7250 / UMS9230E.

Dual Silicon Overclock Architecture:
1. Cortex-A75 (Big Cluster, cpu6-7):
   - Physical clock source: MPLL1 Channel 4 (Reg 0x64580088).
   - In stock Serenity: mult = 70 (1820 MHz), cfg = 4 @ 910 mV.
   - Dual-OC 2.21 GHz: mult = 85 (2210 MHz), cfg = 6 @ 1050 mV.
   - Dual-OC 1.95 GHz: mult = 75 (1950 MHz), cfg = 4 @ 990 mV.
   - Stock MUX Row 7 (03 00 04 04 0a 04 05) physically connects to Channel 4.
   - All 37 frequency entries of 1820000 updated to target_a75_freq @ target_a75_volt.

2. Cortex-A55 (Little Cluster, cpu0-5):
   - Physical clock source: MPLL Channels 5 & 6 (Reg 0x6458008c / 0x64580090).
   - In stock Serenity: 8 steps (max Step 7 = 1612000 kHz @ 896875 uV).
     Stock HW Row 8 (0x19d40): 03 00 04 03 08 04 05.
   - Official Unisoc factory 10-step reference design (e.g. 0x18760 / 0x16c10):
     * Step 7 (1612 MHz): Row 8  = 03 00 04 03 08 04 05
     * Step 8 (1716 MHz): Row 9  = 03 00 05 04 09 04 05
     * Step 9 (1820 MHz): Row 10 = 03 00 06 05 0a 04 05 @ 987500 - 1000000 uV.
   - Overclocking Step 7:
     * All 36 frequency entries of 1612000 updated to 1820000 kHz @ 1000000 uV (1.00V).
     * All 16 occurrences of Row 8 updated to Factory Row 10 (03 00 06 05 0a 04 05).
   - Zero conflict: A55 uses Channels 5/6, A75 uses Channel 4!

3. 100% Stock RSA-2048 Secure Boot Bit-for-Bit Preservation via magic append shellcode.
"""

import struct
import hashlib
import os
import sys

STOCK_INPUT = '/home/hoang/Downloads/serenity_global_images_A15.0.33.0.VGWMIXM_15.0/images/sml-sign.bin'
KNOWN_PAYLOAD_SHA256 = 'de88c8eb71e8b3b81aabdc5a47367702c990a4894ae08cd4ac1eb2616f7d5476'
LOAD_BASE = 0xB0000000
PART_SIZE = 0x100000  # 1 MB
ORIGINAL_PAYLOAD_SIZE = 0x20240

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

def build_dual_image(a75_freq_khz, a75_volt_uv, a75_pll_bias, a75_pll_mult,
                     a55_freq_khz, a55_volt_uv, oc_a55, out_path):
    with open(STOCK_INPUT, 'rb') as f:
        stock = f.read()

    payload = stock[0x200 : 0x200 + ORIGINAL_PAYLOAD_SIZE]
    assert hashlib.sha256(payload).hexdigest() == KNOWN_PAYLOAD_SHA256

    groups = {}

    # 1. Cluster 1 (Cortex-A75) Frequency: patch all 37 entries of 1820000
    a75_freq_count = 0
    for i in range(0, len(payload) - 8, 4):
        f, v = struct.unpack('<II', payload[i:i+8])
        if f == 1820000 and 700000 <= v <= 1200000:
            groups[i] = struct.pack('<2I', a75_freq_khz, a75_volt_uv)
            a75_freq_count += 1

    # 2. Cluster 1 (Cortex-A75) MPLL1 Channel 4 Synthesizer
    if a75_pll_mult is not None and a75_pll_bias is not None:
        ch4_words = [
            0x00000088, 0x00000000, 0x00000007, a75_pll_bias,
            0x00000088, 0x00000004, 0x000007ff, a75_pll_mult
        ]
        groups[0x15aa4] = struct.pack('<8I', *ch4_words)

    # 3. Cluster 0 (Cortex-A55) Frequency: patch all 36 entries of 1612000
    a55_freq_count = 0
    if oc_a55:
        for i in range(0, len(payload) - 8, 4):
            f, v = struct.unpack('<II', payload[i:i+8])
            if f == 1612000 and 700000 <= v <= 1200000:
                assert i not in groups, f'Collision at 0x{i:x}'
                groups[i] = struct.pack('<2I', a55_freq_khz, a55_volt_uv)
                a55_freq_count += 1

    # 4. Cluster 0 (Cortex-A55) Hardware Tables: patch all 16 occurrences of Row 8
    target_row8 = bytes([0x03, 0x00, 0x04, 0x03, 0x08, 0x04, 0x05])
    factory_row10 = bytes([0x03, 0x00, 0x06, 0x05, 0x0a, 0x04, 0x05])
    a55_hw_count = 0
    if oc_a55:
        idx = 0
        while True:
            idx = payload.find(target_row8, idx)
            if idx == -1:
                break
            aligned = idx & ~3
            offset_in_aligned = idx - aligned
            needed_len = ((offset_in_aligned + 7 + 3) // 4) * 4
            raw_block = bytearray(payload[aligned : aligned + needed_len])
            raw_block[offset_in_aligned : offset_in_aligned + 7] = factory_row10
            assert aligned not in groups, f'Collision at HW row 0x{aligned:x}'
            groups[aligned] = bytes(raw_block)
            a55_hw_count += 1
            idx += 1

    # Verify no overlaps
    sorted_offs = sorted(groups.keys())
    for i in range(len(sorted_offs) - 1):
        o1 = sorted_offs[i]
        o2 = sorted_offs[i+1]
        assert o1 + len(groups[o1]) <= o2, f"Overlap between 0x{o1:x} and 0x{o2:x}"

    print(f"Building: A75 @ {a75_freq_khz//1000} MHz | A55 @ {a55_freq_khz//1000 if oc_a55 else 1612} MHz:")
    print(f"  Total patch groups: {len(groups)} (zero overlaps, all 4-byte aligned)")
    print(f"  Patched {a75_freq_count} A75 Freq targets.")
    if a75_pll_mult is not None:
        print(f"  Patched MPLL1 Channel 4: mult={a75_pll_mult}, cfg={a75_pll_bias} at 0x15aa4.")
    if oc_a55:
        print(f"  Patched {a55_freq_count} A55 Freq targets (1612 -> {a55_freq_khz} @ {a55_volt_uv//1000} mV).")
        print(f"  Patched {a55_hw_count} A55 HW Tables with Unisoc Factory Row 10 (03 00 06 05 0a 04 05).")

    # Pack with magic shellcode
    out_bytes = pack_magic(stock, ORIGINAL_PAYLOAD_SIZE, groups, LOAD_BASE, add_len=0x800)

    # Pad to partition size (1 MB)
    if len(out_bytes) > PART_SIZE:
        out_bytes = out_bytes[:PART_SIZE]
    elif len(out_bytes) < PART_SIZE:
        out_bytes = out_bytes + b'\x00' * (PART_SIZE - len(out_bytes))

    # Verification checks
    expected_checks = [
        ("Serenity A75 Freq Table 0x17dc8 Step 6", 0x17df8, struct.pack('<2I', a75_freq_khz, a75_volt_uv)),
        ("Serenity A75 HW Table 0x16a18 Row 7", 0x16a49, b'\x03\x00\x04\x04\x0a\x04\x05'),
    ]
    if a75_pll_mult is not None:
        expected_checks.append(("MPLL1 Ch4 cfg at 0x15ab0", 0x15ab0, struct.pack('<I', a75_pll_bias)))
        expected_checks.append(("MPLL1 Ch4 mult at 0x15ac0", 0x15ac0, struct.pack('<I', a75_pll_mult)))

    if oc_a55:
        expected_checks.append(("Serenity A55 Freq Table 0x199d8 Step 7", 0x19a10, struct.pack('<2I', a55_freq_khz, a55_volt_uv)))
        expected_checks.append(("Serenity A55 HW Table 0x19d08 Row 8", 0x19d40, factory_row10))

    ok = simulate_and_verify(out_bytes, LOAD_BASE, expected_checks)
    if not ok:
        raise RuntimeError(f"Verification failed for {out_path}!")

    with open(out_path, 'wb') as f:
        f.write(out_bytes)

    out_sha = hashlib.sha256(out_bytes).hexdigest()
    print(f"SUCCESS: Generated {out_path}")
    print(f"  File size: {len(out_bytes)} bytes")
    print(f"  SHA256: {out_sha}\n")
    return out_path, out_sha

def main():
    print("==================================================================")
    print("  Unisoc T7250 / UMS9230 Dual-Cluster Overclock SML Generator   ")
    print("==================================================================\n")

    # 1. Dual Overclock: A75 @ 2.210 GHz + A55 @ 1.820 GHz (Max Performance Profile)
    build_dual_image(
        a75_freq_khz=2210000,
        a75_volt_uv=1050000,
        a75_pll_bias=6,
        a75_pll_mult=85,
        a55_freq_khz=1820000,
        a55_volt_uv=1000000,
        oc_a55=True,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_dual_oc_a75_2210_a55_1820.img'
    )

    # 2. Dual Overclock: A75 @ 1.950 GHz + A55 @ 1.820 GHz (Rock-Solid Daily Profile)
    build_dual_image(
        a75_freq_khz=1950000,
        a75_volt_uv=990000,
        a75_pll_bias=4,
        a75_pll_mult=75,
        a55_freq_khz=1820000,
        a55_volt_uv=1000000,
        oc_a55=True,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_dual_oc_a75_1950_a55_1820.img'
    )

    # 3. A55-Only Overclock: A55 @ 1.820 GHz + A75 @ Stock 1.820 GHz (Safe Little Core OC)
    build_dual_image(
        a75_freq_khz=1820000,
        a75_volt_uv=910000,
        a75_pll_bias=None,
        a75_pll_mult=None,
        a55_freq_khz=1820000,
        a55_volt_uv=1000000,
        oc_a55=True,
        out_path='/home/hoang/Downloads/oc_gpu/oc_cpu/sml_a55_only_1820mhz.img'
    )

if __name__ == '__main__':
    main()
