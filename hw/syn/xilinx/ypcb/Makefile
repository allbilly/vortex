ROOT_DIR := $(realpath ../../../..)
include $(ROOT_DIR)/config.mk
include $(VORTEX_HOME)/hw/syn/common.mk
include $(VORTEX_HOME)/hw/syn/xilinx/ypcb/config.mk

DEVICE := xc7k480tffg1156-2
TOP := vortex_afu
SRC_DIR := $(VORTEX_HOME)/hw/syn/xilinx/ypcb
RTL_DIR := $(VORTEX_HOME)/hw/rtl
OUT_DIR := $(CURDIR)/afu
VIVADO ?= vivado
LITEDRAM_PYTHON ?= python3
IVERILOG ?= iverilog
VVP ?= vvp
LITEDRAM_PYTHONPATH ?= $(ROOT_DIR)/open-reference/migen:$(ROOT_DIR)/open-reference/litex:$(ROOT_DIR)/open-reference/litedram:$(ROOT_DIR)/open-python-deps
DDR_OUT_DIR ?= $(CURDIR)/ddr
DDR_CONFIG_HEADER := $(ROOT_DIR)/sw/ypcb/ypcb_ddr_config.h
MEMORY_NUM_INPUTS ?= 4
SLANG_PLUGIN ?= $(ROOT_DIR)/tools-build/sv-elab/slang.so
SCRUB_TEST_DIR ?= $(CURDIR)/scrub-test
SCOPEINFO_TEST_DIR ?= $(CURDIR)/scopeinfo-test
.DEFAULT_GOAL := open-synth
BOARD_OUT_DIR ?= $(CURDIR)/board
BOARD_AFU_DIR ?= $(BOARD_OUT_DIR)/afu
BOARD_AFU_RTLIL ?= $(BOARD_AFU_DIR)/vortex_afu_slang.il
PCIE_REFERENCE ?= $(ROOT_DIR)/open-reference/pcie_7x
PCIE_SRC_DIR ?= $(BOARD_OUT_DIR)/pcie-patched/src
BOARD_CFLAGS := -I$(SRC_DIR) -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs
BOARD_CFLAGS += -DVX_CFG_XLEN=32 -DVX_CFG_XLEN_32 -DVX_CFG_FPU_TYPE=STD -DSYNTHESIS -DVIVADO -DNDEBUG
BOARD_SOURCES := $(wildcard $(SRC_DIR)/VX_ypcb_*.sv) $(SRC_DIR)/ypcb_top.sv

# Use the synthesizable RTL FPU, with the same choice in the simulation oracle.
override CONFIGS += $(YPCB_CONFIGS) -DSYNTHESIS -DVIVADO -DNDEBUG
XCONFIGS := $(shell python3 $(ROOT_DIR)/ci/gen_config.py --config=$(VORTEX_HOME)/VX_config.toml --cflags='$(CONFIGS) -DVX_CFG_XLEN=$(XLEN)')
CFLAGS := -DVX_CFG_XLEN=$(XLEN) -DVX_CFG_XLEN_$(XLEN) $(CONFIGS)
CFLAGS += $(filter -DVX_CFG_FPU_TYPE_%,$(XCONFIGS))
CFLAGS += -I$(ROOT_DIR)/hw -I$(RTL_DIR) -I$(RTL_DIR)/libs -I$(RTL_DIR)/interfaces
CFLAGS += -I$(RTL_DIR)/core -I$(RTL_DIR)/mem -I$(RTL_DIR)/vm -I$(RTL_DIR)/cache
CFLAGS += -I$(RTL_DIR)/fpu -I$(RTL_DIR)/cp -I$(RTL_DIR)/afu/common -I$(RTL_DIR)/afu/xrt
RTL_PKGS := $(RTL_DIR)/VX_gpu_pkg.sv $(RTL_DIR)/fpu/VX_fpu_pkg.sv

.PHONY: sources open-sv2v open-synth frontend-test frontend-slang-test open-slang-import open-slang-synth ddr-sources ddr-host-config ddr-host-test ddr-synth cdc-sources cdc-test wb-cdc-sources wb-cdc-test memory-test pio-test pio-host-test pio-memory-test pio-synth pcie-test pcie-synth control-test control-synth control-mapped-test ddr-control-test ddr-control-synth startup-test startup-host-test startup-synth scrub-test elaborate synth
.PHONY: afu-control-test board-sv2v board-bind board-constraints board-afu board-synth board-pcie
.PHONY: shell-test-build shell-test scopeinfo-test

