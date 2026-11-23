#!/usr/bin/env python3
"""Patch one cpio entry inside a legacy-LZ4 ramdisk by recompressing only the
affected block. All other compressed blocks stay byte-identical, so the image
fits the vendor_boot DTB window without recompressing the whole ramdisk."""
import ctypes
import ctypes.util
import struct
import sys
from pathlib import Path

lib = ctypes.CDLL(ctypes.util.find_library('lz4') or 'liblz4.so.1')
lib.LZ4_decompress_safe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
lib.LZ4_decompress_safe.restype = ctypes.c_int
lib.LZ4_compress_default.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
lib.LZ4_compress_default.restype = ctypes.c_int


def parse(rd):
    assert rd[:4] == bytes.fromhex('02214c18'), rd[:4].hex()
    blocks, p = [], 4
    while p + 4 <= len(rd):
        n = struct.unpack_from('<I', rd, p)[0]
        p += 4
        if n == 0:
            return blocks, True
        blocks.append(rd[p:p + n])
        p += n
    return blocks, False


def decompress(block, capacity=64 * 1024 * 1024):
    src = ctypes.create_string_buffer(block)
    dst = ctypes.create_string_buffer(capacity)
    n = lib.LZ4_decompress_safe(src, dst, len(block), capacity)
    if n <= 0:
        raise SystemExit(f'decompress failed: {n}')
    return dst.raw[:n]


def compress(raw):
    # lz4 CLI splits large inputs into 4 MiB blocks => better ratio than one
    # LZ4_compress_default call over the whole 16 MiB block.
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'b.raw').write_bytes(raw)
        subprocess.run(['lz4', '-l', '-9', '-f', str(Path(d, 'b.raw')), str(Path(d, 'b.lz4'))],
                       check=True, capture_output=True)
        blocks, _ = parse(Path(d, 'b.lz4').read_bytes())
        return blocks


def main():
    rd_path, cpio_off, mod_path, out_path = sys.argv[1:5]
    cpio_off = int(cpio_off, 0)
    rd = Path(rd_path).read_bytes()
    mod = Path(mod_path).read_bytes()
    blocks, terminated = parse(rd)

    # find the block containing the cpio entry
    pos = 0
    idx, off = None, None
    for i, b in enumerate(blocks):
        raw = decompress(b)  # decompress once to learn raw size
        if pos <= cpio_off < pos + len(raw):
            idx, off = i, cpio_off - pos
            break
        pos += len(raw)
    if idx is None:
        raise SystemExit('cpio offset outside ramdisk')
    print(f'block {idx}: raw={pos + len(raw)} off={off:#x} module={len(mod)}')
    assert off + len(mod) <= len(raw), 'module crosses block boundary'

    raw = raw[:off] + mod + raw[off + len(mod):]
    blocks[idx:idx + 1] = compress(raw)
    new_rd = rd[:4]
    for b in blocks:
        new_rd += struct.pack('<I', len(b)) + b
    if terminated:
        new_rd += struct.pack('<I', 0)
    Path(out_path).write_bytes(new_rd)
    print(f'wrote {out_path}: {len(rd)} -> {len(new_rd)} bytes')


if __name__ == '__main__':
    main()
