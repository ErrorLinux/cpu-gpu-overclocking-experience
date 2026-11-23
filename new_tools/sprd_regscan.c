// SPDX-License-Identifier: GPL-2.0
/* Register scanner for the APCPU secure clock block (0x64300000).
 * Write 1 to /sys/module/sprd_regscan/parameters/dump to dump `words` 32-bit
 * registers starting at `scan_base` into dmesg with a stable prefix. */
#include <linux/init.h>
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/io.h>
#include <linux/errno.h>

static unsigned long scan_base = 0x64300000UL;
module_param(scan_base, ulong, 0644);
static unsigned int scan_words = 0x400;
module_param(scan_words, uint, 0644);

static int do_dump(void)
{
	void __iomem *p;
	unsigned int i;

	if (scan_words == 0 || scan_words > 0x1000)
		return -EINVAL;
	p = ioremap(scan_base, scan_words * 4);
	if (!p) {
		pr_err("sprd_regscan: ioremap(%#lx) failed\n", scan_base);
		return -ENOMEM;
	}
	pr_info("sprd_regscan: BEGIN base=%#lx words=%u\n", scan_base, scan_words);
	for (i = 0; i < scan_words; i++)
		pr_info("sprd_regscan: %08lx: %08x\n",
			scan_base + (unsigned long)i * 4, readl(p + i * 4));
	pr_info("sprd_regscan: END\n");
	iounmap(p);
	return 0;
}

static int set_dump(const char *val, const struct kernel_param *kp)
{
	unsigned int v;
	int ret = kstrtouint(val, 0, &v);
	(void)kp;
	if (ret) return ret;
	return v ? do_dump() : 0;
}
static int get_dump(char *buf, const struct kernel_param *kp)
{
	(void)kp;
	return scnprintf(buf, PAGE_SIZE, "0\n");
}
static const struct kernel_param_ops dump_ops = { .set = set_dump, .get = get_dump };
module_param_cb(dump, &dump_ops, NULL, 0200);

static int __init sprd_regscan_init(void)
{
	pr_info("sprd_regscan: loaded; write dump=1 to scan\n");
	return 0;
}
module_init(sprd_regscan_init);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Physical register scanner");
