ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/hw/unittest/dxa_setup
OPTS ?=

.PHONY: all run
all:
	python3 $(SRC_DIR)/run.py --build $(ROOT_DIR) --output $(CURDIR)/compiled --verilator $(VERILATOR_PATH)/bin/verilator --compile-only $(OPTS)

run:
	python3 $(SRC_DIR)/run.py --build $(ROOT_DIR) --output $(CURDIR)/results --verilator $(VERILATOR_PATH)/bin/verilator $(OPTS)
