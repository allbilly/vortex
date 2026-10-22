ROOT_DIR := $(realpath ../../..)
NUM_INPUTS ?= 5
PIPE_DEPTH ?= 1
include $(ROOT_DIR)/config.mk

PROJECT := tcu_masked_max_exp
TOP := VX_tcu_tfr_masked_max_exp
SRC_DIR := $(VORTEX_HOME)/hw/unittest/$(PROJECT)
RTL_DIR := $(VORTEX_HOME)/hw/rtl
PARAMS := -GN=$(NUM_INPUTS) -GWIDTH=10 -GDEPTH=$(PIPE_DEPTH)
CXXFLAGS := -DTEST_N=$(NUM_INPUTS) -DTEST_WIDTH=10 -DTEST_DEPTH=$(PIPE_DEPTH)
SRCS := $(SRC_DIR)/main.cpp
RTL_INCLUDE := -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs -I$(RTL_DIR)/tcu/tfr

include ../common.mk

.PHONY: run-matrix
run-matrix:
	@set -e; for inputs in 5 9; do for depth in 0 1; do \
	  $(MAKE) clean; \
	  $(MAKE) run NUM_INPUTS=$$inputs PIPE_DEPTH=$$depth; \
	done; done
