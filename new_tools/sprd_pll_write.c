// SPDX-License-Identifier: GPL-2.0
/*
 * Reprogram MPLL1 Channel 4 from Linux.
 *
 * On this device the SML DVFS table reports 2210 MHz for the A75 top OPP,
 * but the hardware MUX still selects Channel 4, whose register 0x64580088
 * is factory-set to 0x464 (mult=70, cfg=4 => 1820 MHz).  Channel 7 is
 * factory-set to 0x556 (mult=85, cfg=6 => 2210 MHz).  Writing that same
 * proven value into Channel 4 makes the selected channel output 2210 MHz.
 *
 * No SML partition change, no SMC involved.  Delivered via vendor_ramdisk.
 */
#include <linux/init.h>
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/io.h>

#define REG_PHYS 0x64580088UL   /* MPLL1 Channel 4 config */
#define REG_VALUE 0x556UL       /* mult=85 (85*26=2210MHz), cfg=6 (proven by Ch7) */

static unsigned long reg_phys = REG_PHYS;
module_param(reg_phys, ulong, 0644);
MODULE_PARM_DESC(reg_phys, "physical address of MPLL1 channel register");

static unsigned int reg_value = REG_VALUE;
module_param(reg_value, uint, 0644);
MODULE_PARM_DESC(reg_value, "32-bit value to write");

static int __init sprd_pll_write_init(void)
{
	void __iomem *base;
	u32 before, after;

	base = ioremap(reg_phys, sizeof(u32));
	if (!base) {
		pr_err("sprd_pll_write: ioremap(%#lx) failed\n", reg_phys);
		return -ENOMEM;
	}
	before = readl(base);
	pr_info("sprd_pll_write: %#lx before=%#x\n", reg_phys, before);
	writel(reg_value, base);
	after = readl(base);
	pr_info("sprd_pll_write: %#lx wrote=%#x after=%#x\n",
		reg_phys, reg_value, after);
	iounmap(base);
	return 0;
}

static void __exit sprd_pll_write_exit(void)
{
	void __iomem *base = ioremap(reg_phys, sizeof(u32));
	if (base) {
		writel(0x464, base);   /* restore stock 1820 MHz on unload */
		iounmap(base);
	}
	pr_info("sprd_pll_write: restored stock\n");
}

module_init(sprd_pll_write_init);
module_exit(sprd_pll_write_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Reprogram MPLL1 channel 4 to 2.21 GHz (vendor_boot delivered)");
