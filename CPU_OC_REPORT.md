# Báo cáo: Các cách ép xung CPU cho Redmi A5 / POCO C71 (serenity, UMS9230E / T7250)

Ngày: 2026-11-21  
Ngôn ngữ: Tiếng Việt  
Phạm vi: CPU overclocking, không bao gồm GPU OC (đã giải quyết riêng).  
An toàn: Không chạy `fastboot` hay `spd_dump`. Người dùng tự flash.

## 1. Thông tin thiết bị

- SoC: Unisoc UMS9230E / T7250 (12 nm, 2× Cortex-A75 + 6× Cortex-A55).
- Tần số stock:
  - Cluster 0 (A55): 8 OPP, max 1.612 GHz @ 896.875 mV.
  - Cluster 1 (A75): 7 OPP, max 1.8176 GHz @ 909.375 mV.
- Kernel: 5.15 (A17), driver `sprd-cpufreq-v2.ko` + SML (ATF BL31).
- DVFS table nằm trong SML (`sml-sign.bin`), không trong DTB.

## 2. Tóm tắt xếp hạng

| Hạng | Phương pháp | Khả thi | Rủi ro | Rollback |
|------|-------------|---------|--------|----------|
| 1 | SML hidden tables (bin/version cao) | Trung bình-cao (cần test) | Trung bình | Reboot |
| 2 | Direct SMC calls (bin/version override) | Thấp-trung bình (cần module) | Trung bình | Reboot |
| 3 | Voltage margin via `sprdboot.dvfs_set` / DTB | Cao (đã có code) | Thấp | Reboot |
| 4 | CPU boost via `sprd,cpufreq-boost` | Trung bình | Thấp | Reboot |
| 5 | Undervolt (margin âm) | Cao | Thấp | Reboot |
| 6 | Direct register write (0x64018000) | Thấp | Cao | BDL |
| 7 | SML table patch (magic64) | Đã chết (brick) | Rất cao | BDL |
| 8 | `dvfs_table_update` temp trick | Thấp | Thấp | Reboot |

## 3. Chi tiết từng phương pháp

### 3.1 SML hidden tables (bin/version cao) — Khả thi cao nhất

- **Mô tả**: SML chứa nhiều bảng OPP cho các bin/version khác nhau. Quét SML tìm thấy:
  - Cluster 0 (A55): bảng 10 OPP max **1.82 GHz** (vs stock 1.612 GHz).
  - Cluster 1 (A75): bảng 7 OPP max **2.21 GHz** (vs stock 1.8176 GHz).
- **Cách chọn bảng**: key = `(temp, bin, cluster, version)`. Stock device dùng bin/version từ efuse. Nếu ép bin/version cao, có thể chọn bảng 2.21 GHz.
- **Cách thực hiện**:
  1. Viết kernel module gọi SMC `dvfs_bin_set` (0x0609) và `dvfs_version_set` (0x060a) với bin/version cao.
  2. Gọi `dvfs_init` (0x060b) với packed args.
  3. Kiểm tra OPP table qua `pair_get` (0x0607).
- **Rủi ro**: SML có thể từ chối SMC unknown (0x0609/0x060a chưa được kernel 5.15 expose, nhưng SML có thể hỗ trợ). Nếu bin/version không hợp lệ, SML có thể dùng bảng mặc định. Không brick vĩnh viễn (chỉ reboot).
- **Rollback**: Reboot về stock (SML không bị sửa).

### 3.2 Direct SMC calls (bin/version override) — Thử nghiệm

- **Mô tả**: Tương tự 3.1, nhưng dùng SMC trực tiếp thay vì relying on kernel driver.
- **Cách thực hiện**: Module gọi `arm_smccc_smc(0x82000609, cluster, bin, ...)` và `0x8200060a` cho version. Sau đó `dvfs_init`.
- **Rủi ro**: Nếu SML không hỗ trợ, trả về error. Không brick.
- **Rollback**: Reboot.

### 3.3 Voltage margin via `sprdboot.dvfs_set` / DTB — Khả thi cao

- **Mô tả**: `sprdboot.dvfs_set=0x%x,%x,%x` truyền 3 giá trị packed vào `dvfs_init`:
  - Byte 0: temp per cluster (8 bits)
  - Byte 1-2: min/max index per cluster (5 bits each)
  - Byte 3: margin per cluster (10 bits, +200 bias)
