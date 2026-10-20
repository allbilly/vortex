ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/examples/kernels/$(PROJECT)
VX_SRCS := $(SRC_DIR)/kernel.cpp
VX_HDRS := $(SRC_DIR)/../common.h
KERNEL_LIB := vortex2

include ../../../tests/regression/common.mk
