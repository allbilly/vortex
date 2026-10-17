ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/shell
BOARD_DIR := $(VORTEX_HOME)/hw/syn/xilinx/ypcb
RTL_DIR := $(VORTEX_HOME)/hw/rtl
MODEL_DIR := $(CURDIR)/model
RUNTIME_DIR := $(ROOT_DIR)/sw/runtime
VERILATOR ?= $(VERILATOR_PATH)/bin/verilator
PROJECT := libvortex-ypcb-shell-test.so
BOARD_CONFIGS := -DVX_CFG_FPU_TYPE=STD -DVX_CFG_PLATFORM_CLOCK_RATE=125
BOARD_CONFIGS += -DVX_CFG_PLATFORM_MEMORY_PEAK_BW=12800

RTL_FLAGS := -DVX_CFG_XLEN=32 -DVX_CFG_XLEN_32 -DVX_CFG_FPU_TYPE=STD -DVX_CFG_FPU_TYPE_STD
RTL_FLAGS += -DSIMULATION -DNDEBUG -DVX_CFG_PLATFORM_CLOCK_RATE=125
RTL_FLAGS += -DVX_CFG_PLATFORM_MEMORY_PEAK_BW=12800
RTL_FLAGS += -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(BOARD_DIR) -I$(RTL_DIR)/libs
RTL_FLAGS += -I$(RTL_DIR)/interfaces -I$(RTL_DIR)/core -I$(RTL_DIR)/mem -I$(RTL_DIR)/vm
RTL_FLAGS += -I$(RTL_DIR)/cache -I$(RTL_DIR)/fpu -I$(RTL_DIR)/cp
RTL_FLAGS += -I$(RTL_DIR)/afu/xrt -I$(RTL_DIR)/afu/common
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv $(RTL_DIR)/fpu/VX_fpu_pkg.sv
RTL_PKGS += $(RTL_DIR)/VX_trace_pkg.sv $(RTL_DIR)/cp/VX_cp_pkg.sv
RTL_SRCS := $(shell rg --files $(RTL_DIR) -g '*.sv' -g '*.v' -g '*.vh')
SRCS := $(SRC_DIR)/backend.cpp $(SW_COMMON_DIR)/ypcb_transport.cpp
SRCS += $(SW_COMMON_DIR)/ypcb_host_memory.cpp $(SW_COMMON_DIR)/ypcb_startup.cpp $(SW_COMMON_DIR)/util.cpp
HEADERS := $(wildcard $(SW_COMMON_DIR)/*.h) $(wildcard $(VORTEX_HOME)/sw/runtime/common/*.h)
HEADERS += $(VORTEX_HOME)/sw/runtime/common/callbacks.inc $(wildcard $(VORTEX_HOME)/sw/runtime/include/*.h)
HEADERS += $(ROOT_DIR)/sw/VX_config.h $(ROOT_DIR)/sw/VX_types.h
CXXFLAGS += -std=c++17 -O2 -DNDEBUG -Wall -Wextra -fPIC -fno-tree-loop-distribute-patterns
CXXFLAGS += -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw
CXXFLAGS += -I$(VORTEX_HOME)/sw/runtime/common -I$(VORTEX_HOME)/sw/runtime/include
CXXFLAGS += $(BOARD_CONFIGS)

.PHONY: all run run-demo run-sgemm kernel-build force
all: $(PROJECT)

config.stamp: force
	@stamp_tmp=$@.tmp.$$$$; printf '%s\n' '$(CXX)' '$(VERILATOR)' '$(RTL_FLAGS)' '$(CXXFLAGS)' > $$stamp_tmp; \
	 if ! cmp -s $$stamp_tmp $@; then mv -f $$stamp_tmp $@; else rm -f $$stamp_tmp; fi

$(PROJECT): $(SRCS) $(HEADERS) $(RTL_SRCS) $(ROOT_DIR)/hw/VX_config.vh $(wildcard $(BOARD_DIR)/VX_ypcb_*.sv) $(SRC_DIR)/Makefile config.stamp
	$(VERILATOR) --build --cc --exe --assert -Wall -Wno-fatal --timescale 1ns/1ps -j 2 --top-module VX_ypcb_shell --Mdir $(MODEL_DIR) -o $(CURDIR)/$(PROJECT) $(RTL_FLAGS) "-GSCRUB_BASE_ADDR=64'h7fffffc0" "-GSCRUB_END_ADDR=64'h80000100" $(ROOT_DIR)/sim/xrtsim/verilator.vlt $(RTL_PKGS) $(BOARD_DIR)/VX_ypcb_shell.sv $(SRCS) -CFLAGS '$(CXXFLAGS)' -LDFLAGS '-shared -pthread -Wl,-z,defs'

run: all
	$(MAKE) -C $(ROOT_DIR)/tests/ypcb/memory_map CONFIGS='$(BOARD_CONFIGS)'
	LD_LIBRARY_PATH=$(CURDIR):$(RUNTIME_DIR) VORTEX_DRIVER=ypcb-shell-test VORTEX_CP_POLL_TIMEOUT_S=120 $(ROOT_DIR)/tests/ypcb/memory_map/memory_map

kernel-build:
	$(MAKE) -B -C $(ROOT_DIR)/sw/kernel CONFIGS='$(BOARD_CONFIGS)'

run-demo: all kernel-build
	$(MAKE) -C $(ROOT_DIR)/tests/regression/demo CONFIGS='$(BOARD_CONFIGS)'
	cd $(ROOT_DIR)/tests/regression/demo && LD_LIBRARY_PATH=$(CURDIR):$(RUNTIME_DIR) VORTEX_DRIVER=ypcb-shell-test VORTEX_CP_POLL_TIMEOUT_S=120 ./demo -n64

run-sgemm: all kernel-build
	$(MAKE) -C $(ROOT_DIR)/tests/regression/sgemm CONFIGS='$(BOARD_CONFIGS)'
	cd $(ROOT_DIR)/tests/regression/sgemm && LD_LIBRARY_PATH=$(CURDIR):$(RUNTIME_DIR) VORTEX_DRIVER=ypcb-shell-test VORTEX_CP_POLL_TIMEOUT_S=120 ./sgemm -n16
