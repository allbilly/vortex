ROOT_DIR := $(realpath ../../..)
NUM_THREADS ?= 8
NUM_WARPS ?= 8
NUM_LANES ?= $(NUM_THREADS)
override CONFIGS := $(filter-out -DVX_CFG_NUM_THREADS=% -DVX_CFG_NUM_WARPS=% -DVX_CFG_NUM_CORES=%,$(CONFIGS))
override CONFIGS += -DVX_CFG_NUM_THREADS=$(NUM_THREADS) -DVX_CFG_NUM_WARPS=$(NUM_WARPS) -DVX_CFG_NUM_CORES=2
include $(ROOT_DIR)/config.mk

PROJECT := lrsc
TOP := VX_lsu_lrsc_top
SRC_DIR := $(VORTEX_HOME)/hw/unittest/$(PROJECT)
RTL_DIR := $(VORTEX_HOME)/hw/rtl
SRCS := $(SRC_DIR)/main.cpp
PARAMS := -GNUM_LANES=$(NUM_LANES)
CXXFLAGS := -DTEST_THREADS=$(NUM_THREADS) -DTEST_WARPS=$(NUM_WARPS) -DTEST_LANES=$(NUM_LANES)
CXXFLAGS += -DTEST_XLEN=$(XLEN) -I$(VORTEX_HOME)/sim/simx/amo
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv
RTL_INCLUDE := -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs -I$(RTL_DIR)/core -I$(SRC_DIR)
include ../common.mk

.PHONY: run-matrix
run-matrix:
	@set -e; for shape in 1:1:1 8:8:8 8:8:2 16:4:4 32:4:32; do \
	  threads=$${shape%%:*}; rest=$${shape#*:}; warps=$${rest%%:*}; lanes=$${rest##*:}; \
	  $(MAKE) clean; \
	  $(MAKE) run NUM_THREADS=$$threads NUM_WARPS=$$warps NUM_LANES=$$lanes; \
	done
