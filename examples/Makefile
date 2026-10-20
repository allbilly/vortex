ROOT_DIR := $(realpath ..)
include $(ROOT_DIR)/config.mk

OPS := simple_add elementwise gemm conv pooling
DRIVER ?= simx
PYTHON ?= python3

.PHONY: all runtime run clean $(OPS)
all: $(OPS)

$(OPS):
	$(MAKE) -C kernels/$@ all

runtime:
	$(MAKE) -C $(ROOT_DIR)/sw/runtime/stub
	$(MAKE) -C $(ROOT_DIR)/sw/runtime/$(DRIVER)

run: all runtime
	@set -e; for op in $(OPS); do \
	  $(PYTHON) $(VORTEX_HOME)/examples/$$op.py --build $(ROOT_DIR) --driver $(DRIVER); \
	done

clean:
	@set -e; for op in $(OPS); do $(MAKE) -C kernels/$$op clean; done
