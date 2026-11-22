GPU OC TOOLS — Redmi A5 / POCO C71 (serenity, Unisoc UMS9230 / T7250)
=====================================================================

Các file trong thư mục này
--------------------------
  real_oc.py             Tạo vendor_boot.img ép xung GPU THẬT bằng
                         assigned-clock-rates (GPLL). Không sửa kernel/module.
  real_oc_mali.py        Như trên, nhưng thêm mali-supply = <&DCDC_GPU>
                         để driver Mali thực sự gọi regulator_set_voltage().
  verify_vendor_boot.py  Kiểm tra cấu trúc ảnh + in bảng OPP của GPU node.
  dtc                    Device Tree Compiler (dùng để decompile DTB).

Cách dùng
---------
  python3 real_oc.py vendor_boot.img out.img 1600000 1600000000 1200000
  python3 real_oc_mali.py vendor_boot.img out_mali.img 1600000 1600000000 1200000
  python3 verify_vendor_boot.py out.img
  ./dtc -I dtb -O dts -o gpu.dts gpu.dtb

  Tham số: SRC DST FREQ_KHZ GPLL_HZ VOLT_UV
  Ví dụ trên = 1.6 GHz, GPLL 1.6 GHz, OPP request 1.2 V.
  SRC phải là vendor_boot.img STOCK (script assert top OPP 850 MHz/800 mV).

Các ảnh đã tạo
--------------
  vendor_boot_oc_1600mhz_1200mv.img
      Top OPP 1600 MHz @ 1200 mV + GPLL 1600 MHz.
      SHA-256: b7457f48a98574d7300a0be1f5c5287a04211d56e362db770351f22d359242bc

  vendor_boot_oc_1600mhz_1200mv_mali.img
      Như trên + mali-supply = <0x47> (DCDC_GPU).
      SHA-256: fe21059f4f436f2a3b54aeae405b5f76d6f42da99ec33cc90e2a339102b0bd73

  vendor_boot_oc_1100mhz_1200mv.img
      Top OPP 1100 MHz @ 1200 mV + GPLL 1.1 GHz (bản thử điện áp an toàn).
      SHA-256: 76ba8995f01702a50c818b6040b52921032df752b57e31269dd9dcd4e03b8295

  vendor_boot_oc_1100mhz_1200mv_mali.img
      Như trên + mali-supply (đường regulator thật).
      SHA-256: 02a90f8823221e5b72aa3aff269ac84da8bfca18db2a5ad658c2126e93edfec6

Vì sao có bản 1.1 GHz @ 1.2 V
------------------------------
- 1.1 GHz đã ổn định ở rail ~912 mV, nên nếu điện áp KHÔNG đổi thì máy vẫn
  boot bình thường. Đây là cách thử đường điện áp mà không đánh đổi bằng
  rủi ro treo boot như mức 1.6 GHz.
- Bản 1100mhz_1200mv (không mali) khác bản 1.1 GHz ổn định đúng 6 byte
  (hai trường điện áp). Kỳ vọng: boot được, rail vẫn ~912 mV => chứng minh
  OPP voltage là mỹ phẩm.
- Bản _mali mới là bản có thể đặt 1.2 V thật. Nếu rail lên 1.2 V mà vẫn
  chạy ổn định thì mới đáng thử 1.6 GHz với _mali.

Sự thật về mức 1.2 V
--------------------
- Chỉ sửa operating-points / sprd,dvfs-lists là KHÔNG đủ. Module
  gpu_pm_ums9230.ko không hề import regulator_*; nó chỉ ghi chỉ số DVFS level
  vào regmap. Đo thực tế rail GPU vẫn ~912 mV dù OPP ghi 850 mV hay 1000 mV.
  => Ảnh 1200mv (không mali) chỉ đổi nhãn; khả năng cao vẫn lỗi như bản 1.0 V
     (GPU fault 0x4002 / treo boot).

