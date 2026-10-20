// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <stddef.h>

void *memset(void *destination, int value, size_t count) {
    unsigned char *output = destination;
    for (size_t index = 0; index < count; ++index) {
        output[index] = (unsigned char)value;
    }
    return destination;
}

void *memcpy(void *destination, const void *source, size_t count) {
    unsigned char *output = destination;
    const unsigned char *input = source;
    for (size_t index = 0; index < count; ++index) {
        output[index] = input[index];
    }
    return destination;
}