scopeinfo-test:
	python3 $(SRC_DIR)/tests/scopeinfo.py --yosys $(YOSYS) --iverilog $(IVERILOG) --vvp $(VVP) --output $(SCOPEINFO_TEST_DIR)

shell-test-build:
	$(MAKE) -C $(ROOT_DIR)/tests/ypcb/shell VERILATOR=$(VERILATOR)

shell-test: shell-test-build
	$(MAKE) -C $(ROOT_DIR)/tests/ypcb/shell run VERILATOR=$(VERILATOR)

board-pcie:
	python3 $(SRC_DIR)/stage_pcie.py --source $(PCIE_REFERENCE) --output $(BOARD_OUT_DIR)/pcie-patched

board-afu:
	$(MAKE) open-slang-import OUT_DIR=$(BOARD_AFU_DIR) CONFIGS='$(CONFIGS) -DVX_CFG_PLATFORM_CLOCK_RATE=125'

board-synth: board-bind
	$(YOSYS) -l $(BOARD_OUT_DIR)/yosys-synth.log -p 'read_rtlil $(BOARD_OUT_DIR)/ypcb_bound.il; synth_xilinx -family xc7 -top ypcb_top -flatten -run begin:prepare; write_rtlil $(BOARD_OUT_DIR)/ypcb_begin.il; synth_xilinx -family xc7 -top ypcb_top -flatten -run prepare:map_dsp; write_rtlil $(BOARD_OUT_DIR)/ypcb_prepare.il; synth_xilinx -family xc7 -top ypcb_top -flatten -run map_dsp:map_luts; write_rtlil $(BOARD_OUT_DIR)/ypcb_pre_luts.il; synth_xilinx -family xc7 -top ypcb_top -run map_luts:; delete t:$$scopeinfo; check -assert; select -assert-none ypcb_top/t:$$*; stat; write_json $(BOARD_OUT_DIR)/ypcb.json'

board-constraints:
	python3 $(SRC_DIR)/gen_constraints.py --reference $(ROOT_DIR)/board_reference --package $(ROOT_DIR)/board_reference/package_pins-xc7k480tffg1156-2.csv --audit $(ROOT_DIR)/board-pin-audit.json --top $(SRC_DIR)/ypcb_top.sv --output $(BOARD_OUT_DIR)/ypcb-reference.xdc

afu-control-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_afu_control --Mdir $(CURDIR)/afu-control-test -o afu-control-test $(SRC_DIR)/VX_ypcb_afu_control.sv $(SRC_DIR)/tests/afu_control.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror'
	$(CURDIR)/afu-control-test/afu-control-test

board-sv2v:
	mkdir -p $(BOARD_OUT_DIR)
	$(SV2V) --top=ypcb_top $(BOARD_CFLAGS) -y $(RTL_DIR)/libs $(BOARD_SOURCES) -w $(BOARD_OUT_DIR)/ypcb_top.v

board-bind: board-sv2v board-pcie
	@test -s $(BOARD_AFU_RTLIL) || { echo 'Import the actual 125 MHz board AFU with board-afu first' >&2; exit 1; }
	$(YOSYS) -l $(BOARD_OUT_DIR)/yosys-bind.log -p 'read_rtlil $(BOARD_AFU_RTLIL); read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v; read_verilog -noautowire $(BOARD_OUT_DIR)/ypcb_top.v $(DDR_OUT_DIR)/gateware/ypcb_ddr3.v $(CURDIR)/cdc/ypcb_axi_cdc.v $(CURDIR)/wb-cdc/ypcb_wb_cdc.v; read_verilog -defer -noautowire $(PCIE_SRC_DIR)/xilinx_pcie_mmcm.v $(PCIE_SRC_DIR)/pcie_7x.v $(PCIE_SRC_DIR)/pcie_axi_rx.v $(PCIE_SRC_DIR)/pcie_axi_tx.v $(PCIE_SRC_DIR)/pcie_block.v $(PCIE_SRC_DIR)/pcie_brams.v $(PCIE_SRC_DIR)/pcie_tx_thrtl_ctl.v $(PCIE_SRC_DIR)/pipe_wrapper_gtx.v; hierarchy -check -top ypcb_top; proc; opt_clean; check -assert; stat; write_rtlil $(BOARD_OUT_DIR)/ypcb_bound.il'

