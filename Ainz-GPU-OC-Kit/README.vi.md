# Ainz GPU OC Kit

**Ép xung GPU thật cho Redmi A5 / POCO C71 (`serenity`, Unisoc UMS9230E / T7250).**

Tác giả: **Ainz** · Giấy phép: MIT · Phiên bản: 1.0.0

Hầu hết hướng dẫn "ép xung GPU" trên máy Unisoc chỉ sửa bảng OPP. Trên
`serenity`, cách đó chỉ đổi **nhãn** tần số mà driver báo, còn GPU vẫn chạy
**850 MHz**. Kit này đổi nguồn xung thật — lập trình lại **GPLL** bằng
`assigned-clocks` / `assigned-clock-rates` trên node GPU — và kiểm tra từng
byte của ảnh `vendor_boot.img` tạo ra.

Kit chỉ **tạo ảnh**, không flash. Bạn tự flash và luôn giữ ảnh stock để quay về.

---

## Kết quả đo trên máy thật

Redmi A5 (`serenity`), vendor_boot Android 17, Mali-G57 MP1:

| Xung GPU | Cách làm | Boot | Độ ổn định |
|---|---|---|---|
| 850 MHz | stock | OK | mốc gốc |
| 1.0 GHz | chỉ sửa OPP | OK | ảo — vẫn 850 MHz |
| **1.1 GHz** | **ép GPLL (kit này)** | **OK** | **ổn định, 0 lỗi GPU, +29%** |
| 1.15 GHz | ép GPLL | OK | rác hình khi tải nặng |
| 1.2 GHz | ép GPLL | OK | rác hình khi tải nặng |
| 1.6 GHz | ép GPLL | treo | `GPU fault 0x4002` |

Trần thực tế của máy là **1.1 GHz**, vì rail GPU bị động cơ DVFS phần cứng
kẹp ở mức thấp. GPLL có thể chạy tới 1.6 GHz nhưng GPU không chạy nổi ở mức
điện áp mà phần cứng cấp.

### Sự thật về điện áp

Trường `voltage` trong `operating-points` / `sprd,dvfs-lists` chỉ có tính
**tham khảo** trên nền tảng này. Rail DCDC_GPU do engine **topdvfs** trên chip
điều khiển, không theo giá trị OPP trong DT:

| Mức DVFS GPU | `vddgpu` đo được |
|---|---|
| 384–614.4 MHz | ~750 mV |
| 768 MHz | ~781 mV |
| 1.1 GHz (GPLL) | ~912 mV |

Ghi thẳng qua debugfs vào `DCDC_GPU/voltage` cũng bị ghi đè ngay. Vì vậy:

- Nâng OPP lên 1200 mV **không** nâng rail và không làm 1.6 GHz ổn định.
- `--mali-supply` nối `DCDC_GPU` vào đường regulator của Mali kbase. kbase có
  gọi `regulator_set_voltage()` thật, nhưng topdvfs vẫn thắng. Đây là biến
  thể để thử nghiệm, không phải cách mở khóa điện áp.
- Muốn có 1.2 V thật phải vô hiệu hóa/tái lập trình topdvfs (các bit
  tune-enable ở `0x150`). Kit này không làm việc đó.

