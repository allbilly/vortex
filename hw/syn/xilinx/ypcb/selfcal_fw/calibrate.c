// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <stdint.h>
#include <ypcb_calibration_abi.h>
#include "config.h"
#include "io.h"
#include "calibrate.h"

#ifndef FW_ID
#define FW_ID 0u
#endif

enum { OK, TIMEOUT, NO_EYE, READBACK, ROW_TIMING };
static uint32_t scans[9][8];
static uint32_t bit_scans[8][8];
static struct window windows[9];
static const uint32_t seeds[3] = {42, 84, 36};
static uint64_t deadline;
static uint32_t error, failed_lane, probes, max_row;

_Static_assert(cfg_sdram_phy_modules == 9, "Nine physical DDR lanes required");
_Static_assert(cfg_sdram_phy_dfi_databits == 144 && cfg_sdram_phy_phases == 4,
               "Unsupported DFI geometry");

static uint32_t read_word(uint32_t offset) {
    if (cal_now() >= deadline) {
        error = TIMEOUT;
        return 0;
    }
    return cal_read(offset);
}

static void write_word(uint32_t offset, uint32_t value) {
    if (cal_now() >= deadline) {
        error = TIMEOUT;
    }
    if (!error) {
        cal_write(offset, value);
    }
}

static void wait_cycles(uint32_t cycles) {
    if (!error) {
        cal_wait(cycles);
        if (cal_now() >= deadline) {
            error = TIMEOUT;
        }
    }
}

static void command(uint32_t phase, uint32_t value) {
    write_word(cfg_phases[phase].command, value);
    write_word(cfg_phases[phase].issue, 1);
    (void)read_word(cfg_sdram_dfii_control);
}

static void configure_lane(uint32_t lane, uint32_t slip, uint32_t delay) {
    write_word(cfg_ddrphy_dly_sel, 1u << lane);
    write_word(cfg_ddrphy_rdly_dq_rst, 1);
    write_word(cfg_ddrphy_rdly_dq_bitslip_rst, 1);
    for (uint32_t i = 0; i < slip; ++i) {
        write_word(cfg_ddrphy_rdly_dq_bitslip, 1);
    }
    for (uint32_t i = 0; i < delay; ++i) {
        write_word(cfg_ddrphy_rdly_dq_inc, 1);
    }
    write_word(cfg_ddrphy_dly_sel, 0);
}

static void probe(uint32_t seed, uint32_t bad[9]) {
    uint8_t expected[4][18];
    for (uint32_t phase = 0; phase < 4; ++phase) {
        write_word(cfg_phases[phase].address, 0);
        write_word(cfg_phases[phase].bank, 0);
    }
    for (uint32_t phase = 0; phase < 4; ++phase) {
        uint32_t words[5] = {0};
        for (uint32_t byte = 0; byte < 18; ++byte) {
            seed ^= seed << 13;
            seed ^= seed >> 17;
            seed ^= seed << 5;
            expected[phase][byte] = (uint8_t)seed;
            words[byte >> 2] |= (uint32_t)expected[phase][byte] << ((byte & 3) * 8);
        }
        for (uint32_t word = 0; word < 5; ++word) {
            write_word(cfg_phases[phase].wrdata + (4 - word) * 4, words[word]);
        }
    }
    uint64_t start = cal_now();
    command(0, cfg_dfii_command_ras | cfg_dfii_command_cs);
    wait_cycles(15);
    command(cfg_sdram_phy_wrphase, cfg_dfii_command_cas | cfg_dfii_command_we |
            cfg_dfii_command_cs | cfg_dfii_command_wrdata);
    wait_cycles(15);
    command(cfg_sdram_phy_rdphase, cfg_dfii_command_cas | cfg_dfii_command_cs | cfg_dfii_command_rddata);
    wait_cycles(15);
    command(0, cfg_dfii_command_ras | cfg_dfii_command_cs | cfg_dfii_command_we);
    uint32_t span = (uint32_t)(cal_now() - start);
    if (span > max_row) {
        max_row = span;
    }
    if (span > (cfg_sys_clock_hz / 100000u) * 351u / 100u) {
        error = ROW_TIMING;
    }
    wait_cycles(15);
    for (uint32_t lane = 0; lane < 9; ++lane) {
        bad[lane] = 0;
    }
    for (uint32_t phase = 0; phase < 4; ++phase) {
        uint32_t words[5];
        for (uint32_t word = 0; word < 5; ++word) {
            words[word] = read_word(cfg_phases[phase].rddata + (4 - word) * 4);
        }
        for (uint32_t byte = 0; byte < 18; ++byte) {
            uint32_t actual = (words[byte >> 2] >> ((byte & 3) * 8)) & 255;
            bad[byte < 9 ? byte : byte - 9] |= actual ^ expected[phase][byte];
        }
    }
    ++probes;
}

