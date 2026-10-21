ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/shell
BOARD_DIR := $(VORTEX_HOME)/hw/syn/xilinx/ypcb
RTL_DIR := $(VORTEX_HOME)/hw/rtl
MODEL_DIR := $(CURDIR)/model
RUNTIME_DIR := $(ROOT_DIR)/sw/runtime
VERILATOR ?= $(VERILATOR_PATH)/bin/verilator
PROJECT := libvortex-ypcb-shell-test.so
include $(BOARD_DIR)/config.mk
BOARD_CONFIGS := $(CONFIGS) $(YPCB_CONFIGS)
BOARD_XCONFIGS := $(shell python3 $(ROOT_DIR)/ci/gen_config.py --config=$(VORTEX_HOME)/VX_config.toml --cflags='$(BOARD_CONFIGS) -DVX_CFG_XLEN=$(XLEN)')
TCU_ITYPE ?= fp16
TCU_OTYPE ?= fp32
TCU_K := $(if $(filter int8,$(TCU_ITYPE)),32,16)

RTL_FLAGS := -DVX_CFG_XLEN=32 -DVX_CFG_XLEN_32 -DVX_CFG_FPU_TYPE=STD -DVX_CFG_FPU_TYPE_STD
RTL_FLAGS += -DSIMULATION -DNDEBUG -DVX_CFG_PLATFORM_CLOCK_RATE=125
RTL_FLAGS += $(BOARD_CONFIGS)
RTL_FLAGS += $(filter -DVX_CFG_TCU_TYPE_%,$(BOARD_XCONFIGS))
RTL_FLAGS += -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(BOARD_DIR) -I$(RTL_DIR)/libs
RTL_FLAGS += -I$(RTL_DIR)/interfaces -I$(RTL_DIR)/core -I$(RTL_DIR)/mem -I$(RTL_DIR)/vm
RTL_FLAGS += -I$(RTL_DIR)/cache -I$(RTL_DIR)/fpu -I$(RTL_DIR)/cp
RTL_FLAGS += -I$(RTL_DIR)/afu/xrt -I$(RTL_DIR)/afu/common
RTL_FLAGS += -I$(RTL_DIR)/tcu -I$(RTL_DIR)/tcu/tfr
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv $(RTL_DIR)/fpu/VX_fpu_pkg.sv
ifneq ($(findstring -DVX_CFG_EXT_TCU_ENABLE,$(BOARD_CONFIGS)),)
RTL_PKGS += $(RTL_DIR)/tcu/VX_tcu_pkg.sv
endif
ifneq (,$(filter -DVX_CFG_EXT_DXA_ENABLE,$(BOARD_XCONFIGS)))
RTL_FLAGS += -I$(RTL_DIR)/dxa
RTL_PKGS += $(RTL_DIR)/dxa/VX_dxa_pkg.sv
endif
RTL_PKGS += $(RTL_DIR)/VX_trace_pkg.sv $(RTL_DIR)/cp/VX_cp_pkg.sv
RTL_SRCS := $(shell find "$(RTL_DIR)" -type f \( -name '*.sv' -o -name '*.v' -o -name '*.vh' \))
ifneq ($(.SHELLSTATUS),0)
$(error Unable to discover RTL sources under $(RTL_DIR))
endif
ifeq ($(strip $(RTL_SRCS)),)
$(error No RTL sources found under $(RTL_DIR))
endif
SRCS := $(SRC_DIR)/backend.cpp $(SW_COMMON_DIR)/ypcb_transport.cpp
SRCS += $(SW_COMMON_DIR)/ypcb_host_memory.cpp $(SW_COMMON_DIR)/ypcb_startup.cpp $(SW_COMMON_DIR)/util.cpp
HEADERS := $(wildcard $(SW_COMMON_DIR)/*.h) $(wildcard $(VORTEX_HOME)/sw/runtime/common/*.h)
HEADERS += $(VORTEX_HOME)/sw/runtime/common/callbacks.inc $(wildcard $(VORTEX_HOME)/sw/runtime/include/*.h)
HEADERS += $(ROOT_DIR)/sw/VX_config.h $(ROOT_DIR)/sw/VX_types.h
CXXFLAGS += -std=c++17 -O2 -DNDEBUG -Wall -Wextra -fPIC -fno-tree-loop-distribute-patterns
CXXFLAGS += -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw
CXXFLAGS += -I$(VORTEX_HOME)/sw/runtime/common -I$(VORTEX_HOME)/sw/runtime/include
CXXFLAGS += $(BOARD_CONFIGS)
CXXFLAGS += $(filter -DVX_CFG_TCU_TYPE_%,$(BOARD_XCONFIGS))

.PHONY: all run run-demo run-sgemm run-sgemm-tcu kernel-build force
all: $(PROJECT)

config.stamp: force
	@stamp_tmp=$@.tmp.$$$$; printf '%s\n' '$(CXX)' '$(VERILATOR)' '$(RTL_FLAGS)' '$(CXXFLAGS)' > $$stamp_tmp; \
	 if ! cmp -s $$stamp_tmp $@; then mv -f $$stamp_tmp $@; else rm -f $$stamp_tmp; fi

$(PROJECT): $(SRCS) $(HEADERS) $(RTL_SRCS) $(ROOT_DIR)/hw/VX_config.vh $(wildcard $(BOARD_DIR)/VX_ypcb_*.sv) $(SRC_DIR)/Makefile config.stamp
	$(VERILATOR) --build --cc --exe --assert -Wall -Wno-fatal --timescale 1ns/1ps -j 1 --top-module VX_ypcb_shell --Mdir $(MODEL_DIR) -o $(CURDIR)/$(PROJECT) $(RTL_FLAGS) "-GSCRUB_BASE_ADDR=64'h7ffffec0" "-GSCRUB_END_ADDR=64'h80000000" $(ROOT_DIR)/sim/xrtsim/verilator.vlt $(RTL_PKGS) $(BOARD_DIR)/VX_ypcb_shell.sv $(SRCS) -CFLAGS '$(CXXFLAGS)' -LDFLAGS '-shared -pthread -Wl,-z,defs'

run: all
	$(MAKE) -C $(ROOT_DIR)/tests/ypcb/memory_map CONFIGS='$(BOARD_CONFIGS)' STARTUP_ADDR=$(YPCB_STARTUP_ADDR)
	LD_LIBRARY_PATH=$(CURDIR):$(RUNTIME_DIR) VORTEX_DRIVER=ypcb-shell-test VORTEX_CP_POLL_TIMEOUT_S=120 $(ROOT_DIR)/tests/ypcb/memory_map/memory_map

kernel-build:
	$(MAKE) -C $(ROOT_DIR)/sw/kernel CONFIGS='$(BOARD_CONFIGS)' STARTUP_ADDR=$(YPCB_STARTUP_ADDR)

run-demo: all kernel-build
	$(MAKE) -C $(ROOT_DIR)/tests/regression/demo CONFIGS='$(BOARD_CONFIGS)' STARTUP_ADDR=$(YPCB_STARTUP_ADDR)
	cd $(ROOT_DIR)/tests/regression/demo && LD_LIBRARY_PATH=$(CURDIR):$(RUNTIME_DIR) VORTEX_DRIVER=ypcb-shell-test VORTEX_CP_POLL_TIMEOUT_S=120 ./demo -n64

run-sgemm: all kernel-build
	$(MAKE) -C $(ROOT_DIR)/tests/regression/sgemm CONFIGS='$(BOARD_CONFIGS)' STARTUP_ADDR=$(YPCB_STARTUP_ADDR)
	cd $(ROOT_DIR)/tests/regression/sgemm && LD_LIBRARY_PATH=$(CURDIR):$(RUNTIME_DIR) VORTEX_DRIVER=ypcb-shell-test VORTEX_CP_POLL_TIMEOUT_S=120 ./sgemm -n16

run-sgemm-tcu: all kernel-build
	$(MAKE) -C $(ROOT_DIR)/tests/regression/sgemm_tcu CONFIGS='$(BOARD_CONFIGS) -DITYPE=$(TCU_ITYPE) -DOTYPE=$(TCU_OTYPE)' STARTUP_ADDR=$(YPCB_STARTUP_ADDR)
	cd $(ROOT_DIR)/tests/regression/sgemm_tcu && LD_LIBRARY_PATH=$(CURDIR):$(RUNTIME_DIR) VORTEX_DRIVER=ypcb-shell-test VORTEX_CP_POLL_TIMEOUT_S=120 ./sgemm_tcu -m16 -n16 -k$(TCU_K) -r2
