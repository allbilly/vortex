# LR/SC ordering regression

Each active hart uses private global and local words. The application checks
that a second SC cannot reuse an earlier reservation and that a later LR
replaces the previous address. It also checks that rejected writes leave the
target unchanged. The critical instruction sequences are single inline-assembly
blocks, with early-clobber outputs and a memory clobber.

| Bit | Sequence before the rejected SC to A |
| --- | --- |
| 0, 1 | LR A; SC A, in global or local memory |
| 2, 4 | LR A; SC B, different words in the same global or local bank |
| 3, 5 | LR A; SC B, different global or local banks |
| 6, 7 | LR A; SC B, global-to-local or local-to-global |
| 8, 10 | LR A; LR B, different words in the same global or local bank |
| 9, 11 | LR A; LR B, different global or local banks |
| 12, 13 | LR A; LR B, global-to-local or local-to-global |

Global words occupy distinct cache lines; local words occupy distinct XLEN
words. Bank periods come from the resolved configuration. Different-bank cases
are explicitly absent from `enabled_cases` when that memory has only one bank.
A multibank CI configuration supplies that coverage.

Ordinary SC operations may fail spuriously. Only the forbidden SC is required
to fail; independent LR/SC increment loops retry with an 8,192-attempt bound.
The host requires their requested increments to complete and verifies that
every active task returned all enabled results. `failed_first_sc` records the
intervening failed-SC paths observed during the run.

From a configured build, use matching flags for the kernel library, dispatcher,
backend and application:

```bash
CONFIGS="-DVX_CFG_EXT_A_ENABLE" make -C tests/regression/lrsc_order
CONFIGS="-DVX_CFG_EXT_A_ENABLE" ./ci/blackbox.sh --driver=simx --app=lrsc_order --args="-n4"
```

`-n1..128` sets the iteration count. Default launch shape uses every configured
hart, one CTA per core; `-s` launches a single active hart without changing the
machine configuration. Separate configured builds cover scalar and narrow LSU
packets, including eight threads with four SIMD lanes and two LSU lanes.

With Zacas enabled, two additional phases use native `amocas.w.aqrl`. Adjacent
lanes choose opposite local/global addresses before the common instruction;
the second phase swaps their choices. Each checks a matching nonzero comparand
and a stale nonzero comparand, returned old values and memory contents. `-c`
runs only these phases so a split-request comparator failure can be diagnosed
independently of LR/SC ordering. At least two active lanes are needed to exercise
the mixed local/global split in one request.

`-w1..3600` changes the host event-wait budget in seconds (default 60), without
changing the GPU iteration or retry limits. Large RTL models may need a longer
wall-time budget; run them under a separate bounded process timeout.