int ypcb_cal_select_window(const uint32_t scan[8], struct window *result) {
    if (!result) {
        return 0;
    }
    uint32_t best = 1;
    for (uint32_t slip = 0; slip < 8; ++slip) {
        uint32_t length = 0;
        for (uint32_t tap = 0; tap <= 32; ++tap) {
            if (tap < 32 && ((scan[slip] >> tap) & 1)) {
                ++length;
            } else {
                if (length > best) {
                    best = length;
                    result->slip = slip;
                    result->first = tap - length;
                    result->last = tap - 1;
                    result->center = (tap - length + tap - 1) >> 1;
                }
                length = 0;
            }
        }
    }
    return best >= 2;
}

static void publish_bit_diagnostics(uint32_t lane, uint32_t error_or, uint32_t error_and) {
    uint32_t valid = 0;
    for (uint32_t bit = 0; bit < 8; ++bit) {
        struct window w = {0};
        uint32_t count = 0;
        for (uint32_t slip = 0; slip < 8; ++slip) {
            uint32_t mask = bit_scans[bit][slip];
            while (mask) {
                mask &= mask - 1;
                ++count;
            }
        }
        uint32_t best_mask = 0;
        if (ypcb_cal_select_window(bit_scans[bit], &w)) {
            valid |= 1u << bit;
            best_mask = bit_scans[bit][w.slip];
        }
        cal_mailbox(YPCB_CAL_MB_BIT_WINDOWS + bit,
                    w.slip | (w.first << 8) | (w.last << 16) | (w.center << 24));
        cal_mailbox(YPCB_CAL_MB_BIT_COUNTS + bit, count);
        cal_mailbox(YPCB_CAL_MB_BIT_MASKS + bit, best_mask);
    }
    cal_mailbox(YPCB_CAL_MB_DIAG_LANE, lane);
    cal_mailbox(YPCB_CAL_MB_DIAG_VALID_BITS, valid);
    cal_mailbox(YPCB_CAL_MB_DIAG_ERROR_OR, error_or);
    cal_mailbox(YPCB_CAL_MB_DIAG_ERROR_AND, error_and);
    cal_mailbox(YPCB_CAL_MB_DIAG_TAPS, 256);
    cal_mailbox(YPCB_CAL_MB_DIAG_MAGIC, YPCB_CAL_DIAG_MAGIC);
}

static void train(void) {
    for (uint32_t lane = 0; lane < 9 && !error; ++lane) {
        failed_lane = lane;
        uint32_t error_or = 0, error_and = 255;
        for (uint32_t bit = 0; bit < 8; ++bit) {
            for (uint32_t slip = 0; slip < 8; ++slip) {
                bit_scans[bit][slip] = 0;
            }
        }
        for (uint32_t slip = 0; slip < 8 && !error; ++slip) {
            configure_lane(lane, slip, 0);
            for (uint32_t tap = 0; tap < 32 && !error; ++tap) {
                uint32_t bad_bits = 0;
                for (uint32_t sample = 0; sample < 3 && !error; ++sample) {
                    uint32_t bad[9];
                    probe(seeds[sample], bad);
                    bad_bits |= bad[lane];
                }
                if (!error) {
                    error_or |= bad_bits;
                    error_and &= bad_bits;
                    if (bad_bits == 0) {
                        scans[lane][slip] |= 1u << tap;
                    }
                    for (uint32_t bit = 0; bit < 8; ++bit) {
                        if (!((bad_bits >> bit) & 1)) {
                            bit_scans[bit][slip] |= 1u << tap;
                        }
                    }
                }
                write_word(cfg_ddrphy_dly_sel, 1u << lane);
                write_word(cfg_ddrphy_rdly_dq_inc, 1);
                write_word(cfg_ddrphy_dly_sel, 0);
            }
        }
        if (!error && !ypcb_cal_select_window(scans[lane], &windows[lane])) {
            publish_bit_diagnostics(lane, error_or, error_and);
            error = NO_EYE;
        }
        configure_lane(lane, windows[lane].slip, windows[lane].center);
        for (uint32_t sample = 0; sample < 3 && !error; ++sample) {
            uint32_t bad[9];
            probe(seeds[sample], bad);
            if (bad[lane]) {
                error = NO_EYE;
            }
        }
    }
    for (uint32_t sample = 0; sample < 3 && !error; ++sample) {
        uint32_t bad[9];
        probe(seeds[sample], bad);
        for (uint32_t lane = 0; lane < 9 && !error; ++lane) {
            if (bad[lane]) {
                failed_lane = lane;
                error = NO_EYE;
            }
        }
    }
    if (!error) {
        failed_lane = 9;
    }
}

