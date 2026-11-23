#!/usr/bin/env python3
"""Repack vendor_boot while keeping the DTB/table/bootconfig/footer at their
original byte offsets. Only the header ramdisk_size and the ramdisk bytes
change; the table entry ramdisk_size is patched in place."""
import argparse
import struct
from pathlib import Path

DTB_OFF = 0x20B9000
TAB_OFF = 0x20DC000

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base')
    ap.add_argument('ramdisk_lz4')
    ap.add_argument('out')
    args = ap.parse_args()

    base = Path(args.base).read_bytes()
    rd = Path(args.ramdisk_lz4).read_bytes()
    assert len(base) == 104857600 and base[:8] == b'VNDRBOOT'
    old_size = struct.unpack_from('<I', base, 0x18)[0]
    assert 4096 + len(rd) <= DTB_OFF, (len(rd), DTB_OFF - 4096)

    out = bytearray(base[:4096])
    struct.pack_into('<I', out, 0x18, len(rd))
    out += rd
    out += b'\0' * (DTB_OFF - len(out))
    tail = bytearray(base[DTB_OFF:])
    struct.pack_into('<I', tail, TAB_OFF - DTB_OFF, len(rd))
    out += tail
    assert len(out) == len(base), len(out)

    Path(args.out).write_bytes(out)
    print(f'wrote {args.out}; ramdisk {old_size} -> {len(rd)}; DTB kept at {DTB_OFF:#x}')
    print(f'table ramdisk_size {old_size} -> {len(rd)}')

if __name__ == '__main__':
    main()
