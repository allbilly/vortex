# Hart-wide LR/SC qualification

The bounded bank reservation tables can retain entries for one hart in different
slots or banks. `LR(A); LR(B); SC(B); SC(A)` can therefore make both stores
conditional succeed. The new SimX local-memory reservation policy exposes the
same inherited RTL weakness. The [RISC-V Zalrsc specification](https://riscv.github.io/riscv-isa-manual/snapshot/spec/)
requires every SC to invalidate that hart's reservation, including a failed SC,
and permits pairing only with its most recent LR.

Keep the existing bank tables and their bounded holder credits. Add a small
qualification tracker at the LSU slice's accepted request boundary, before
local/global routing and cache banking. It holds one valid bit and the latest LR
address per resident hart. An accepted LR replaces that state. An accepted SC
reads it and always clears it; a missing or different-address reservation marks
the request as forced failure. Comparing effective addresses may reject an alias,
which Zalrsc permits. Qualification is necessary but insufficient: the destination
bank still checks interference, eviction, and its existing reservation policy.

Each warp has a stable issue slot, and lane dispatch maps that slot to a stable
LSU block. All memory requests from a hart consequently pass through one slice,
regardless of destination bank or local/global address class. Include packet ID
in the hart ID when a warp spans multiple LSU packets; lane index alone aliases
different threads.

Carry the rejection bit in the typed AMO attribute and combine it with the bank's
SC reservation result. It must suppress the store, preserve another hart's
reservation, and produce the ordinary nonzero SC result. No extra request,
pipeline stage, or memory arbitration change is needed. Old orphaned bank entries
may consume bounded capacity temporarily but cannot authorize an unqualified SC.

SimX's LSU owns the same per-hart tracker. Its per-lane request field flows through
the existing request channels and adapters into the cache/local-memory flags.
No module reaches across another module's ownership boundary. The global cache model uses the same bounded, direct-mapped station table as
the RTL, normalizing byte addresses to bank-local line numbers before indexing.
Local and global tables protect any occupied station from a foreign LR while
hold credits remain, including a different-tag index conflict. Otherwise two
private lines that alias one station can repeatedly evict each other before
either SC arrives. Same-hart replacement remains allowed, and abandoned holders
expire after the existing credit budget. Pipeline stages and all timing constants
remain unchanged.

A mixed local/global request may be accepted by its two branches on different
cycles. The switch records each accepted subset until the complete input is
released, so a fast branch cannot issue duplicate requests while its peer is
stalled. SimX uses the same partial-send state over its request channels.

The split request must preserve the existing compare-and-swap comparand as well
as the new qualification field. Native Zacas tests with nonzero comparands check
both local and global operand forwarding.

Validation adds an independent architectural tracker reference, RTL/SimX trace
comparison with stalls and packetized lanes, and real LR/SC kernels covering
different words in one bank, different banks, failed SC, successful SC, and both
orders of local/global transitions. Existing contended atomic tests check forward
progress and the SimX/RTL parity case checks unchanged modeled timing. The active
baseline build and its pinned source remain untouched until these isolated
changes are reviewed and qualified.