uint32_t ypcb_calibrate(void) {
    uint64_t start = cal_now();
    deadline = start + 30ull * cfg_sys_clock_hz;
    error = probes = max_row = 0;
    failed_lane = 9;
    for (uint32_t lane = 0; lane < 9; ++lane) {
        for (uint32_t slip = 0; slip < 8; ++slip) {
            scans[lane][slip] = 0;
        }
        windows[lane] = (struct window){0};
    }
    for (uint32_t index = 0; index < 128; ++index) {
        cal_mailbox(index, 0);
    }
    cal_mailbox(YPCB_CAL_MB_MAGIC, YPCB_CAL_MAGIC);
    cal_mailbox(YPCB_CAL_MB_FIRMWARE, FW_ID);
    cal_mailbox(YPCB_CAL_MB_STATE, YPCB_CAL_RUNNING);
    write_word(cfg_ddrctrl_selfcal_state, YPCB_CAL_RUNNING);
    write_word(cfg_ddrctrl_init_done, 0);
    write_word(cfg_ddrctrl_init_error, 0);
    write_word(cfg_sdram_dfii_control, cfg_dfii_control_odt);
    write_word(cfg_ddrphy_rst, 1);
    write_word(cfg_ddrphy_rdphase, cfg_sdram_phy_rdphase);
    write_word(cfg_ddrphy_wrphase, cfg_sdram_phy_wrphase);
    write_word(cfg_sdram_dfii_pi0_address, 0);
    write_word(cfg_sdram_dfii_pi0_baddress, 0);
    wait_cycles(1000);
    write_word(cfg_ddrphy_rst, 0);
    (void)read_word(cfg_sdram_dfii_control);
    wait_cycles(cfg_sys_clock_hz / 5000u);
    for (uint32_t i = 0; i < sizeof(cfg_initialization) / sizeof(cfg_initialization[0]) && !error; ++i) {
        const struct cfg_operation *operation = &cfg_initialization[i];
        if (operation->kind == CFG_WAIT) {
            (void)read_word(cfg_sdram_dfii_control);
            wait_cycles(operation->value);
        } else {
            write_word(operation->offset, operation->value);
        }
    }
    write_word(cfg_sdram_dfii_control, cfg_dfii_control_cke | cfg_dfii_control_odt | cfg_dfii_control_reset_n);
    for (uint32_t lane = 0; lane < 9; ++lane) {
        configure_lane(lane, 0, 0);
    }
    train();
    write_word(cfg_ecc_axi_0_enable, 1);
    if (!error) {
        uint32_t value = read_word(cfg_ecc_axi_0_enable);
        if (!error && value != 1) {
            error = READBACK;
        }
    }
    write_word(cfg_sdram_dfii_control, cfg_dfii_control_sel);
    if (!error) {
        uint32_t value = read_word(cfg_sdram_dfii_control);
        if (!error && value != cfg_dfii_control_sel) {
            error = READBACK;
        }
    }
    write_word(cfg_ddrctrl_init_done, 1);
    if (!error) {
        uint32_t value = read_word(cfg_ddrctrl_init_done);
        if (!error && value != 1) {
            error = READBACK;
        }
    }
    if (error) {
        cal_write(cfg_ddrctrl_init_done, 0);
        cal_write(cfg_ddrctrl_init_error, 1);
        cal_write(cfg_ddrphy_dly_sel, 0);
        cal_write(cfg_ddrphy_rst, 0);
        cal_write(cfg_sdram_dfii_control, cfg_dfii_control_odt);
    }
    for (uint32_t lane = 0; lane < 9; ++lane) {
        struct window *w = &windows[lane];
        cal_mailbox(YPCB_CAL_MB_LANES + lane, w->slip | (w->first << 8) | (w->last << 16) | (w->center << 24));
        for (uint32_t slip = 0; slip < 8; ++slip) {
            cal_mailbox(YPCB_CAL_MB_SCANS + lane * 8 + slip, scans[lane][slip]);
        }
    }
    uint64_t elapsed = cal_now() - start;
    cal_mailbox(YPCB_CAL_MB_ERROR, error);
    cal_mailbox(YPCB_CAL_MB_FAILED_LANE, failed_lane);
    cal_mailbox(YPCB_CAL_MB_PROBES, probes);
    cal_mailbox(YPCB_CAL_MB_MAX_ROW_CYCLES, max_row);
    cal_mailbox(YPCB_CAL_MB_CYCLES_LOW, (uint32_t)elapsed);
    cal_mailbox(YPCB_CAL_MB_CYCLES_HIGH, (uint32_t)(elapsed >> 32));
    uint32_t state = error ? YPCB_CAL_FAILED : YPCB_CAL_READY;
    cal_mailbox(YPCB_CAL_MB_STATE, state);
    cal_write(cfg_ddrctrl_selfcal_state, state);
    return error;
}

#ifndef CAL_HOST
int main(void) {
    (void)ypcb_calibrate();
    for (;;) {
    }
}
#endif
