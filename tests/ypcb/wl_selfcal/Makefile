ROOT_DIR := $(realpath ../../..)
include $(ROOT_DIR)/config.mk

SRC_DIR := $(VORTEX_HOME)/tests/ypcb/wl_selfcal
FW_DIR := $(VORTEX_HOME)/hw/syn/xilinx/ypcb/opentpu/selfcal_fw
DDR_DIR ?= $(ROOT_DIR)/hw/syn/xilinx/ypcb/ddr
CFLAGS += -std=c11 -O2 -Wall -Wextra -Werror -fno-builtin -shared -fPIC
VERILATOR ?= $(VERILATOR_PATH)/bin/verilator
RTL_DIR ?= $(CURDIR)/cpu-test
LITEDRAM_PYTHONPATH ?= $(ROOT_DIR)/open-reference/migen:$(ROOT_DIR)/open-reference/litex:$(ROOT_DIR)/open-reference/litedram

.PHONY: all run cpu-test report-test clean
all: libwl-selfcal.so libwl-arith.so

libwl-selfcal.so: $(FW_DIR)/cal.c $(FW_DIR)/main.c $(FW_DIR)/host.c $(FW_DIR)/cal.h $(FW_DIR)/hw.h $(DDR_DIR)/selfcal_fw/selfcal_cfg.h
	$(CC) $(CFLAGS) -DSELFCAL_HOST -I$(DDR_DIR)/selfcal_fw -I$(FW_DIR) $(filter %.c,$^) -o $@

libwl-arith.so: $(FW_DIR)/arith.c
	$(CC) $(CFLAGS) $< -o $@

run: all
	python3 $(SRC_DIR)/verify.py --library $(CURDIR)/libwl-selfcal.so --arithmetic $(CURDIR)/libwl-arith.so --ddr $(DDR_DIR)

cpu-test: libwl-arith.so
	env PYTHONPATH=$(LITEDRAM_PYTHONPATH) python3 $(VORTEX_HOME)/hw/syn/xilinx/ypcb/tests/gen_selfcal.py --firmware $(DDR_DIR)/selfcal_fw/firmware.bin --output $(RTL_DIR)/selfcal_top.v
	$(VERILATOR) --cc --build -j 1 --assert -Wno-fatal --top-module selfcal_top --Mdir $(RTL_DIR)/obj $(RTL_DIR)/selfcal_top.v -CFLAGS '-fPIC'
	$(MAKE) -j1 -C $(RTL_DIR)/obj -f Vselfcal_top.mk verilated.o verilated_threads.o verilated_dpi.o
	$(CXX) -std=c++17 -O2 -Wall -Wextra -Werror -fPIC -shared -pthread -I$(RTL_DIR)/obj -I$(DDR_DIR)/selfcal_fw -isystem $(VERILATOR_PATH)/share/verilator/include -isystem $(VERILATOR_PATH)/share/verilator/include/vltstd $(SRC_DIR)/cpu.cpp $(RTL_DIR)/obj/Vselfcal_top__ALL.a $(RTL_DIR)/obj/verilated.o $(RTL_DIR)/obj/verilated_threads.o $(RTL_DIR)/obj/verilated_dpi.o -latomic -o $(RTL_DIR)/libwl-cpu.so
	python3 $(SRC_DIR)/verify.py --library $(RTL_DIR)/libwl-cpu.so --arithmetic $(CURDIR)/libwl-arith.so --ddr $(DDR_DIR) --cpu --case per_bit --case clock_error

wl-report-test: $(SRC_DIR)/report.cpp $(SW_COMMON_DIR)/ypcb_wl_calibration.cpp $(SW_COMMON_DIR)/ypcb_wl_calibration.h $(ROOT_DIR)/sw/ypcb/ypcb_wl_config.h
	$(CXX) -std=c++17 -O2 -Wall -Wextra -Werror -pthread -I$(SW_COMMON_DIR) -I$(ROOT_DIR)/sw/ypcb $(SRC_DIR)/report.cpp $(SW_COMMON_DIR)/ypcb_wl_calibration.cpp -o $@

report-test: wl-report-test
	./wl-report-test $(REPORT_FIXTURE)

clean:
	rm -f libwl-selfcal.so libwl-arith.so wl-report-test
