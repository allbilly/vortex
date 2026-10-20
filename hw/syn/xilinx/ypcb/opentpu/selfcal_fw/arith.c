// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <stdint.h>

uint32_t __mulsi3(uint32_t a, uint32_t b) {
    uint32_t result = 0;
    while (b) {
        if (b & 1) {
            result += a;
        }
        a <<= 1;
        b >>= 1;
    }
    return result;
}

uint32_t __umodsi3(uint32_t a, uint32_t b) {
    if (!b) {
        return a;
    }
    uint32_t bit = 1;
    while (b < a && !(b & 0x80000000u)) {
        b <<= 1;
        bit <<= 1;
    }
    while (bit) {
        if (a >= b) {
            a -= b;
        }
        b >>= 1;
        bit >>= 1;
    }
    return a;
}

int32_t __modsi3(int32_t a, int32_t b) {
    uint32_t magnitude = a < 0 ? 0u - (uint32_t)a : (uint32_t)a;
    uint32_t divisor = b < 0 ? 0u - (uint32_t)b : (uint32_t)b;
    uint32_t remainder = __umodsi3(magnitude, divisor);
    return (int32_t)(a < 0 ? 0u - remainder : remainder);
}
