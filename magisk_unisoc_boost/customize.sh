#!/sbin/sh
##########################################################################################
#
# Unisoc Serenity Always Turbo Boost - Installation Script
# Compatible with Magisk, KernelSU, APatch
#
##########################################################################################

SKIPUNZIP=0

ui_print "*****************************************************"
ui_print "*        UNISOC SERENITY ALWAYS TURBO BOOST         *"
ui_print "*       Device: Redmi 14C / POCO C71 (serenity)     *"
ui_print "*       SoC: Unisoc UMS9230 / T7250 / T616          *"
ui_print "*****************************************************"
ui_print ""

# Check device architecture
ARCH=$(getprop ro.bionic.arch)
if [ "$ARCH" != "arm64" ]; then
    ui_print "! Unsupported architecture: $ARCH (expected arm64)"
    abort "! This module only supports ARM64 devices."
fi

ui_print "- Target CPU Clusters:"
ui_print "  * Cluster 0 (6x Cortex-A55): Max 1,820,000 kHz (1.82 GHz)"
ui_print "  * Cluster 1 (2x Cortex-A75): Max 2,210,000 kHz (2.21 GHz)"
ui_print ""
ui_print "- Features Configured:"
ui_print "  [✓] Aggressive Schedutil Governor Rate-Limits"
ui_print "  [✓] Auto-detection and Pinning of Max CPU Frequencies"
ui_print "  [✓] Userspace Thermal Throttling Disabled (thermald kill)"
ui_print "  [✓] Thermal Cooling Device State Locked to 0"
ui_print "  [✓] Thermal Zone Trip Points Raised to 95°C"
ui_print "  [✓] Background Turbo Watchdog Daemon Active"
ui_print ""

# Set permissions
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
set_perm "$MODPATH/uninstall.sh" 0 0 0755

ui_print "- Installation successful! Please reboot your device."
ui_print "*****************************************************"