sources:
	@test "$(XLEN)" = 32 || { echo "YPCB preparation uses its own RV32 build directory" >&2; exit 1; }
	mkdir -p $(OUT_DIR)
	printf '%s\n' '$(CFLAGS)' > $(OUT_DIR)/config.flags
	$(VORTEX_HOME)/hw/scripts/gen_sources.sh $(CFLAGS) -T$(TOP) -P -C$(OUT_DIR)/src -O$(OUT_DIR)/sources.txt $(RTL_PKGS)

open-sv2v: frontend-test sources
	$(VORTEX_HOME)/hw/scripts/sv2v.sh -t$(TOP) -I$(OUT_DIR)/src -o$(OUT_DIR)/vortex_afu.v

open-synth: open-sv2v
	$(YOSYS) -l $(OUT_DIR)/yosys.log -p 'read_verilog $(OUT_DIR)/vortex_afu.v; synth_xilinx -family xc7 -top $(TOP) -flatten -noiopad -noclkbuf -run begin:map_luts; write_rtlil $(OUT_DIR)/vortex_afu_pre_luts.il; synth_xilinx -family xc7 -top $(TOP) -noiopad -noclkbuf -run map_luts:; delete t:$$scopeinfo; check -assert; select -assert-none $(TOP)/t:$$*; write_json $(OUT_DIR)/vortex_afu.json; write_verilog $(OUT_DIR)/vortex_afu_mapped.v; stat'

frontend-test:
	mkdir -p $(CURDIR)/frontend-test
	$(SV2V) --top=VX_ypcb_frontend_test -v -w $(CURDIR)/frontend-test/frontend.v $(SRC_DIR)/tests/frontend.sv
	$(YOSYS) -l $(CURDIR)/frontend-test/yosys.log -p 'read_verilog -noautowire $(CURDIR)/frontend-test/frontend.v; prep -top VX_ypcb_frontend_test; flatten; opt; check -assert; sat -verify -prove correct 1 -show value'

frontend-slang-test:
	@test -s $(SLANG_PLUGIN) || { echo 'Build the pinned Slang plugin against this Yosys first' >&2; exit 1; }
	mkdir -p $(CURDIR)/frontend-slang-test
	$(YOSYS) -m $(SLANG_PLUGIN) -l $(CURDIR)/frontend-slang-test/yosys.log -p 'read_slang --top VX_ypcb_frontend_test $(SRC_DIR)/tests/frontend.sv; prep -top VX_ypcb_frontend_test; flatten; opt; check -assert; sat -verify -prove correct 1 -show value'

open-slang-import: frontend-slang-test sources
	$(YOSYS) -m $(SLANG_PLUGIN) -l $(OUT_DIR)/yosys-slang-import.log -p 'read_slang --top $(TOP) -f $(OUT_DIR)/sources.txt; check -assert; stat; write_rtlil $(OUT_DIR)/vortex_afu_slang.il'

open-slang-synth: open-slang-import
	$(YOSYS) -l $(OUT_DIR)/yosys-slang-synth.log -p 'read_rtlil $(OUT_DIR)/vortex_afu_slang.il; synth_xilinx -family xc7 -top $(TOP) -flatten -noiopad -noclkbuf -run begin:map_luts; write_rtlil $(OUT_DIR)/vortex_afu_slang_pre_luts.il; synth_xilinx -family xc7 -top $(TOP) -noiopad -noclkbuf -run map_luts:; delete t:$$scopeinfo; check -assert; select -assert-none $(TOP)/t:$$*; stat; write_json $(OUT_DIR)/vortex_afu_slang.json'

ddr-sources:
	env PYTHONPATH=$(LITEDRAM_PYTHONPATH) $(LITEDRAM_PYTHON) -m litedram.gen $(SRC_DIR)/litedram.yml --name=ypcb_ddr3 --no-compile-software --no-compile-gateware --output-dir=$(DDR_OUT_DIR)

ddr-host-config:
	python3 $(VORTEX_HOME)/ci/ypcb_ddr_config.py --ddr $(DDR_OUT_DIR) --output $(DDR_CONFIG_HEADER)

ddr-host-test: ddr-host-config
	$(MAKE) -C $(ROOT_DIR)/tests/ypcb/ddr run

cdc-sources:
	env PYTHONPATH=$(LITEDRAM_PYTHONPATH) $(LITEDRAM_PYTHON) $(SRC_DIR)/gen_cdc.py --output $(CURDIR)/cdc/ypcb_axi_cdc.v

