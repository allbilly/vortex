ROOT_DIR := $(realpath ../..)
include $(ROOT_DIR)/config.mk

DRIVER ?= simx
PYTHON ?= python3

.PHONY: run clean
run: abi-check
	$(MAKE) -C $(ROOT_DIR)/examples all runtime DRIVER=$(DRIVER)
	$(PYTHON) $(VORTEX_HOME)/tests/examples/verify.py --build $(ROOT_DIR) --driver $(DRIVER)

abi-check: $(VORTEX_HOME)/tests/examples/abi.cpp $(VORTEX_HOME)/sw/runtime/include/vortex2.h $(VORTEX_HOME)/examples/kernels/common.h
	$(CXX) -std=c++17 -Wall -Wextra -Werror -I$(VORTEX_HOME)/sw/runtime/include -I$(VORTEX_HOME)/examples/kernels $< -o $@

clean:
	rm -f abi-check
