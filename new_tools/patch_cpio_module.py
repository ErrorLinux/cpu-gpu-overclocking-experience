#!/usr/bin/env python3
"""Overwrite one existing cpio entry in-place with a new kernel module.

Keeps the cpio byte layout identical (same entry count/size) so the vendor_boot
DTB stays at its original offset. Pads the new module with zero bytes to the
original entry size.
"""
import struct
import sys
from pathlib import Path

def parse(cpio):
    p = 0
    while p + 110 <= len(cpio):
        if cpio[p:p+6] != b'070701':
            raise SystemExit(f'bad cpio magic at {p:#x}')
        h = cpio[p:p+110].decode('ascii')
        v = [int(h[6+i*8:14+i*8], 16) for i in range(13)]
        filesize, nlen = v[6], v[11]
        name = cpio[p+110:p+110+nlen-1].split(b'\0', 1)[0].decode('utf8', 'replace')
        data = (p + 110 + nlen + 3) & ~3
        nxt = (data + filesize + 3) & ~3
        yield name, data, filesize, p
        if name == 'TRAILER!!!':
            return
        p = nxt

def main():
    cpio_path, target, mod_path, out = sys.argv[1:5]
    cpio = bytearray(Path(cpio_path).read_bytes())
    mod = Path(mod_path).read_bytes()
    found = None
    for name, data, size, hdr in parse(cpio):
        if name == target:
            found = (data, size)
            break
    if not found:
        raise SystemExit(f'entry {target} not found')
    data, size = found
    if len(mod) > size:
        raise SystemExit(f'module {len(mod)} > entry {size}')
    cpio[data:data+size] = mod + b'\0' * (size - len(mod))
    Path(out).write_bytes(cpio)
    print(f'patched {target}: data@{data:#x} size={size}, module={len(mod)}, pad={size-len(mod)}')

if __name__ == '__main__':
    main()
