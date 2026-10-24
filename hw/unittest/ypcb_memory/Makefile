TASK_BUILD := $(realpath ../../../../build32)
include $(TASK_BUILD)/config.mk
SRC_DIR := $(VORTEX_HOME)/hw/unittest/ypcb_memory
OUTPUT ?= $(TASK_BUILD)/unittest-ypcb-memory

.PHONY: all run compile-only clean

all: run

run:
	python3 $(SRC_DIR)/run.py --build $(TASK_BUILD) --output $(OUTPUT) --verilator $(VERILATOR_PATH)/bin/verilator

compile-only:
	python3 $(SRC_DIR)/run.py --build $(TASK_BUILD) --output $(OUTPUT) --verilator $(VERILATOR_PATH)/bin/verilator --compile-only

clean:
	rm -rf $(OUTPUT)
