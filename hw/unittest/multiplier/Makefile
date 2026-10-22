ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk
A_WIDTH ?= 33
B_WIDTH ?= 33
R_WIDTH ?= 66
SIGNED ?= 1
LATENCY ?= 3
PARTIAL_REG ?= $(if $(filter 0 1,$(LATENCY) $(A_WIDTH) $(B_WIDTH)),0,1)
PROJECT := multiplier
TOP := VX_multiplier
SRC_DIR := $(VORTEX_HOME)/hw/unittest/$(PROJECT)
RTL_DIR := $(VORTEX_HOME)/hw/rtl
SRCS := $(SRC_DIR)/main.cpp
PARAMS := -GA_WIDTH=$(A_WIDTH) -GB_WIDTH=$(B_WIDTH) -GR_WIDTH=$(R_WIDTH)
PARAMS += -GSIGNED=$(SIGNED) -GLATENCY=$(LATENCY) -GPARTIAL_REG=$(PARTIAL_REG)
CXXFLAGS := -DTEST_A=$(A_WIDTH) -DTEST_B=$(B_WIDTH) -DTEST_R=$(R_WIDTH)
CXXFLAGS += -DTEST_SIGNED=$(SIGNED) -DTEST_LAT=$(LATENCY)
RTL_INCLUDE := -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs
include ../common.mk
.PHONY: run-matrix
run-matrix:
	python3 $(SRC_DIR)/run.py
