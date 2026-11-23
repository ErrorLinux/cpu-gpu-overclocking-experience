# Bản thử SMC cứng: gọi trực tiếp bộ set index DVFS của SML

**Ảnh dùng:** `new_tools/vendor_boot_hw_smc_v7.img` (104,857,600 bytes)  
**SHA-256:** `700150f7bb931802adb0862e7f1f5122bab254f3daf015ede1195d77c553e157`

> v7: v6 bị lỗi validate `oc_range > 0x3ff` nên `0x280A` bị từ chối (không có
> log DVFS_INIT). v7 tự gọi `0x60B(0, 0x280A, 0)` trong `oc_index` và nới limit.

> **v6 mở clamp:** thử nghiệm trên máy xác nhận SMC DVFS có tác dụng thật
> (index 0 → PMU A75 0.767 GHz), nhưng index 9 bị kẹp về 1.82 GHz tại `0x58fc`
> do bảng min/max runtime `0xB00223D0/D8`. SMC `0x8200060B` → `0x5AD4` ghi
> bảng này; a2 đóng gói 10 bit/cluster (5 bit thấp = max, 5 bit cao = min).
> `oc_range=10250` (0x280A) đặt max=10 cho cả 2 cluster. Cluster mặc định = 1 (A75).

> **v1/v2 đều bootloop.** Nguyên nhân thực sự không phải SMC lúc init, mà là
> **đóng gói ramdisk khác với ảnh đã boot được trước đó**: v1/v2 thay entry
> `sprd_cp_dump.ko`, zero `ntfs3.ko` và nén `lz4 -l -9` (khác level gốc là `-12`).
> **v3 quay lại đúng công thức ảnh `vendor_boot_pll_write.img` đã boot tốt**:
> chỉ thay entry `sprd_cache_print.ko` (module 14,240 B / entry 15,152 B), giữ
> nguyên `ntfs3.ko`, nén `lz4 -l -12`, DTB vẫn ở `0x20B9000`. Module vẫn inert
> lúc boot (không gọi SMC trong `module_init`).

## Điểm mới (khác tất cả bản trước)

Sau khi giải mã bảng dispatch của SML tại `0xB00128B8` và hàm
`dvfs_work_index_set` (`0x4B7C`), xác định:

| SMC | Hàm SML thật | Tác dụng |
|---|---|---|
| `0x82000601` | `0x5784` | `dvfs_cluster_enable` |
| `0x82000602` | `0x5878 → 0x4DB8 → 0x4B7C` | **ghi thanh ghi work-index phần cứng + gọi callback MPLL/DVFS** |
| `0x82000605` | `0x5A14` | `pair_get(cluster,index)` → a1=Hz, a2=uV (KHÔNG phải freq_set) |

Các bản trước gọi `0x82000605` như `freq_set` nên thực tế chỉ đọc bảng,
không đụng phần cứng. Bản này gọi `0x82000602` — đây mới là đường dẫn
`cpufreq` driver dùng để đổi xung thật.

Bảng OPP trong SML (đọc trực tiếp từ image):

* **A75 (cluster 1)** tại payload `0x174E8`: index **9 = 2,210,000 kHz / 1,050,000 uV**
  (0=768M, 1=1040M, 2=1228M, 3=1404M, 4=1536M, 5=1690M, 6=1820M,
  7=1898M, 8=1950M, **9=2210M**).
* **A55 (cluster 0)** tại payload `0x17BB8`: index **7 = 1,898,000 kHz / 1,040,000 uV**
  (index 6 = 1820M).

Module được chèn vào entry `lib/modules/sprd_cp_dump.ko` trong ramdisk
(16,368 bytes, entry 31,824 bytes), vẫn nằm trong `modules.load`, nên tự load
lúc boot. Entry `ntfs3.ko` được zero để compressed ramdisk vừa khung DTB
`0x20B9000` (không ảnh hưởng máy — NTFS không dùng trên Android).

## Flash (tự bạn chạy)

```bash
cd /home/hoang/Downloads/oc_gpu
fastboot flash vendor_boot new_tools/vendor_boot_hw_smc_v7.img
fastboot reboot
```

Bootloader phải mở, verified boot phải tắt. Rollback:
`fastboot flash vendor_boot new_tools/vendor_boot.img`.

## Sau khi boot

```bash
# v2 không tự dump lúc boot. Kích hoạt dump cặp freq/volt bằng tay:
adb shell su -c 'echo 1 > /sys/module/sprd_cp_dump/parameters/oc_probe'
adb shell su -c 'dmesg | grep sprd_dvfs_hw'

# Tên sysfs lấy theo tên file trong modules.load = sprd_cp_dump:
adb shell su -c 'ls /sys/module/sprd_cp_dump/parameters'

# Đặt A75 lên index 9 = 2.21 GHz (mặc định cluster=1)
adb shell su -c 'echo 9 > /sys/module/sprd_cp_dump/parameters/oc_index'
adb shell su -c 'dmesg | grep "sprd_dvfs_hw: TABLE_UPDATE"'

# Hoặc A55 index 7 = 1.898 GHz (đổi cluster trước):
adb shell su -c 'echo 0 > /sys/module/sprd_cp_dump/parameters/oc_cluster'
adb shell su -c 'echo 7 > /sys/module/sprd_cp_dump/parameters/oc_index'

# Chứng minh bằng PMU — DÙNG pmU_spot.sh, KHÔNG dùng pmu_verify.sh ở bước này:
# pmu_verify.sh đổi scaling_min/max => cpufreq gọi lại SML và ghi đè index vừa đặt.
bash /home/hoang/Downloads/oc_gpu/oc_cpu/pmu_spot.sh

# (pmu_verify.sh vẫn là arbiter cuối cùng khi đã vá SML cố định:)
bash /home/hoang/Downloads/oc_gpu/oc_cpu/pmu_verify.sh
```

Nếu dòng `pair clu1 idx 9` hiện `2210000 / 1050000` mà PMU vẫn 1.82 GHz,
chứng tỏ **hàng MUX của index 9 trong bảng phần cứng vẫn trỏ kênh 4
(1.82 GHz)** — lúc đó mới cần vá đúng 1 dòng MUX trong SML (sẽ dùng kết quả
log này để xác định vị trí chính xác thay vì đoán như các bản trước).
