#!/system/bin/sh
##########################################################################################
#
# Unisoc Serenity Always Turbo Boost - Background Daemon
# Runs in late_start service mode
#
##########################################################################################

LOG_FILE="/data/local/tmp/unisoc_turbo_boost.log"
exec > "$LOG_FILE" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Unisoc Turbo Boost Service starting..."

# 1. Wait until Android boot is complete
while [ "$(getprop sys.boot_completed)" != "1" ]; do
    sleep 2
done

# Extra wait for services and thermal HAL to stabilize
sleep 4

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Boot completed. Applying Turbo Boost configuration..."

# 2. Stop userspace thermal daemon if running
echo "[*] Disabling vendor thermal daemon..."
stop vendor.thermald 2>/dev/null
stop thermald 2>/dev/null
killall -9 thermald 2>/dev/null

# 3. Raise writable thermal trip points to 95°C (95000)
# Kernel config CONFIG_THERMAL_WRITABLE_TRIPS=y allows this
echo "[*] Raising kernel thermal trip points..."
for trip in /sys/class/thermal/thermal_zone*/trip_point_*_temp; do
    if [ -f "$trip" ]; then
        chmod 644 "$trip" 2>/dev/null
        echo 95000 > "$trip" 2>/dev/null
    fi
done

# 4. Reset and lock thermal cooling devices
echo "[*] Locking thermal cooling devices to 0..."
for cdev in /sys/class/thermal/cooling_device*; do
    if [ -f "$cdev/cur_state" ]; then
        chmod 644 "$cdev/cur_state" 2>/dev/null
        echo 0 > "$cdev/cur_state" 2>/dev/null
        chmod 444 "$cdev/cur_state" 2>/dev/null
    fi
done

# 5. Function to apply cpufreq boost & governor tuning
apply_cpufreq_boost() {
    for pol in /sys/devices/system/cpu/cpufreq/policy*; do
        [ -d "$pol" ] || continue

        # Detect maximum available frequency
        TARGET_MAX=""
        if [ -f "$pol/scaling_available_frequencies" ]; then
            TARGET_MAX=$(tr ' ' '\n' < "$pol/scaling_available_frequencies" | sort -n | tail -1)
        fi
        if [ -z "$TARGET_MAX" ] && [ -f "$pol/cpuinfo_max_freq" ]; then
            TARGET_MAX=$(cat "$pol/cpuinfo_max_freq" 2>/dev/null)
        fi

        # Unlock write access
        chmod 644 "$pol/scaling_max_freq" 2>/dev/null
        chmod 644 "$pol/scaling_min_freq" 2>/dev/null
        chmod 644 "$pol/scaling_governor" 2>/dev/null

        # Governor tuning
        GOV=$(cat "$pol/scaling_governor" 2>/dev/null)
        if [ "$GOV" = "schedutil" ]; then
            TUNEDIR="$pol/schedutil"
            if [ -d "$TUNEDIR" ]; then
                [ -f "$TUNEDIR/up_rate_limit_us" ] && echo 500 > "$TUNEDIR/up_rate_limit_us" 2>/dev/null
                [ -f "$TUNEDIR/down_rate_limit_us" ] && echo 50000 > "$TUNEDIR/down_rate_limit_us" 2>/dev/null
                [ -f "$TUNEDIR/rate_limit_us" ] && echo 1000 > "$TUNEDIR/rate_limit_us" 2>/dev/null
            fi
        fi

        # Apply maximum scaling frequency
        if [ -n "$TARGET_MAX" ] && [ "$TARGET_MAX" -gt 0 ]; then
            echo "$TARGET_MAX" > "$pol/scaling_max_freq" 2>/dev/null
            # Lock scaling_max_freq to read-only so thermald/PowerHAL cannot downclock it
            chmod 444 "$pol/scaling_max_freq" 2>/dev/null
            echo "[+] Policy $(basename "$pol") locked to max: $TARGET_MAX kHz"
        fi
    done
}

apply_cpufreq_boost

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Initial boost applied. Starting Watchdog loop..."

# 6. Persistent Watchdog Loop (runs every 5 seconds)
while true; do
    sleep 5

    # If thermald was restarted by init, kill it
    if pidof thermald >/dev/null 2>&1; then
        stop vendor.thermald 2>/dev/null
        killall -9 thermald 2>/dev/null
    fi

    # Ensure cooling devices stay at state 0
    for cdev_state in /sys/class/thermal/cooling_device*/cur_state; do
        if [ -f "$cdev_state" ]; then
            CUR=$(cat "$cdev_state" 2>/dev/null)
            if [ "$CUR" != "0" ]; then
                chmod 644 "$cdev_state" 2>/dev/null
                echo 0 > "$cdev_state" 2>/dev/null
                chmod 444 "$cdev_state" 2>/dev/null
            fi
        fi
    done

    # Ensure cpufreq policy max is not degraded
    for pol in /sys/devices/system/cpu/cpufreq/policy*; do
        [ -d "$pol" ] || continue
        if [ -f "$pol/cpuinfo_max_freq" ]; then
            MAX_POSSIBLE=$(cat "$pol/cpuinfo_max_freq" 2>/dev/null)
            CURR_MAX=$(cat "$pol/scaling_max_freq" 2>/dev/null)
            if [ -n "$MAX_POSSIBLE" ] && [ "$CURR_MAX" != "$MAX_POSSIBLE" ]; then
                chmod 644 "$pol/scaling_max_freq" 2>/dev/null
                echo "$MAX_POSSIBLE" > "$pol/scaling_max_freq" 2>/dev/null
                chmod 444 "$pol/scaling_max_freq" 2>/dev/null
            fi
        fi
    done
done &
