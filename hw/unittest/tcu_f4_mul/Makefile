ROOT_DIR := $(realpath ../../..)
NUM_REGS ?= 2
PROD_REG ?= 1
USE_DSP ?= 1
TEST_THREADS := $(shell expr 4 \* $(NUM_REGS))

# Unit geometry must enter profile resolution as explicit flags.
override CONFIGS := $(filter-out -DVX_CFG_NUM_THREADS=% -DVX_CFG_NUM_WARPS=%,$(CONFIGS))
override CONFIGS += -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_NUM_THREADS=$(TEST_THREADS) -DVX_CFG_NUM_WARPS=8
override CONFIGS += -DVX_CFG_TCU_WGMMA_ENABLE -DVX_CFG_TCU_MX_ENABLE -DVX_CFG_TCU_FP4_ENABLE
override CONFIGS += -DVX_CFG_TCU_MXFP4_ENABLE -DVX_CFG_TCU_NVFP4_ENABLE
include $(ROOT_DIR)/config.mk

PROJECT := tcu_f4_mul
TOP := VX_tcu_f4_mul_top
SRC_DIR := $(VORTEX_HOME)/hw/unittest/$(PROJECT)
RTL_DIR := $(VORTEX_HOME)/hw/rtl
PARAMS := -GN=$(NUM_REGS) -GPROD_REG=$(PROD_REG) -GDSP_ENABLE=$(USE_DSP)
CXXFLAGS := -DNUM_REGS=$(NUM_REGS) -DPROD_REG=$(PROD_REG)
SRCS := $(SRC_DIR)/main.cpp
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv $(RTL_DIR)/tcu/VX_tcu_pkg.sv
RTL_INCLUDE := -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs -I$(RTL_DIR)/tcu -I$(RTL_DIR)/tcu/tfr -I$(SRC_DIR)

include ../common.mk

.PHONY: run-matrix
run-matrix:
	@set -e; for regs in 2 4; do for pipe in 0 1; do for dsp in 0 1; do \
	  $(MAKE) clean; \
	  $(MAKE) run NUM_REGS=$$regs PROD_REG=$$pipe USE_DSP=$$dsp; \
	done; done; done
