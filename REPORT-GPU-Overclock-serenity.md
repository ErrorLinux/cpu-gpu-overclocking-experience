# Báo cáo: Ép xung GPU **thật** trên Redmi A5 / POCO C71 (Unisoc T7250)

> Máy: **Redmi A5 / POCO C71** — codename `serenity` — SoC **Unisoc UMS9230E (T7250)** — GPU **Mali-G57 MP1** tại `gpu@23100000`
> Kernel: `6.18.21-android17-5-gf8ee977e062b-ab16100350-4k 4k` (Lineage-based, Android 17)
> Build fingerprint: `Redmi/serenity_global/serenity:17/CP2A.260605.016/A17.0.4.0.XGWMIXM:user/release-keys`
> Ngày phân tích: 2026-11-18 (vòng lặp flash/test trên cùng 1 máy)

---

## Abstract (English)

The Mali-G57 MP1 in the Unisoc T7250 is clocked by **GPLL**, a PLL whose rate is **never programmed** by the GPU driver on devices whose GPU device tree has a 5-entry `sprd,dvfs-lists` (5 DVFS levels). Editing the OPP table (the change described in public guides) only re-labels the requested level — the hardware DVFS mux selects the fixed-rate PLL behind the level (384 / 512 / 614.4 / 768 MHz PLLs, level 4 = GPLL = **850 MHz**). The recorded "1.5 GHz / 2.2 GHz" builds were therefore **always running at 850 MHz**. A real overclock requires reprogramming GPLL itself; this report shows that adding `assigned-clocks`/`assigned-clock-rates` to the GPU node in `vendor_boot.img` forces GPLL to 1.1 GHz at `kbase` probe time and is the only DVB-visible change needed. Result: measured GPLL = **1100.00 MHz** (nint=42, kint=2,581,110), zero GPU faults, stable boot. The GPU voltage rail (`vddgpu`) is **locked at ~912.5 mV** by the hardware DVFS engine regardless of the OPP voltage request, which limits the practical overclock to **+29% (1.1 GHz)**; 1.15 / 1.2 GHz produce screen artifacts and 1.6 GHz hangs the GPU at boot (GPU fault 0x4002). This report documents the investigation, the applied fix, the stability results and rollback instructions.

---

## 1. Tóm tắt kết quả

| Hạng mục | Kết quả |
|---|---|
| Stock (mặc định) | GPU chạy **850 MHz**, bảng DVFS chỉ là "nhãn" |
| Bản 1.0 / 1.5 / 2.2 GHz (chỉ sửa bảng OPP) | Vẫn **850 MHz**, chỉ báo sai số |
| Fix thật | `assigned-clocks` + `assigned-clock-rates = <1100000000>` trên node GPU |
| Kết quả đo (build 1.1 GHz) | GPLL = **1100.00 MHz**, GPU fault **0**, máy boot OK |
| Trần ổn định thực tế | **1.1 GHz** (điện áp vddgpu bị lock ~912,5 mV) |
| 1.15 / 1.2 GHz | **Rác hình** (artifacts) khi GPU tải nặng |
| 1.6 GHz | Hang GPU ngay boot (`GPU fault 0x4002`), màn đen, backlight vẫn sáng |
| Điện áp GPU | Request 850 mV → 921 mV; request 1.0 V → 912,5 mV → **bị DVFS engine clamp** |
| Rollback | Flash `vendor_boot.img` (stock) hoặc `vendor_boot_oc_1100mhz_1000mv.img` |

---

## 2. Bối cảnh & vấn đề ban đầu

