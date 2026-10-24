ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/reservation
RT_DIR := $(ROOT_DIR)/sw/runtime
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Werror
CXXFLAGS += -I$(VORTEX_HOME)/sw/runtime/include -I$(VORTEX_HOME)/sw/runtime/common
CXXFLAGS += -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw
CXXFLAGS += $(shell python3 $(ROOT_DIR)/ci/gen_config.py --config=$(VORTEX_HOME)/VX_config.toml --cflags='$(CONFIGS) -DVX_CFG_XLEN=$(XLEN)')
HEADERS := $(SW_COMMON_DIR)/ypcb_host_memory.h $(SW_COMMON_DIR)/ypcb_transport.h $(SW_COMMON_DIR)/mem_alloc.h $(ROOT_DIR)/sw/VX_types.h $(ROOT_DIR)/sw/VX_config.h $(VORTEX_HOME)/VX_config.toml

.PHONY: all run clean
all: reservation-test libvortex-reservation-test.so

reservation-test: $(SRC_DIR)/main.cpp $(HEADERS) $(RT_DIR)/libvortex.so
	$(CXX) $(CXXFLAGS) $< -L$(RT_DIR) -Wl,-rpath,$(RT_DIR) -lvortex -ldl -o $@

libvortex-reservation-test.so: $(SRC_DIR)/backend.cpp $(VORTEX_HOME)/sw/runtime/common/callbacks.h
	$(CXX) $(CXXFLAGS) -fPIC -shared $< -ldl -o $@

run: all
	VORTEX_DRIVER=reservation-test LD_LIBRARY_PATH=$(CURDIR):$(RT_DIR) VORTEX_CP_POLL_TIMEOUT_S=10 timeout 120 ./reservation-test

clean:
	rm -f reservation-test libvortex-reservation-test.so