Chi tiết: [`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md) và
[`docs/TECHNICAL.md`](docs/TECHNICAL.md).

---

## Yêu cầu

- Đúng máy Redmi A5 / POCO C71 (`serenity`, UMS9230E / T7250).
- `vendor_boot.img` **stock** của firmware đang chạy (100 MiB / 104.857.600
  byte, FDT tại `0x2482040`).
- Python 3.8+. Không cần thư viện ngoài.
- Có đường quay về: ảnh `vendor_boot.img` stock và cách flash lại.

Kit không kèm ảnh stock hay ảnh dựng sẵn. Hãy lấy `vendor_boot.img` từ gói
firmware, hoặc dump từ máy trước khi sửa.

---

## Bắt đầu nhanh

```bash
# 1. Xem thông tin ảnh stock (không sửa gì)
python3 oc.py verify vendor_boot.img

# 2. Tạo bản 1.1 GHz đã chứng minh ổn định
python3 oc.py build --stock vendor_boot.img --freq-mhz 1100 --volt-mv 1000

# 3. Kiểm tra ảnh tạo ra so với stock
python3 oc.py verify vendor_boot_oc_1100mhz_1000mv.img --stock vendor_boot.img
```

`build` in SHA-256 và dòng `verify: PASS`. Bản 1.1 GHz tái tạo giống từng byte:

```
cf0735a64f42cf8b7c5b56e614df7f0c57ca6b4fb68e091e48382509451a5277
```

Tự flash:

```bash
adb reboot fastboot
fastboot flash vendor_boot vendor_boot_oc_1100mhz_1000mv.img
fastboot reboot
```

Quay về:

```bash
fastboot flash vendor_boot vendor_boot.img
```

> Offset FDT, các trường trong wrapper SPRD và `dtb_size` ở boot header được
> sửa đồng bộ. Flash ảnh sửa dở có thể làm máy không boot. Luôn chạy `verify`
> trước khi flash.

---

## Tham chiếu CLI

```
python3 oc.py --version
python3 oc.py build --stock vendor_boot.img --freq-mhz 1100 --volt-mv 1000
python3 oc.py verify vendor_boot_oc_1100mhz_1000mv.img --stock vendor_boot.img
```

### `build`

| Tùy chọn | Ý nghĩa |
|---|---|
| `--stock PATH` | `vendor_boot.img` stock (mặc định `vendor_boot.img`). Phải có OPP top 850 MHz. |
| `--out PATH` | Tên ảnh ra. Mặc định `vendor_boot_oc_<freq>mhz_<volt>mv[_mali].img`. |
| `--freq-mhz N` | Tần số OPP top (MHz). Cũng là tốc độ GPLL nếu không có `--gpll-mhz`. |
| `--gpll-mhz N` | Tốc độ GPLL (MHz), mặc định bằng `--freq-mhz`. |
| `--volt-mv N` | Điện áp OPP top (mV), mặc định 800. Chỉ là thông tin trên máy này. |
| `--mali-supply` | Thêm `mali-supply = <&DCDC_GPU>` (thử nghiệm). |
| `--i-know-the-risks` | Bắt buộc khi >1200 MHz hoặc >1000 mV. |

Tool từ chối đầu vào không phải stock sạch: OPP top phải là 850 MHz @ 800 mV,
cell DVFS top phải là cell GPLL `0x08`, và ảnh chưa có
`assigned-clock-rates` / `mali-supply`.

### `verify`

In node GPU (phandle, bảng OPP, mức DVFS, tốc độ GPLL) và kiểm tra:

- kích thước ảnh 104.857.600 byte;
- magic FDT tại `0x2482040`;
- boot header `0x834` = 64 + kích thước FDT;
- wrapper `+0x04` = 64 + kích thước FDT;
- wrapper `+0x20` = kích thước FDT;
- với `--stock`: cùng độ dài file, các byte ngoài FDT không đổi, vùng sau FDT
  không đổi.

Mã thoát `0` = PASS, `1` = FAIL.

---

## Cơ chế (bản ngắn)

GPU có 5 mức DVFS. Mức 0–3 dùng PLL cố định (384 / 512 / 614.4 / 768 MHz).
Mức 4 là **GPLL**, và trên firmware stock không có ai gọi `clk_set_rate()` cho
nó, nên nó đứng ở 850 MHz. Sửa bảng OPP chỉ đổi nhãn của mức 4.

Kit thêm vào node GPU:

```dts
assigned-clocks      = <&pll1 0x1d>;   /* GPLL (phandle 0x24, cell 0x1d) */
assigned-clock-rates = <1100000000>;    /* 1.1 GHz */
```

`of_clk_set_defaults()` áp dụng cấu hình này trước khi driver GPU probe, nên
GPLL được lập trình một lần và giữ nguyên. Bảng OPP cũng được cập nhật để
`devfreq` hiển thị đúng tần số, nhưng xung thật là GPLL.

GPLL chỉ phục vụ GPU trên SoC này, nên không ảnh hưởng block khác. Nếu lập
trình PLL thất bại, GPU quay về 850 MHz; máy không bị brick.

Chi tiết: [`docs/TECHNICAL.md`](docs/TECHNICAL.md).

---

## An toàn

- Chỉ mức **≤ 1.1 GHz** đã được kiểm chứng trên máy.
- Cổng an toàn chặn >1200 MHz hoặc >1000 mV nếu không có
  `--i-know-the-risks`. Đây chỉ là rào chắn, không phải bảo đảm.
- 1.15/1.2 GHz bị rác hình khi tải; 1.6 GHz treo GPU lúc boot.
- Bản `--mali-supply` boot được ở 1.1 GHz nhưng **không** nâng rail. Đừng dùng
  nó để biện minh cho xung cao hơn.
- Ép xung có thể treo boot, mất dữ liệu hoặc hỏng phần cứng. Giữ ảnh stock và
  biết cách vào fastboot.

Đọc [`docs/SAFETY.md`](docs/SAFETY.md) trước khi flash.

---

## Cấu trúc

```
Ainz-GPU-OC-Kit/
├── oc.py                 # CLI build/verify
├── README.md             # bản tiếng Anh
├── README.vi.md          # bản tiếng Việt
├── CHANGELOG.md
├── AUTHORS
├── LICENSE
└── docs/
    ├── TECHNICAL.md      # layout FDT, GPLL, vì sao sửa OPP là ảo
    ├── MEASUREMENTS.md   # số đo trên máy
    └── SAFETY.md         # rủi ro, giới hạn, quay về
```

## Ghi công

- **Ainz** — tác giả và người bảo trì: điều tra, công cụ, thử nghiệm trên máy.
- Hành vi DVFS GPU của Unisoc được xác nhận bằng cách disassemble các module
  `gpu_pm_ums9230.ko` và `mali_kbase_ums9230.ko` có trên máy, cùng với việc
  đọc trực tiếp thanh ghi GPLL.

## Giấy phép

MIT — xem [`LICENSE`](LICENSE). Copyright (c) 2026 Ainz.

Dự án không liên kết với Xiaomi, Redmi, POCO hay Unisoc. Flash ảnh sửa đổi sẽ
mất bảo hành và do bạn tự chịu rủi ro.