Có sẵn hướng dẫn ép xung GPU Unisoc phổ thông ([GUIDE-Overclock-Unisoc[ID] (2).txt](file:///home/hoang/Downloads/oc_gpu/GUIDE-Overclock-Unisoc[ID]%20(2).txt), by @KurumiDev2) khuyến nghị chỉ sửa `operating-points` và `sprd,dvfs-lists` trong DTB. Khi áp dụng:

- `sysfs/devfreq/23100000.gpu/available_frequencies` đổi đúng theo bảng (ví dụ `1.5 GHz` đứng đầu),
- `cur_freq` báo 1.5 GHz khi max_freq = 1.5 GHz,
- nhưng **GPU không chạy nhanh hơn**.

Yêu cầu: tìm ra lý do và ép xung **thật**, giữ `vendor_boot.img` chỉ khác đúng các byte cần thiết.

---

## 3. Điều tra trên máy thật (kỹ lưỡng, nhiều bước)

### 3.1 Đọc thanh ghi PLL GPLL trực tiếp (cơ chế debugfs regmap)

Syscon `0x645a0000` (thư mục `dummy-syscon@0x00000000645a0000/registers` trong debugfs), GPLL ở offset `0x48/0x4c/0x50`:

```
0000: 0004077b
...
0048: 000007ab     (sau flash 1.1 GHz: 000007af)
004c: 10589d8a     (sau flash 1.1 GHz: 15276276)
0050: 00000005
```

Giải mã (công thức trong `f_pll` của `ums9230-clk.c`, refin = 26 MHz, div_s=1, SDM on):

```
nint = (reg >> 23) & 0x7f
kint = reg & 0x7fffff
f    = 26e6 * (nint + kint / 2**23)
```

- Trước flash: nint=32, kint=5.807.498 → **850.00 MHz** (đo nhiều lần, cả lúc tải GPU, không đổi).
- Sau flash: nint=42, kint=2.581.110 → **1100.00 MHz** chính xác.
- Thanh ghi `0x48` đổi từ `0x7ab` → `0x7af` (ibias bị PLL driver đổi khi set_rate), `0x50` không đổi (POSTDIV, LOCK, ...).

### 3.2 Phân tích driver GPU power/DVFS (`gpu_pm_ums9230.ko`, live module trên máy)

Disassembly (`mali_clock_on`, `platform_set_freq_volt`, `sprd_mali_platform_init`):

- `sprd_mali_platform_init` đọc `sprd,dvfs-lists` → tạo bảng mức, ghi `phandle 0x24` (`gc-pll`) của từng level ra mảng clock, count = 5.
- `mali_clock_on` — nếu số mức = 1 / 2 thì mới đi nhánh có `clk_set_rate` (gọi `clk_set_rate(gpll, freq*1000)`). Với **5 mức** (máy này), nó nhảy `0xbe8`: chỉ gọi `regmap_update_bits` (bit DVFS-enable, ghi voltage) + `maliQosConfig`, **hoàn toàn không đụng PLL**.
- `platform_set_freq_volt`: binary search tần số → ghi **điện áp** (regmap tại `ctx+0x78`) + lưu index mức ở `ctx+0xc` + gọi tracepoint `clock_set_rate` (chuỗi debug `unisoc-gpu-freq`) — **không gọi `clk_set_rate`, không gọi `clk_set_parent`**.
- Module không tham chiếu `clk_set_parent` / `clk_set_rate` ở nhánh 5 mức. Module `mali_kbase_ums9230.ko` cũng không có symbol `clk_set_rate`.
- Tracepoint `clk_set_rate` đo được: **0 lần gọi** trong toàn bộ boot + tải GPU.

Kết luận điều tra: **không có code nào trong driver GPU set rate cho GPLL.** Bảng OPP chỉ là mảng tham khảo để driver tính "level index" và điện áp.

### 3.3 Cây clock

`gpu@23100000` (live DTB, `/proc/device-tree`):

```
clocks = <0x34 0x09   0x4d 0x00   0x4d 0x02   0x4d 0x04   0x24 0x02   0x24 0x08   0x24 0x16   0x24 0x01   0x24 0x1d>
         ext-mm  clk0        clk2        clk4        [4]384   [5]512     [6]614.4   [7]768     [8]GPLL
```

Phần cứng DVFS ("topdvfs", `topdvfsctrl@64014000` → `dcdc_mm/gpu-sys`) chọn **mux** giữa 5 PLL nguồn cho level 0..4:

| Level | OPP | Nguồn | Tần số thật |
|---|---|---|---|
| 0 | 384 MHz | `twpll-384m` | 384 MHz |
| 1 | 512 MHz | `twpll-512m` | 512 MHz |
| 2 | 614.4 MHz | `lpll-614m4` | 614.4 MHz |
| 3 | 768 MHz | `twpll-768m` | 768 MHz |
| 4 | *top OPP* | **GPLL** | **GPLL rate** |

- `gpu-core-clk` (CCF mux) luôn đọc `twpll-384m`, không được driver nào lập trình — clock chính được chọn ở **phần cứng DVFS** (top-DVFS APB `0x23014000`), CCF chỉ enable/disable nguồn và cache sai (mux=1, 384 mHz).
- GPLL: **consumer duy nhất là GPU** (`<0x24 0x1d>` chỉ xuất hiện 1 lần trong DTB) → thay đổi nó không ảnh hưởng th.khác.
- GPLL ftable: max **1.6 GHz** (ibias ≤ 6).

`gpu_freq_time` (`/sys/kernel/debug/mali0/gpu_freq_time`) xác nhận DVFS **có chuyển mức thật** — trên build 1.5 GHz, bucket `1500000000` busy **61,4 giây**; các mức khác busy hàng trăm ms. Tức máy vào "level 4" nhưng PLL đứng ở 850 → 850 MHz thật.

### 3.4 Điện áp GPU bị **lock** (không tăng được bằng DTB)

| OPP request | `vddgpu` đo thực |
|---|---|
| 850 mV (build 1000/1500 ch.) | 921 mV |
| 1000 mV (build 1500/1600/2200) | 912,5 mV |

Regulator `vddgpu` (max 1596 mV theo regulator_summary) nhưng **rail do topdvfs dcdc engine điều khiển** — bảng điện áp nằm trong firmware DVFS chip (dcdc_mm `gpu-sys` `<0x150 0x01 0x01>`), **không phải trong DTB OPP**; driver ghi mỗi "level index", không phải µV. Không có cách nào trong DTB raise GPU voltage cho máy này.

---

## 4. Fix thật: ép GPLL trước khi GPU dùng

### 4.1 Cơ chế

Thêm vào node GPU:

```
assigned-clocks       = <&pll1 0x1d>;    /* GPLL (phandle 0x24, CLK_GPLL = 0x1d) */
assigned-clock-rates  = <1100000000>;     /* 1.1 GHz */
```

Driver core gọi `of_clk_set_defaults()` **trước khi probe** node GPU. Kbase (`mali_kbase_ums9230.ko`) là module từ `/vendor_dlkm` → bind **sau khi** tất cả clock provider built-in đã chạy → `of_clk_get_from_provider` luôn OK → `clk_set_rate(gpll, 1100000000)` → PLL được lập trình lại, lock, giữ nguyên 1.1 GHz sau đó (không gì set lại GPLL).

- Nếu PLL set_rate thất bại: chỉ `pr_err`, GPU vẫn boot ở 850 MHz (không dead mày).
- Nếu provider chưa sẵn sàng: `clk_set_rate` bị bỏ qua / probe lỗi — không áp dụng cho máy này vì PLL built-in.

### 4.2 Kiểm chứng sau flash (`vendor_boot_oc_1100mhz_1000mv.img`)

| Kiểm tra | Kết quả |
|---|---|
| GPLL regs 0x48/0x4c | `0x7af` / `0x15276276` → **1100.00 MHz** khớp 100% với `assigned-clock-rates` |
| `available_frequencies` | `1100000000 768000000 614400000 512000000 384000000` |
| `governor` / `cur_freq` | `performance` / `1100000000` |
| `gpu_freq_time` | bucket `1100000000`: **busy 3372 ms**, idle 60,2 s — mức 4 dùng thật |
| `dmesg` GPU | **0** fault / soft-reset trong boot |
| `sys.boot_completed` | `1`, launcher lên bình thường |

Mức 4 (GPLL) giờ là **1.1 GHz thật**. Các mức 0–3 giữ nguyên 384/512/614.4/768 MHz.

### 4.3 DTB sửa thế nào

`vendor_boot.img` (v4) layout: header (0x0..0x2100) → vendor ramdisk → **wrapper SPRD 64 B** (0x2482000) → **FDT** (`0xd00d feed`, 146,594 B) → padding (798 B) → ramdisk table/bootconfig. Offsets (máy này):

```
FDT_OFF         = 38281280   (0x2482080)
WRAPPER         = 38281216   (magic 0xd7b7ab1e)
DTB_SECTION     = 146,658 B  (dtb_size ở boot header 0x834; wrapper +4 = container size; wrapper +0x20 = FDT size)
FDT totalsize   = 146,594 B  (struct 130,664 B + strings 15,874 B)
```

Thay đổi tối thiểu (tổng cộng DTB lớn 57 byte, vẫn nằm trong padding trang):

1. `operating-points` + `sprd,dvfs-lists`: top entry → `1100000 kHz @ 1000000 µV` (clock cell `0x08` = GPLL giữ nguyên).
2. Node GPU: thêm 2 property `assigned-clocks` / `assigned-clock-rates`, thêm 1 string `assigned-clock-rates`, shifts struct/string blocks, cập nhật `size_dt_struct` / `off_dt_strings` / `size_dt_strings` / `totalsize` + wrapper (+0x04, +0x20) + boot header `dtb_size` (0x834).
3. Bytes ngoài DTB **byte-identical**, vùng sau DTB byte-identical.

---

## 5. Thử nghiệm độ ổn định (cùng 1 máy, rail ~912,5 mV)

| GPLL | Boot | Hình ảnh / GPU fault | Đánh giá |
|---|---|---|---|
| 850 MHz (stock) | OK | OK | baseline |
| 1.0 GHz (chỉ sửa bảng) | OK | OK (vẫn 850 MHz thật) | label ảo |
| 1.1 GHz (GPLL ép) | OK | OK, 0 fault, launcher/game chạy | **ổn định nhất, dùng chính thức** |
| 1.15 GHz | OK | **rác hình** dưới tải | quá ngưỡng |
| 1.2 GHz | OK | **rác hình** dưới tải | quá ngưỡng |
| 1.5 GHz | OK | OK nhưng vẫn 850 MHz (label ảo) | không OC thật |
| 1.6 GHz | **Treo** | `t6xx: GPU fault 0x4002`, job hard-stop, soft-reset lặp, boot không hoàn tất, màn đen backlight sáng, launcher chết | quá ngưỡng, không flash |
| 2.2 GHz | — | không thử (vượt GPLL max 1.6 GHz) | không dùng |

**Kết luận: trần ép xung an toàn của máy này ≈ 1.1 GHz** (ở ~912,5 mV, +29% vs stock). Muốn cao hơn phải có điện áp GPU cao hơn — OV không có sẵn trên máy này.

---

## 6. Danh sách file + SHA-256

| File | SHA-256 | Ghi chú |
|---|---|---|
| `vendor_boot.img` | `091521617e189e94a1d423a77010b4bc207949e96625b980ac6b58f3e01640ee` | stock, 850 MHz |
| `vendor_boot_oc_1000mhz_850mv.img` | `2eef2c2b643bf7ae2347dd8c7100553b59e9a12aaa39adfec0032abe17445d89` | label ảo 1.0 GHz |
| `vendor_boot_oc_1500mhz_1000mv.img` | `2e5f382399247a53e540e4bfbb4a79863b994dda9fe190bd50084ed4fb556e89` | label ảo 1.5 GHz |
| `vendor_boot_oc_2200mhz_1200mv.img` | `de291b541e62414fa10f1f0f7a919ca86ebe6e1e7827c464be96b1f0f76d9254` | label ảo 2.2 GHz |
| `vendor_boot_oc_1600mhz_1000mv.img` | `dd15d4256e7bb9c74dc23e6a617d4f508d1a6126b6bdcfa6bcfdf3fc8dc99ef2` | GPLL 1.6 GHz — boot fail |
| `vendor_boot_oc_1200mhz_1000mv.img` | `57279c8c1db01b8cb31496a248bb2b66ac652c09778bc521d7b9d5cce53929d5` | GPLL 1.2 GHz — rác hình |
| `vendor_boot_oc_1150mhz_1000mv.img` | `245dc6771388a2c21a3afe81fbdd2088e7ed832db19ed78aa0e32898295016b7` | GPLL 1.15 GHz — rác hình |
| **`vendor_boot_oc_1100mhz_1000mv.img`** | **`cf0735a64f42cf8b7c5b56e614df7f0c57ca6b4fb68e091e48382509451a5277`** | **GPLL 1.1 GHz — OK, dùng bản này** |

---

## 7. Rollback (flash qua fastboot — bạn tự flash, tôi không flash)

```bash
adb reboot fastboot
fastboot flash vendor_boot vendor_boot.img   # về stock 850 MHz
# hoặc
fastboot flash vendor_boot vendor_boot_oc_1100mhz_1000mv.img
fastboot reboot
```

Nếu máy treo boot / màn đen: boot vào fastboot → flash lại `vendor_boot.img` gốc → reboot. **Không flash cùng lúc nhiều file**, **không dùng các bản 1.15/1.2** trừ khi bạn chấp nhận rác hình tạm thời (máy vẫn boot, chỉ hiển thị lỗi).

---

## 8. Những gì **không** làm được trên máy này (và cách làm ở máy khác)

1. **Không tăng điện áp GPU** từ DTB/userspace — rail do DVFS engine firmware quyết định. Cách duy nhất: chọn tần số phù hợp với rail (1.1 GHz).
2. **Không thể** ép cao hơn 1.6 GHz — GPLL ftable max = 1.6 GHz (và máy này rác hình ở 1.15+).
3. Muốn "thật sự" ép xung mà **không** sửa PLL: không có — driver không set_rate bất cứ thứ gì (bằng chứng ở §3.2).
4. kprobes không hoạt động trên kernel 6.18 của máy này (kprobe_events được nhận nhưng hits = 0); `clk_summary`/`clk_rate` **treo** khi đọc (kernel crash trong vài trường hợp) — tránh.

---

## 9. Kết luận

Máy Redmi A5 / POCO C71 (`serenity`, UMS9230E, Mali-G57 MP1) khi gắn driver GPU 5 mức:

- Bảng DVFS trong DTB **không phản ánh tần số thật** — PLL nguồn cho mức 4 (GPLL) không bao giờ được driver lập trình; mọi bản "OC" kiểu chỉnh bảng đều chạy ở 850 MHz.
- Ép xung thật = ép **GPLL** qua `assigned-clock-rates` trên node GPU ở lần bind của kbase.
- Build 1.1 GHz (file `vendor_boot_oc_1100mhz_1000mv.img`) đã kiểm chứng ổn định — 0 GPU fault, boot hoàn tất, đo được GPLL = 1100.00 MHz.

---

## Appendix A — Giải mã thanh ghi GPLL (python3)

```python
regs = open('/sys/kernel/debug/regmap/dummy-syscon@0x00000000645a0000/registers').read().splitlines()
r48, r4c, r50 = (int(regs[i].split(':')[1], 16) for i in (18, 19, 20))
nint = (r4c >> 23) & 0x7f
kint = r4c & 0x7fffff
print("GPLL = %.2f MHz" % (26 * (nint + kint / 2**23)))
```

## Appendix B — Vị trí / giá trị quan trọng (máy này)

```
vendor_boot.img       size 104,857,600 B, header v4 (dtb_size @ 0x834 = 146,658)
wrapper               @ 0x2482000, magic 0xd7b7ab1e, container size @ +0x04, FDT size @ +0x20
FDT                   @ 0x2482080, totalsize 146,594 (magic 0xd00d feed)
gpu node              /soc/mm/gpu@23100000   (phandle 0xbe)
gpu-pll               &pll1 (gc-pll) = phandle 0x24, CLK_GPLL = 0x1d, syscon 0x645a0000
gpucpu                gpu-core-clk @ 0x23000004 bits[6:4] (CCF, không được DVFS dùng)
DVFS APB              0x23014000 (sprd,gpu-dvfs-apb-syscon, phandle 0x4a) — ghi level index
topdvfs               topdvfsctrl@64014000 (phandle 0x48), dcdc_mm/gpu-sys: tune <0x150 0x01 0x01>
OPP stock top         operating-points/dvfs-lists top = 850 MHz (0xcf850 kHz, 0xc3500 µV)
vddgpu                ~912,500 µV (locked), regulator max 1,596 mV (không dùng được)
```

## Appendix C — Lịch sử thử nghiệm (timeline)

1. Flash `vendor_boot_oc_1000mhz_850mv.img` → devfreq báo 1.0 GHz; GPLL vẫn 850; vddgpu 921 mV.
2. Flash `vendor_boot_oc_1500mhz_1000mv.img` → devfreq 1.5 GHz; GPLL vẫn 850; `gpu_freq_time` level 1500000000 busy 61,4 s; 0 fault.
3. Phân tích driver → tìm ra root cause (PLL never programmed).
4. Build `vendor_boot_oc_1600mhz_1000mv.img` (GPLL ép) → GPU fault 0x4002, boot fail, backlight sáng, màn đen.
5. Build `vendor_boot_oc_1100mhz_1000mv.img` → **GPLL 1100.00 MHz đo được**, 0 fault, máy ổn định.
6. Build `vendor_boot_oc_1200mhz_1000mv.img` → rác hình.
7. Build `vendor_boot_oc_1150mhz_1000mv.img` → rác hình.
8. Kết luận: **1.1 GHz là trần thực tế**.
