// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once
#include <stdint.h>

#ifdef CAL_HOST
uint32_t cal_read(uint32_t offset);
void cal_write(uint32_t offset, uint32_t value);
uint64_t cal_now(void);
void cal_wait(uint32_t cycles);
void cal_mailbox(uint32_t index, uint32_t value);
#else
static inline uint32_t cal_read(uint32_t offset) {
    return *(volatile uint32_t *)(0xf0000000u + offset);
}
static inline void cal_write(uint32_t offset, uint32_t value) {
    *(volatile uint32_t *)(0xf0000000u + offset) = value;
}
static inline uint64_t cal_now(void) {
    uint32_t low = *(volatile uint32_t *)0x20000800u;
    uint32_t high = *(volatile uint32_t *)0x20000804u;
    return ((uint64_t)high << 32) | low;
}
static inline void cal_wait(uint32_t cycles) {
    uint64_t start = cal_now();
    while (cal_now() - start < cycles) {
    }
}
static inline void cal_mailbox(uint32_t index, uint32_t value) {
    ((volatile uint32_t *)0x20000000u)[index] = value;
}
#endif
