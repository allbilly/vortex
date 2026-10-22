ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/hw/unittest/amo_reservation
OPTS ?=

.PHONY: all run
all:
	python3 $(SRC_DIR)/run.py --build $(ROOT_DIR) --output $(CURDIR)/compiled --verilator $(VERILATOR_PATH)/bin/verilator --cflags='-DVX_CFG_XLEN=$(XLEN) -DVX_CFG_XLEN_$(XLEN) $(CONFIGS)' --compile-only $(OPTS)

run:
	python3 $(SRC_DIR)/run.py --build $(ROOT_DIR) --output $(CURDIR)/results --verilator $(VERILATOR_PATH)/bin/verilator --cflags='-DVX_CFG_XLEN=$(XLEN) -DVX_CFG_XLEN_$(XLEN) $(CONFIGS)' $(OPTS)
