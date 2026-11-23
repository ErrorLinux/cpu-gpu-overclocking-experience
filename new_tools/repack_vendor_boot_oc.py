#!/usr/bin/env python3
"""Byte-level repack of vendor_boot.img with a modified vendor ramdisk.

Keeps the SPRD DTB wrapper, vendor ramdisk table and bootconfig byte-identical,
only patches:
  * header vendor_ramdisk_size @ 0x18
  * vendor_ramdisk_table entry ramdisk_size @ +0 of the table
The AVB footer (last 64 bytes) is copied verbatim; the caller must have
verified boot disabled, exactly as for the earlier GPU/CPU margin images.
"""
import argparse
import struct
from pathlib import Path

PAGE = 4096
DTB_OFF = 0x20B9000          # original SPRD DTB wrapper offset
TAB_OFF = 0x20DC000          # original vendor_ramdisk_table offset
BC_OFF = 0x20DD000           # original bootconfig offset
FOOTER_LEN = 64

def align(v, a=PAGE):
    return (v + a - 1) & ~(a - 1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base')
    ap.add_argument('ramdisk_lz4')
    ap.add_argument('out')
    args = ap.parse_args()

    base = Path(args.base).read_bytes()
    rd = Path(args.ramdisk_lz4).read_bytes()
    assert len(base) == 104857600, len(base)
    assert base[:8] == b'VNDRBOOT'

    old_rd_size = struct.unpack_from('<I', base, 0x18)[0]
    assert old_rd_size == 34305665, old_rd_size
    assert align(PAGE + old_rd_size) == DTB_OFF

    # original pieces
    header = bytearray(base[:PAGE])
    dtb_blob = base[DTB_OFF:TAB_OFF]
    table = bytearray(base[TAB_OFF:BC_OFF])
    bc_size = struct.unpack_from('<I', base, 0x84C)[0]
    assert bc_size == 53, bc_size
    bootconfig = base[BC_OFF:BC_OFF + align(bc_size)]
    footer = base[len(base) - FOOTER_LEN:]

    # patch header ramdisk size and table entry size
    struct.pack_into('<I', header, 0x18, len(rd))
    old_tab_rd_size = struct.unpack_from('<I', table, 0)[0]
    assert old_tab_rd_size == old_rd_size, old_tab_rd_size
    struct.pack_into('<I', table, 0, len(rd))

    out = bytearray()
    out += header
    out += rd
    out += b'\0' * (align(len(out)) - len(out))
    new_dtb_off = len(out)
    assert new_dtb_off == align(PAGE + len(rd)), hex(new_dtb_off)
    out += dtb_blob
    out += table
    out += bootconfig
    out += b'\0' * (len(base) - FOOTER_LEN - len(out))
    out += footer
    assert len(out) == len(base), len(out)

    Path(args.out).write_bytes(out)
    print(f'wrote {args.out} ({len(out)} bytes)')
    print(f'  ramdisk: {old_rd_size} -> {len(rd)} bytes')
    print(f'  DTB: {DTB_OFF:#x} -> {new_dtb_off:#x}')
    print(f'  table ramdisk_size patched: {old_tab_rd_size} -> {len(rd)}')
    print('  AVB footer copied verbatim (verified boot must be disabled)')

if __name__ == '__main__':
    main()
