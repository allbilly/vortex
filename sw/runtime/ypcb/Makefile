include ../../../config.mk
include $(VORTEX_HOME)/hw/syn/xilinx/ypcb/config.mk
override CONFIGS += $(YPCB_CONFIGS)
include ../common.mk

SRC_DIR := $(VORTEX_HOME)/sw/runtime/ypcb
DESTDIR ?= $(CURDIR)/..
override DESTDIR := $(abspath $(DESTDIR))
CONFIG_HEADER := $(ROOT_DIR)/sw/ypcb/ypcb_ddr_config.h

CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Werror -fPIC -DNDEBUG
CXXFLAGS += -I$(INC_DIR) -I$(RT_COMMON_DIR) -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw
CXXFLAGS += -I$(ROOT_DIR)/sw/ypcb
LDFLAGS += -shared -pthread -Wl,-z,defs
SRCS := $(SRC_DIR)/vortex.cpp $(SW_COMMON_DIR)/ypcb_transport.cpp \
        $(SW_COMMON_DIR)/ypcb_calibration.cpp $(SW_COMMON_DIR)/ypcb_startup.cpp \
        $(SW_COMMON_DIR)/ypcb_host_memory.cpp $(SW_COMMON_DIR)/ypcb_jtag.cpp
HEADERS := $(wildcard $(SW_COMMON_DIR)/ypcb*.h) $(SW_COMMON_DIR)/mem_alloc.h \
           $(RT_COMMON_DIR)/callbacks.h $(RT_COMMON_DIR)/callbacks.inc $(CONFIG_HEADER)
HEADERS += $(wildcard $(RT_COMMON_DIR)/*.h) $(wildcard $(INC_DIR)/*.h)
HEADERS += $(ROOT_DIR)/sw/VX_config.h $(ROOT_DIR)/sw/VX_types.h
stamp_quote = '$(subst ','"'"',$(1))'

.PHONY: all clean force
all: $(DESTDIR)/libvortex-ypcb.so

config.stamp: force
	@stamp_tmp=$@.tmp.$$$$; printf '%s\n' $(call stamp_quote,$(CXX)) $(call stamp_quote,$(CXXFLAGS)) $(call stamp_quote,$(LDFLAGS)) > $$stamp_tmp; \
	 if ! cmp -s $$stamp_tmp $@; then mv -f $$stamp_tmp $@; else rm -f $$stamp_tmp; fi

$(DESTDIR)/libvortex-ypcb.so: $(SRCS) $(HEADERS) $(SRC_DIR)/Makefile config.stamp
	@test "$(MEMORY_SIZE)" = 2147483648 || { echo "Configure the YPCB build with --memory-size=2147483648" >&2; exit 1; }
	@test "$(XLEN)" = 32 || { echo 'YPCB requires the RV32 build' >&2; exit 1; }
	mkdir -p $(DESTDIR)
	$(CXX) $(CXXFLAGS) $(SRCS) $(LDFLAGS) -o $@

clean:
	rm -f $(DESTDIR)/libvortex-ypcb.so config.stamp