cdc-test: cdc-sources
	@test -f $(CURDIR)/cdc/FDPE.v || { echo 'Stage the Yosys FDPE simulation cell with tests/stage_fdpe.py first' >&2; exit 1; }
	$(IVERILOG) -g2012 -Wall -I$(CURDIR)/cdc -s cdc_tb -o $(CURDIR)/cdc/test-bus.vvp $(CURDIR)/cdc/ypcb_axi_cdc.v $(CURDIR)/cdc/FDPE.v $(SRC_DIR)/tests/cdc_tb.sv
	$(VVP) $(CURDIR)/cdc/test-bus.vvp
	$(IVERILOG) -g2012 -Wall -I$(CURDIR)/cdc -s cdc_tb -Pcdc_tb.BUS_HALF=9 -Pcdc_tb.MEMORY_HALF=4 -Pcdc_tb.PHASE=1 -Pcdc_tb.RESET_MEMORY=1 -o $(CURDIR)/cdc/test-memory.vvp $(CURDIR)/cdc/ypcb_axi_cdc.v $(CURDIR)/cdc/FDPE.v $(SRC_DIR)/tests/cdc_tb.sv
	$(VVP) $(CURDIR)/cdc/test-memory.vvp

wb-cdc-sources:
	env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$(LITEDRAM_PYTHONPATH) $(LITEDRAM_PYTHON) $(SRC_DIR)/gen_wb_cdc.py --output $(CURDIR)/wb-cdc/ypcb_wb_cdc.v

wb-cdc-test: wb-cdc-sources
	python3 $(SRC_DIR)/tests/stage_fdpe.py $(YOSYS_PATH)/share/yosys/xilinx/cells_sim.v $(CURDIR)/wb-cdc/FDPE.v
	$(IVERILOG) -g2012 -Wall -I$(CURDIR)/wb-cdc -s wb_cdc_tb -o $(CURDIR)/wb-cdc/test-bus.vvp $(CURDIR)/wb-cdc/ypcb_wb_cdc.v $(CURDIR)/wb-cdc/FDPE.v $(SRC_DIR)/tests/wb_cdc_tb.sv
	$(VVP) $(CURDIR)/wb-cdc/test-bus.vvp
	$(IVERILOG) -g2012 -Wall -I$(CURDIR)/wb-cdc -s wb_cdc_tb -Pwb_cdc_tb.BUS_HALF=9 -Pwb_cdc_tb.MEMORY_HALF=4 -Pwb_cdc_tb.PHASE=1 -Pwb_cdc_tb.RESET_MEMORY=1 -o $(CURDIR)/wb-cdc/test-memory.vvp $(CURDIR)/wb-cdc/ypcb_wb_cdc.v $(CURDIR)/wb-cdc/FDPE.v $(SRC_DIR)/tests/wb_cdc_tb.sv
	$(VVP) $(CURDIR)/wb-cdc/test-memory.vvp

ddr-synth: $(DDR_OUT_DIR)/ypcb_ddr3_xc7.json

$(DDR_OUT_DIR)/ypcb_ddr3_pre_luts.il: $(DDR_OUT_DIR)/gateware/ypcb_ddr3.v $(SRC_DIR)/Makefile
	$(YOSYS) -l $(DDR_OUT_DIR)/yosys-pre-luts.log -p 'read_verilog $<; synth_xilinx -family xc7 -top ypcb_ddr3 -flatten -run begin:map_luts; write_rtlil $@'

$(DDR_OUT_DIR)/ypcb_ddr3_xc7.json: $(DDR_OUT_DIR)/ypcb_ddr3_pre_luts.il $(SRC_DIR)/Makefile
	$(YOSYS) -l $(DDR_OUT_DIR)/yosys-map.log -p 'read_rtlil $<; synth_xilinx -family xc7 -top ypcb_ddr3 -run map_luts:; delete t:$$scopeinfo; check -assert; select -assert-none ypcb_ddr3/t:$$*; stat; write_json $@'

memory-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_memory --Mdir $(CURDIR)/memory-test$(MEMORY_NUM_INPUTS) -o memory-test -GNUM_INPUTS=$(MEMORY_NUM_INPUTS) $(filter-out -DSYNTHESIS -DNDEBUG,$(CFLAGS)) -DSIMULATION -y $(RTL_DIR)/libs $(SRC_DIR)/VX_ypcb_memory.sv $(SRC_DIR)/tests/memory.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror -DTEST_NUM_INPUTS=$(MEMORY_NUM_INPUTS)'
	$(CURDIR)/memory-test$(MEMORY_NUM_INPUTS)/memory-test

