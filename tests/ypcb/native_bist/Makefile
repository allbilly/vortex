ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/native_bist
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Werror -pthread
CXXFLAGS += -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw/ypcb
CONFIG_HEADER := $(ROOT_DIR)/sw/ypcb/ypcb_wl_config.h
SOURCES := $(SRC_DIR)/main.cpp $(SW_COMMON_DIR)/ypcb_jtag.cpp $(SW_COMMON_DIR)/ypcb_wl_calibration.cpp
HEADERS := $(SRC_DIR)/protocol.h $(CONFIG_HEADER) $(SW_COMMON_DIR)/ypcb_jtag.h $(SW_COMMON_DIR)/ypcb_wl_calibration.h $(SW_COMMON_DIR)/ypcb_transport.h

.PHONY: all test clean force
all: native_bist

stamp_quote = '$(subst ','"'"',$(1))'
config.stamp: force
	@stamp_tmp=$@.tmp.$$$$; printf '%s\n' $(call stamp_quote,$(CXX)) $(call stamp_quote,$(CXXFLAGS)) > $$stamp_tmp; \
	 if ! cmp -s $$stamp_tmp $@; then mv -f $$stamp_tmp $@; else rm -f $$stamp_tmp; fi

native_bist: $(SOURCES) $(HEADERS) $(SRC_DIR)/Makefile config.stamp
	@test "$(PROFILE)" = ypcb_blackwell_like_4gb || { echo 'Native full-range BIST requires the 4 GiB profile' >&2; exit 1; }
	$(CXX) $(CXXFLAGS) $(SOURCES) -o $@

protocol-test: $(SRC_DIR)/test.cpp $(HEADERS) $(SRC_DIR)/Makefile config.stamp
	$(CXX) $(CXXFLAGS) -UNDEBUG $(SRC_DIR)/test.cpp -o $@

test: protocol-test
	./protocol-test

clean:
	rm -f native_bist protocol-test config.stamp
