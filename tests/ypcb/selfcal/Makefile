ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/selfcal
FW_DIR := $(VORTEX_HOME)/hw/syn/xilinx/ypcb/selfcal_fw
HEADERS := $(wildcard $(SW_COMMON_DIR)/ypcb*.h) $(FW_DIR)/calibrate.h
DDR_DIR ?= $(ROOT_DIR)/hw/syn/xilinx/ypcb/ddr
VERILATOR ?= $(VERILATOR_PATH)/bin/verilator
CFLAGS += -std=c11 -O2 -Wall -Wextra -Werror -DCAL_HOST
CFLAGS += -I$(DDR_DIR)/selfcal_fw -I$(SW_COMMON_DIR)
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Werror -pthread
CXXFLAGS += -I$(FW_DIR) -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw/ypcb

.PHONY: all run rtl-test clean
all: selfcal-host-test

firmware.o: $(FW_DIR)/calibrate.c $(FW_DIR)/calibrate.h $(FW_DIR)/io.h $(SW_COMMON_DIR)/ypcb_calibration_abi.h $(DDR_DIR)/selfcal_fw/config.h
	$(CC) $(CFLAGS) -c $< -o $@

selfcal-host-test: $(SRC_DIR)/main.cpp $(VORTEX_HOME)/tests/ypcb/ddr/oracle.h firmware.o $(SW_COMMON_DIR)/ypcb_ddr.cpp $(SW_COMMON_DIR)/ypcb_calibration.cpp $(ROOT_DIR)/sw/ypcb/ypcb_ddr_config.h $(HEADERS)
	$(CXX) $(CXXFLAGS) $(SRC_DIR)/main.cpp firmware.o $(SW_COMMON_DIR)/ypcb_ddr.cpp $(SW_COMMON_DIR)/ypcb_calibration.cpp -o $@

run: selfcal-host-test
	./selfcal-host-test

read-report: $(SRC_DIR)/read_report.cpp $(SW_COMMON_DIR)/ypcb_calibration.cpp $(SW_COMMON_DIR)/ypcb_jtag.cpp $(HEADERS) $(ROOT_DIR)/sw/ypcb/ypcb_ddr_config.h
	$(CXX) $(CXXFLAGS) $(SRC_DIR)/read_report.cpp $(SW_COMMON_DIR)/ypcb_calibration.cpp $(SW_COMMON_DIR)/ypcb_jtag.cpp -o $@

RTL_DIR ?= $(CURDIR)/rtl-test
RTL_BOOT_FIRMWARE ?= $(DDR_DIR)/selfcal_fw/firmware.bin
LITEDRAM_PYTHONPATH ?= $(ROOT_DIR)/open-reference/migen:$(ROOT_DIR)/open-reference/litex:$(ROOT_DIR)/open-reference/litedram
rtl-test:
	env PYTHONPATH=$(LITEDRAM_PYTHONPATH) python3 $(VORTEX_HOME)/hw/syn/xilinx/ypcb/tests/gen_selfcal.py --firmware $(RTL_BOOT_FIRMWARE) --output $(RTL_DIR)/selfcal_top.v
	$(VERILATOR) --cc --exe --build -j 1 --assert -Wno-fatal --top-module selfcal_top --Mdir $(RTL_DIR)/obj -o selfcal-rtl $(RTL_DIR)/selfcal_top.v $(SRC_DIR)/rtl.cpp -CFLAGS '$(CXXFLAGS) -I$(DDR_DIR)/selfcal_fw'
	$(RTL_DIR)/obj/selfcal-rtl $(DDR_DIR)/selfcal_fw/firmware.bin

clean:
	rm -f firmware.o selfcal-host-test read-report