pio-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_pio --Mdir $(CURDIR)/pio-test -o pio-test $(filter-out -DSYNTHESIS -DNDEBUG,$(CFLAGS)) -DSIMULATION $(SRC_DIR)/VX_ypcb_pio.sv $(SRC_DIR)/tests/pio.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror'
	$(CURDIR)/pio-test/pio-test

pio-host-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_pio --Mdir $(CURDIR)/pio-host-test -o pio-host-test $(filter-out -DSYNTHESIS -DNDEBUG,$(CFLAGS)) -DSIMULATION $(SRC_DIR)/VX_ypcb_pio.sv $(SRC_DIR)/tests/pio.cpp $(SW_COMMON_DIR)/ypcb_transport.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror -pthread -DTEST_PIO_TRANSPORT -I$(SW_COMMON_DIR)' -LDFLAGS '-pthread'
	$(CURDIR)/pio-host-test/pio-host-test

pio-memory-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_pio --Mdir $(CURDIR)/pio-memory-test -o pio-memory-test $(filter-out -DSYNTHESIS -DNDEBUG,$(CFLAGS)) -DSIMULATION $(SRC_DIR)/VX_ypcb_pio.sv $(SRC_DIR)/tests/pio.cpp $(SW_COMMON_DIR)/ypcb_transport.cpp $(SW_COMMON_DIR)/ypcb_host_memory.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror -pthread -DTEST_PIO_TRANSPORT -DTEST_HOST_MEMORY -I$(SW_COMMON_DIR)' -LDFLAGS '-pthread'
	$(CURDIR)/pio-memory-test/pio-memory-test

pio-synth:
	mkdir -p $(CURDIR)/pio
	$(YOSYS) -l $(CURDIR)/pio/yosys.log -p 'read_verilog -sv -I$(RTL_DIR) -I$(ROOT_DIR)/hw $(SRC_DIR)/VX_ypcb_pio.sv; synth_xilinx -family xc7 -top VX_ypcb_pio -flatten -noiopad -noclkbuf; check -assert; stat; write_json $(CURDIR)/pio/pio.json'

pcie-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_pcie --Mdir $(CURDIR)/pcie-test -o pcie-test $(filter-out -DSYNTHESIS -DNDEBUG,$(CFLAGS)) -DSIMULATION $(SRC_DIR)/VX_ypcb_pcie.sv $(SRC_DIR)/tests/pcie.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror'
	$(CURDIR)/pcie-test/pcie-test

pcie-synth:
	mkdir -p $(CURDIR)/pcie
	$(YOSYS) -l $(CURDIR)/pcie/yosys.log -p 'read_verilog -sv -I$(RTL_DIR) -I$(ROOT_DIR)/hw $(SRC_DIR)/VX_ypcb_pcie.sv; synth_xilinx -family xc7 -top VX_ypcb_pcie -flatten -noiopad -noclkbuf; check -assert; stat; write_json $(CURDIR)/pcie/pcie.json'

control-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_control --Mdir $(CURDIR)/control-test -o control-test $(SRC_DIR)/VX_ypcb_control.sv $(SRC_DIR)/tests/control.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror'
	$(CURDIR)/control-test/control-test

control-synth:
	mkdir -p $(CURDIR)/control
	$(SV2V) --top=VX_ypcb_control -w $(CURDIR)/control/control.v $(SRC_DIR)/VX_ypcb_control.sv
	$(YOSYS) -l $(CURDIR)/control/yosys.log -p 'read_verilog -noautowire $(CURDIR)/control/control.v; prep -top VX_ypcb_control; check -assert; synth_xilinx -family xc7 -top VX_ypcb_control -flatten -noiopad -noclkbuf -run begin:map_luts; write_rtlil $(CURDIR)/control/control-pre-luts.il; synth_xilinx -family xc7 -top VX_ypcb_control -noiopad -noclkbuf -run map_luts:; delete t:$$scopeinfo; check -assert; select -assert-none VX_ypcb_control/t:$$*; stat; write_json $(CURDIR)/control/control.json; write_verilog -noattr $(CURDIR)/control/control-mapped-body.v'
	python3 -c 'from pathlib import Path; p = Path("$(CURDIR)/control"); (p / "control-mapped.v").write_text("`timescale 1ns/1ps\n" + (p / "control-mapped-body.v").read_text())'

