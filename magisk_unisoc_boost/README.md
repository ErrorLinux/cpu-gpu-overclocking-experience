# Unisoc Serenity Always Turbo Boost Module (Magisk / KernelSU / APatch)

## Giới thiệu
Module Magisk được tối ưu hóa chuyên biệt cho chipset Unisoc UMS9230 / T7250 / T616 trên thiết bị Xiaomi Redmi 14C / POCO C71 (`serenity`).

## Tính năng chính
1. **Ép xung tối đa CPU (CPU Turbo Boost Pinning):**
   - Cluster 0 (6× Cortex-A55): Tối đa **1,820,000 kHz (1.82 GHz)**.
   - Cluster 1 (2× Cortex-A75): Tối đa **2,210,000 kHz (2.21 GHz)**.
2. **Khóa chống tụt xung (Anti-Throttling Lock):**
   - Đặt quyền `chmod 444` lên `/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq` ngăn chặn PowerHAL, Battery Saver hạ xung.
   - Vô hiệu hóa daemon kiểm soát nhiệt người dùng: `vendor.thermald`.
   - Khóa các thiết bị làm mát (thermal cooling devices) về mức 0.
   - Tăng ngưỡng trip points nhiệt độ trong kernel lên 95°C (`CONFIG_THERMAL_WRITABLE_TRIPS=y`).
3. **Tinh chỉnh Governor Schedutil:**
   - `up_rate_limit_us`: 500 µs (tăng xung tức thì khi có tải đồ họa/game).
   - `down_rate_limit_us`: 50,000 µs (duy trì xung đỉnh lâu hơn trước khi hạ).
   - `rate_limit_us`: 1,000 µs.
4. **Daemon giám sát chạy ngầm (Watchdog Loop):**
   - Kiểm tra định kỳ mỗi 5 giây trong nền, tự động khôi phục xung nhịp tối đa nếu bị hệ thống can thiệp.

## Hướng dẫn cài đặt
1. Cài đặt file `Unisoc_Serenity_Always_Boost_v1.0.zip` qua ứng dụng **Magisk**, **KernelSU**, hoặc **APatch**.
2. Khởi động lại thiết bị (Reboot).
3. Kiểm tra nhật ký hoạt động qua terminal:
   ```sh
   su -c "cat /data/local/tmp/unisoc_turbo_boost.log"
   su -c "cat /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq"
   ```
