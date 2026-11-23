# CPU OC qua vendor_boot — bản SMC runtime (UMS9230E / serenity)

## File đầu ra

| File | Mô tả |
|---|---|
| `sprd_cpu_oc.c` | Source module: đọc bảng OPP và gọi SML SMC để đặt xung CPU |
| `sprd_cpu_oc.ko` | Module arm64 đã build (vermagic khớp stock) |
| `.work_oc_ramdisk/new.cpio.lz4` | Ramdisk sau khi nối module + `modules.load` |
| `vendor_boot_cpu_oc_smc.img` | **Ảnh cần flash** (104,857,600 bytes) |

SHA-256 ảnh: `9f193dcf48442e65134076df2dffd0267e98e9d0168aeb0341cd9ee659779707`

## Nguyên lý

Bảng DVFS CPU nằm trong SML (đã ký), không nằm trong DTB, nên sửa DTB chỉ đổi được
điện áp. Ảnh này inject một kernel module vào `vendor_ramdisk`; lúc boot module gọi
trực tiếp SMCCC tới SML (đã giải mã từ `sprd_sip_svc.ko`):

| SMC | Hàm |
|---|---|
| `0x82000607` | `pair_get(cluster, index)` → đọc cặp freq/volt |
| `0x82000606` | `freq_get(cluster)` → đọc xung hiện tại |
| `0x82000605` | `freq_set(cluster, freq_kHz)` → đặt xung |
| `0x82000603` | `step_set(cluster, index)` |
| `0x82000604` | `margin_set(cluster, margin)` |

Mặc định: A55 (cluster 0) = 1,820,000 kHz, A75 (cluster 1) = 2,210,000 kHz.
Có thể đổi bằng module param (sửa `modules.load` hoặc truyền qua `/sys/module/...`):
`oc_a55`, `oc_a75`, `oc_apply_mode` (0 = chỉ đọc, 1 = freq_set, 2 = step_set).

## Build lại (nếu muốn đổi thông số)

```bash
cd /home/hoang/Downloads/oc_gpu/kernel_source
export PATH=/home/hoang/clang-r450784e/bin:$PATH ARCH=arm64 LLVM=1 LLVM_IAS=1 \
       CROSS_COMPILE=aarch64-linux-gnu- BUILD_NUMBER=15212794 \
       KBUILD_BUILD_USER=build-user KBUILD_BUILD_HOST=build-host KBUILD_BUILD_VERSION=1 \
       KBUILD_BUILD_TIMESTAMP="Wed Apr 15 01:39:41 UTC 2026"
make -s -C . M=/home/hoang/Downloads/oc_gpu/new_tools modules
```

Rồi nối module vào cpio, nén lz4 legacy, gọi `repack_vendor_boot_oc.py`.

## Flash (tự bạn chạy)

```bash
fastboot flash vendor_boot /home/hoang/Downloads/oc_gpu/new_tools/vendor_boot_cpu_oc_smc.img
fastboot reboot
```

**Bắt buộc:** bootloader đã mở và **verified boot đã tắt**. AVB footer được giữ
nguyên vẹn nhưng hash không còn đúng (giống các ảnh GPU OC trước đó).

Rollback: `fastboot flash vendor_boot /home/hoang/Downloads/oc_gpu/new_tools/vendor_boot.img`

## Kiểm tra sau boot

```bash
adb shell "su -c 'dmesg | grep sprd_cpu_oc'"
```

Mong đợi các dòng `clu0 oppN = ... kHz / ... uV`, `freq_get before/after`, và
`freq_set(...) => a0=...`. Nếu `freq_get after` vẫn là 1612000 / 1820000 thì SML
đã clamp — lúc đó cần chuyển sang bản SML definitive (flash qua BROM) như đã
research trong `oc_cpu/`.

Đo xung vật lý (chứng minh thực, không phải sysfs ảo):

```bash
bash /home/hoang/Downloads/oc_gpu/oc_cpu/pmu_verify.sh
```

## Cơ chế đóng gói

- Header: chỉ đổi `vendor_ramdisk_size` @ `0x18`.
- `vendor_ramdisk_table`: chỉ đổi field `ramdisk_size` @ `+0`.
- DTB + wrapper `0xd7b7ab1e`, bootconfig, AVB footer: copy nguyên vẹn, DTB dời
  từ `0x20b9000` → `0x20cf000` do ramdisk lớn thêm ~92 KB.
- Module được **nối vào cuối cpio**; kernel initramfs dùng `O_TRUNC` nên entry
  sau ghi đè entry cũ (đã kiểm tra `modules.load` kết thúc bằng `sprd_cpu_oc.ko`).