control-mapped-test: control-synth
	python3 $(SRC_DIR)/tests/stage_xilinx.py $(YOSYS_PATH)/share/yosys/xilinx/cells_sim.v $(CURDIR)/control/cells.v --netlist $(CURDIR)/control/control.json --top VX_ypcb_control
	$(IVERILOG) -g2012 -Wall -s control_tb -o $(CURDIR)/control/test.vvp $(CURDIR)/control/control-mapped.v $(CURDIR)/control/cells.v $(SRC_DIR)/tests/control_tb.sv
	$(VVP) $(CURDIR)/control/test.vvp

ddr-control-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_ddr_control --Mdir $(CURDIR)/ddr-control-test -o ddr-control-test $(SRC_DIR)/VX_ypcb_ddr_control.sv $(SRC_DIR)/tests/ddr_control.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror'
	$(CURDIR)/ddr-control-test/ddr-control-test

ddr-control-synth:
	mkdir -p $(CURDIR)/ddr-control
	$(YOSYS) -l $(CURDIR)/ddr-control/yosys.log -p 'read_verilog -sv $(SRC_DIR)/VX_ypcb_ddr_control.sv; synth_xilinx -family xc7 -top VX_ypcb_ddr_control -flatten -noiopad -noclkbuf; check -assert; stat; write_json $(CURDIR)/ddr-control/ddr-control.json'

startup-test:
	mkdir -p $(CURDIR)/startup
	$(VERILATOR) --lint-only --assert -Wall -DSIMULATION -I$(RTL_DIR) --top-module VX_ypcb_startup $(SRC_DIR)/VX_ypcb_startup.sv
	$(IVERILOG) -g2012 -Wall -I$(RTL_DIR) -s startup_tb -o $(CURDIR)/startup/test.vvp $(SRC_DIR)/tests/startup_tb.sv $(SRC_DIR)/VX_ypcb_startup.sv $(SRC_DIR)/VX_ypcb_scrub.sv
	$(VVP) $(CURDIR)/startup/test.vvp

startup-synth:
	mkdir -p $(CURDIR)/startup
	$(YOSYS) -l $(CURDIR)/startup/yosys.log -p 'read_verilog -sv -I$(RTL_DIR) $(SRC_DIR)/VX_ypcb_startup.sv; synth_xilinx -family xc7 -top VX_ypcb_startup -flatten -noiopad -noclkbuf; check -assert; stat; write_json $(CURDIR)/startup/startup.json'

startup-host-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -DSIMULATION -j 1 --top-module startup_host_top --Mdir $(CURDIR)/startup-host-test -o startup-host-test -I$(RTL_DIR) $(SRC_DIR)/tests/startup_host_top.sv $(SRC_DIR)/VX_ypcb_startup.sv $(SRC_DIR)/VX_ypcb_scrub.sv $(SRC_DIR)/tests/startup_host.cpp $(SW_COMMON_DIR)/ypcb_startup.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror -pthread -I$(SW_COMMON_DIR)' -LDFLAGS '-pthread'
	$(CURDIR)/startup-host-test/startup-host-test

scrub-test:
	$(VERILATOR) --build --cc --exe --assert -Wall -j 1 --top-module VX_ypcb_scrub --Mdir $(SCRUB_TEST_DIR) -o scrub-test "-GBASE_ADDR=64'h3ffff000" "-GEND_ADDR=64'h40002140" $(SRC_DIR)/VX_ypcb_scrub.sv $(SRC_DIR)/tests/scrub.cpp -CFLAGS '-std=c++17 -Wall -Wextra -Werror'
	$(SCRUB_TEST_DIR)/scrub-test

elaborate: sources
	$(VIVADO) -mode batch -nojournal -log $(OUT_DIR)/elaborate.log -source $(SRC_DIR)/afu.tcl -tclargs $(OUT_DIR) $(DEVICE) $(TOP) elaborate

synth: sources
	$(VIVADO) -mode batch -nojournal -log $(OUT_DIR)/synth.log -source $(SRC_DIR)/afu.tcl -tclargs $(OUT_DIR) $(DEVICE) $(TOP) synth

.PHONY: axil-cdc-test print-configs
axil-cdc-test:
	$(IVERILOG) -g2012 -Wall -s axil_cdc_tb -o $(CURDIR)/axil-cdc.vvp $(SRC_DIR)/VX_ypcb_axil_cdc.sv $(SRC_DIR)/tests/axil_cdc_tb.sv
	$(VVP) $(CURDIR)/axil-cdc.vvp

print-configs:
	@printf '%s\n' '$(YPCB_CONFIGS)'