- **Cách thực hiện**:
  1. Thêm `sprd,voltage-margin = <...>` vào DTB (`apcpu-dvfs` node).
  2. Hoặc dùng bootarg `sprdboot.dvfs_set=0x<temp>,<index>,<margin>`.
- **Rủi ro**: Thấp. Margin âm = undervolt (an toàn). Margin dương = overvolt (cần cẩn trọng).
- **Rollback**: Reboot.

### 3.4 CPU boost via `sprd,cpufreq-boost` — Trung bình

- **Mô tả**: DTS có `sprd,cpufreq-boost` trên cả 2 cluster. Driver hỗ trợ boost OPP tạm thời.
- **Cách thực hiện**: Sửa DTB để tăng boost duration hoặc thêm boost OPP.
- **Rủi ro**: Thấp. Boost chỉ áp dụng trong thời gian ngắn sau boot.
- **Rollback**: Reboot.

### 3.5 Undervolt (margin âm) — Khả thi cao

- **Mô tả**: Giảm voltage margin để giảm nhiệt, cho phép tần số cao hơn trong thời gian dài.
- **Cách thực hiện**: `sprdboot.dvfs_set=0x0,0x0,0x<margin_neg>` hoặc DTB `sprd,voltage-margin`.
- **Rủi ro**: Thấp. Undervolt an toàn hơn overvolt.
- **Rollback**: Reboot.

### 3.6 Direct register write (0x64018000) — Rủi ro cao

- **Mô tả**: 4.14 dùng `sprd-hwdvfs-normal` với block `cpudvfs-dev@64018000`. 5.15 SML có thể vẫn sở hữu block này.
- **Cách thực hiện**: Module ioremap `0x64018000` và ghi register.
- **Rủi ro**: Cao. SML có thể conflict, crash.
- **Rollback**: BDL.

### 3.7 SML table patch (magic64) — Đã chết

- **Mô tả**: Thử patch SML container với payload không đổi nhưng magic64. Tất cả modified container đều brick.
- **Rủi ro**: Rất cao. Đã xác nhận brick.
- **Rollback**: BDL + flash stock `sml-sign.bin`.

### 3.8 `dvfs_table_update` temp trick — Thấp

- **Mô tả**: `dvfs_table_update(cluster, temp)` chọn bảng theo nhiệt độ. Có thể thử temp thấp để chọn bảng cao hơn.
- **Rủi ro**: Thấp. Nhưng bảng theo temp thường có max freq thấp hơn, không cao hơn.
- **Rollback**: Reboot.

## 4. Repos và tài liệu tham khảo

| Repo | Mô tả |
|------|-------|
| `TheGammaSqueeze/UnisocBypass` | OC/UV cho UMS512 (T618), DTB-based, voltage ceiling research |
| `TheGammaSqueeze/kernel_ums512_5.4` | Kernel source cho UMS512 |
| `TomKing062/unisoc_chipram_signcheck_exploit` | Sign bypass cho Unisoc SML/uboot |
| `dikeckaan/mu300-linux` | Kernel source với voltage offset cho UMS9620 |
| `XTENSEI/android_unisoc_tuner` | Magisk tuner cho UMS9230 (T7250) |
| `nethgraves/Unisoc_UBL` | Unlock bootloader cho UMS9230 |
| `DiegoPtit/unisoc_tools` | Reverse engineering toolkit cho T606/UMS9230 |
| `ums9230-mainline/linux` | Mainline kernel cho UMS9230 |

## 5. Kết luận và khuyến nghị

1. **Phương pháp khả thi nhất**: SML hidden tables (bin/version cao) + direct SMC calls. Cần test trên device.
2. **Phương pháp an toàn nhất**: Voltage margin via `sprdboot.dvfs_set` hoặc DTB `sprd,voltage-margin`.
3. **Phương pháp đã chết**: SML table patch (magic64) — không thử lại.
4. **Khuyến nghị**: Bắt đầu với voltage margin + undervolt (an toàn), sau đó thử direct SMC bin/version override.

## 6. Rollback chung

- Reboot: nếu method dùng SML/SIP (không sửa SML), reboot là đủ.
- BDL: nếu brick, flash stock `sml-sign.bin` vào `sml_a`/`sml_b`.
- Stock rollback image: `/home/hoang/Downloads/oc_gpu/oc_cpu/serenity_global_images_A17.0.4.0.XGWMIXM_17.0/images/sml-sign.bin`.

---

*Báo cáo này tổng hợp từ phân tích binary SML, driver, và tài liệu cộng đồng. Các phương pháp chưa được test trên device (device offline).*