- mali_kbase_ums9230.ko (driver Mali thật) CÓ dùng regulator:
  power_control_init() tìm 2 supply tùy chọn tên "mali" và "shadercores";
  kbase_devfreq_target() gọi regulator_set_voltage() TRƯỚC khi đổi tần số.
  Stock chỉ có gpu-supply (Unisoc), nên đường này chưa từng được dùng.
  => Ảnh _mali thêm mali-supply để nối DCDC_GPU vào đường đó. Đây là bản
     duy nhất có khả năng đặt 1.2 V thật.

- sc2730_regulator.ko nằm trong vendor_boot ramdisk (không phải vendor_dlkm).
  Descriptor DCDC_GPU: vsel_reg=0x1854, mask=0x1ff, bước 3125 uV,
  1.2 V tương ứng selector 384 (0x180).

Kết quả đo trên máy — bản 1100mhz_1200mv_mali (19/11)
-----------------------------------------------------
- DCDC_GPU/voltage = 912  (912.5 mV), KHÔNG phải 1200 mV.
- regulator.2 (vddgpu) có consumer "23100000.gpu-mali", num_users=1
  => kbase đã lấy được mali-supply và có gọi regulator_set_voltage().
- Ghi thẳng 1200 qua debugfs (locken=0x6e7f) rồi đọc lại vẫn 912
  => topdvfs phần cứng ghi đè ngay sau khi kernel ghi thanh ghi PMIC.
- Điện áp chạy theo DVFS level thực tế: 384-614 MHz ~750 mV,
  768 MHz ~781 mV, 1.1 GHz ~912 mV. Không khớp bảng OPP trong DT
  (700/750/800/1200) => trường voltage trong DT không điều khiển rail.
- gpu_pm_ums9230.ko chỉ ghi "cell" (0x04..0x08) vào topdvfs bằng
  regmap_update_bits; không hề ghi điện áp. Bảng điện áp nằm trong
  phần cứng/efuse (nvmem gpu_bin).
=> Muốn 1.2 V thật phải vô hiệu hóa/tái lập trình topdvfs cho GPU
   (vùng register 0x150, các bit tune-enable), không thể chỉ sửa
   vendor_boot DT. Vì vậy bản 1.6 GHz vẫn sẽ chạy rail ~912 mV và
   tiếp tục treo/fault như bản 1.0 V.

Test nhanh mức 1.2 V KHÔNG cần flash (chỉ chứng minh ghi được PMIC)
-------------------------------------------------------------------
  adb shell su -c 'mount -t debugfs none /sys/kernel/debug'
  adb shell su -c 'ls /sys/kernel/debug/sprd_regulator'
  adb shell su -c 'echo 0x6e7f > /sys/kernel/debug/sprd_regulator/locken'
  adb shell su -c 'echo 1200 > /sys/kernel/debug/sprd_regulator/DCDC_GPU/voltage'
  adb shell su -c 'cat /sys/kernel/debug/sprd_regulator/DCDC_GPU/voltage'

  Đơn vị là mV (driver nhân 1000). Đọc lại chỉ cho biết thanh ghi PMIC,
  KHÔNG chứng minh rail thực đã đổi — phải đo rail như trong REPORT.
  Nếu topdvfs phần cứng ghi đè thì rail vẫn ~912 mV.

Rủi ro / quay về
----------------
- 1.6 GHz khi rail vẫn ~912 mV: dự kiến treo boot hoặc GPU fault 0x4002.
- Ảnh _mali chưa được kiểm chứng trên máy; có thể dev_pm_opp_set_config
  từ chối cấu hình hoặc topdvfs ghi đè điện áp.
- Ảnh 1.1 GHz @ 1.2 V (không mali): rủi ro thấp, kỳ vọng boot bình thường
  vì rail không đổi. Ảnh 1.1 GHz _mali: nếu regulator path hoạt động thì
  rail lên 1.2 V — theo dõi nhiệt và độ ổn định.
- Quay về: flash lại vendor_boot.img stock.
- Bản 1.1 GHz ổn định: vendor_boot_oc_1100mhz_1000mv.img.
- KHÔNG flash các ảnh SML CPU (đã brick; kể cả sml_a17_stock.img).
