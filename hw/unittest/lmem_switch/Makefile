ROOT_DIR := $(realpath ../../..)
override CONFIGS += -DVX_CFG_NUM_LSU_LANES=2
include $(ROOT_DIR)/config.mk
SRC_DIR := $(VORTEX_HOME)/hw/unittest/lmem_switch
OPTS ?=
.PHONY: all run clean
all:
	python3 $(SRC_DIR)/run.py --build $(ROOT_DIR) --output $(CURDIR)/compiled --verilator $(VERILATOR_PATH)/bin/verilator --configs='$(CONFIGS)' --compile-only $(OPTS)
run:
	python3 $(SRC_DIR)/run.py --build $(ROOT_DIR) --output $(CURDIR)/results --verilator $(VERILATOR_PATH)/bin/verilator --configs='$(CONFIGS)' $(OPTS)

clean:
	rm -rf compiled results
