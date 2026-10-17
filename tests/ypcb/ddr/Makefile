ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/ddr
CONFIG_DIR := $(ROOT_DIR)/sw/ypcb
PROJECT := ddr-host-test
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Werror -pthread
CXXFLAGS += -I$(SW_COMMON_DIR) -I$(CONFIG_DIR)

.PHONY: all run clean
all: $(PROJECT)

$(PROJECT): $(SRC_DIR)/main.cpp $(SW_COMMON_DIR)/ypcb_ddr.cpp $(SW_COMMON_DIR)/ypcb_ddr.h $(SW_COMMON_DIR)/ypcb_transport.h $(CONFIG_DIR)/ypcb_ddr_config.h
	$(CXX) $(CXXFLAGS) $(SRC_DIR)/main.cpp $(SW_COMMON_DIR)/ypcb_ddr.cpp -o $@

run: $(PROJECT)
	./$(PROJECT)

clean:
	rm -f $(PROJECT)
