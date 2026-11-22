# Changelog

All notable changes to the Ainz GPU OC Kit are documented here.

## [1.0.0] — 2026-11-19

### Added

- Unified `oc.py` CLI with `build` and `verify` commands.
- Real GPLL overclock through `assigned-clocks` / `assigned-clock-rates`
  on the GPU device-tree node.
- Optional `mali-supply = <&DCDC_GPU>` variant for the Mali kbase
  regulator path.
- Structural verifier for the FDT, SPRD wrapper, boot-header `dtb_size`,
  and the byte-identical regions outside the FDT.
- Safety gate: values above 1200 MHz or 1000 mV require
  `--i-know-the-risks`.
- Documentation: technical notes, measurements, safety and rollback.
- Byte-for-byte reproducibility against the reference builds:
  - 1100 MHz / 1000 mV: `cf0735a64f42cf8b7c5b56e614df7f0c57ca6b4fb68e091e48382509451a5277`
  - 1100 MHz / 1200 mV: `76ba8995f01702a50c818b6040b52921032df752b57e31269dd9dcd4e03b8295`
  - 1100 MHz / 1200 mV + mali-supply: `02a90f8823221e5b72aa3aff269ac84da8bfca18db2a5ad658c2126e93edfec6`
  - 1600 MHz / 1200 mV + mali-supply: `fe21059f4f436f2a3b54aeae405b5f76d6f42da99ec33cc90e2a339102b0bd73`
- Initial public release. Author: Ainz.
