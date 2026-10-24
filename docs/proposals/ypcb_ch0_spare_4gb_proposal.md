# YPCB 4 GiB mixed-ECC memory

The qualified `ypcb_blackwell_like` image uses CH1's 2 GiB with ECC. The
successor adds CH0's 2 GiB without ECC and retains the complete compute
configuration, 125 MHz GPU clock, JTAG runtime and PCIe runtime interfaces.

OpenTPU's fixed-clock spare-lane configuration provides the board reference:
CH0 logical lanes map to physical lanes `[0, 1, 2, 3, 4, 5, 8, 7]`. Physical
lane 8 replaces faulty lane 6, so CH0 has eight data lanes and no ECC lane.
CH1 retains its nine-lane ECC arrangement. Capacity comes from enabling both
channels; disabling ECC alone does not double a channel's capacity.

## Address and interface contract

Keep one logical AFU memory bank and widen its byte address to 32 bits.
The board router selects the physical channel with address bit 31 and sends
bits 30:0 to that channel. CH0 occupies `0x00000000` through `0x7fffffff`;
CH1 occupies `0x80000000` through `0xffffffff`. Requests above 4 GiB, unaligned
64-byte beats and bursts crossing 4 KiB retain explicit error responses.
Read and write transactions retain their selected channel and original ID
until completion, including backpressure and reset cancellation.

Use a separate `ypcb_blackwell_like_4gb` profile. Existing profiles retain
their 2 GiB configuration. RV32 can encode the device byte addresses, while
the runtime must account for console, stacks, local memory and any enabled
virtual apertures when reporting allocatable memory.

The runtime reserves the architectural top region using the device's hart
geometry, including the padded warp-index stride. With 64 harts and 8 KiB
stacks, the protected range is `0xfff70000` through `0xffffffff`: 512 KiB
of stacks plus the 64 KiB local-memory window and top gap. The separate
256 MiB YPCB host-staging arena also remains reserved. Physical capacity
queries report 4 GiB; free-memory queries account for these reservations.

## Controller and startup changes

Generate separate CH0 and CH1 WL7DDRPHY controllers at DDR800 with 100 MHz
controller clocks. CH0 uses a 64-bit PHY and a raw 512-bit user port; CH1 uses
a 72-bit PHY and its existing 512-bit ECC user port. Masked writes retain
read-modify-write serialization because board DM outputs are not connected.
Each controller owns its calibration CPU, firmware, CSR bridge and reset.
Firmware and export metadata must identify the physical channel, lane map
and ECC mode. The dual-channel board interface has a new identity and startup
waits for both channels. The reviewed 2 GiB image remains a separate fallback.

Configure a fresh build with `--xlen=32 --memory-size=4294967296
--profile=ypcb_blackwell_like_4gb`. From that generated build, the board's
`ddr-sources` target generates both controllers into separate directories and
assembles the dual export. `ddr-host-config` derives the runtime header from
that export; the runtime rejects a header with a different capacity or channel
selection. Controller output directories must be fresh. To reuse a preserved
CH1 export, generate CH0 with `opentpu/gen_core.py --physical-channel=0`, then
pass those two exports to `gen_dual_ddr.py --ch0 ... --ch1 ... --output ...`.
Reuse preserves the selected controller bytes; the new complete image still
requires its own hardware qualification.

## Verification

Resolve the selected profile and elaborate its complete export before
implementation. Exercise channel selection, response ownership, byte masks,
backpressure, invalid addresses and reset behavior in RTL tests. Qualify
both controllers' calibration and CDC constraints independently, including
every FIFO, reset and status sideband. On the board, verify distinct patterns
on both channels, the 2 GiB boundary, high addresses and absence of aliases.
Repeat the compute examples and relevant full-profile regressions with the
new runtime, memory size and exact bitstream. Physical PCIe qualification
remains distinct from the local JTAG runtime results.
