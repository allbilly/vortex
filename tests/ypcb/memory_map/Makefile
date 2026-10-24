ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/memory_map
RT_DIR := $(ROOT_DIR)/sw/runtime
PROJECT := memory_map
DRIVER ?= simx
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Werror -I$(VORTEX_HOME)/sw/runtime/include
CXXFLAGS += -I$(ROOT_DIR)/sw
CXXFLAGS += $(shell python3 $(ROOT_DIR)/ci/gen_config.py --config=$(VORTEX_HOME)/VX_config.toml --cflags='$(CONFIGS) -DVX_CFG_XLEN=$(XLEN)')
.DEFAULT_GOAL := all

.PHONY: all run run-simx run-xrt clean force

all: $(PROJECT)

$(RT_DIR)/libvortex.so: force
	CONFIGS="$(CONFIGS)" $(MAKE) -C $(RT_DIR)/stub

config.stamp: force
	@TMP=$@.tmp.$$$$; printf '%s\n' '$(CXXFLAGS)' > $$TMP; \
	 if ! cmp -s $$TMP $@; then mv -f $$TMP $@; else rm -f $$TMP; fi

$(PROJECT): $(SRC_DIR)/main.cpp $(VORTEX_HOME)/sw/runtime/include/vortex2.h $(VORTEX_HOME)/VX_config.toml $(ROOT_DIR)/sw/VX_types.h $(ROOT_DIR)/sw/VX_config.h $(RT_DIR)/libvortex.so config.stamp
	$(CXX) $(CXXFLAGS) $< -L$(RT_DIR) -lvortex -o $@

raw-memory: $(SRC_DIR)/raw.cpp $(SW_COMMON_DIR)/ypcb_transport.cpp $(SW_COMMON_DIR)/ypcb_jtag.cpp $(SW_COMMON_DIR)/ypcb_transport.h $(SW_COMMON_DIR)/ypcb_jtag.h $(ROOT_DIR)/sw/ypcb/ypcb_wl_config.h config.stamp
	$(CXX) $(CXXFLAGS) -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw/ypcb -pthread $(filter %.cpp,$^) -o $@

run: $(PROJECT)
	CONFIGS="$(CONFIGS)" $(MAKE) -C $(RT_DIR)/$(DRIVER)
	LD_LIBRARY_PATH=$(RT_DIR):$(LD_LIBRARY_PATH) VORTEX_DRIVER=$(DRIVER) ./$(PROJECT)

run-simx: DRIVER=simx
run-simx: run

run-xrt: DRIVER=xrt
run-xrt: run

clean:
	rm -f $(PROJECT) raw-memory config.stamp
