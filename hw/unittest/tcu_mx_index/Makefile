ROOT_DIR := $(realpath ../../..)
override CONFIGS += -DVX_CFG_EXT_TCU_ENABLE
include $(ROOT_DIR)/config.mk

PROJECT := tcu_mx_index
TOP := VX_tcu_mx_index_top
SRC_DIR := $(VORTEX_HOME)/hw/unittest/$(PROJECT)
RTL_DIR := $(VORTEX_HOME)/hw/rtl

SRCS := $(SRC_DIR)/main.cpp
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv $(RTL_DIR)/tcu/VX_tcu_pkg.sv
RTL_INCLUDE := -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs -I$(RTL_DIR)/tcu -I$(SRC_DIR)

include ../common.mk
