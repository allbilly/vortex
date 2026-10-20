// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "cal.h"
#include "hw.h"
#include "selfcal_cfg.h"

uint32_t ypcb_wl_calibrate(void) {
    hw_wr(CSR_INIT_DONE, 0);
    hw_wr(CSR_INIT_ERROR, 0);
    hw_wr(CSR_ECC_ENABLE, 0);
    uint32_t state = selfcal_run(1, 1);
    if (state == ST_OK) {
        hw_wr(CSR_ECC_ENABLE, 1);
        if (hw_rd(CSR_ECC_ENABLE) != 1 || hw_rd(CSR_DFII_CONTROL) != 1) {
            state = ST_FAILED | (8u << 8);
        }
    }
    if (state == ST_OK) {
        hw_wr(CSR_INIT_DONE, 1);
        if (hw_rd(CSR_INIT_DONE) != 1) {
            state = ST_FAILED | (8u << 8);
        }
    }
    if (state != ST_OK) {
        hw_wr(CSR_INIT_DONE, 0);
        hw_wr(CSR_INIT_ERROR, 1);
        hw_wr(CSR_DFII_CONTROL, 4);
        hw_wr(CSR_DLY_SEL, 0);
        hw_mbox(MB_CH(0) + MB_STATUS, state | (1u << 16) | (1u << 17) | (1u << 24));
    }
    // The terminal flag also certifies the ECC/controller handoff.
    state |= ST_DONE;
    hw_mbox(MB_STATE, state);
    hw_wr(CSR_SELFCAL_STATE, state);
    return state;
}

#ifndef SELFCAL_HOST
int main(void) {
    (void)ypcb_wl_calibrate();
    for (;;) {
    }
}
#endif
