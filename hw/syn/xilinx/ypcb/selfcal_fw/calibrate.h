// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once
#include <stdint.h>

struct window { uint32_t slip, first, last, center; };
#ifdef __cplusplus
extern "C" {
#endif
int ypcb_cal_select_window(const uint32_t scan[8], struct window *result);
uint32_t ypcb_calibrate(void);
#ifdef __cplusplus
}
#endif
