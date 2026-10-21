if {$argc != 7} {
    error "Usage: vivado_board.tcl source build output ddr cdc pcie stage"
}
lassign $argv source_root build_root output_dir ddr_dir cdc_dir pcie_dir stage
foreach name {source_root build_root output_dir ddr_dir cdc_dir pcie_dir} {
    set $name [file normalize [set $name]]
}
if {$stage ni {synthesize implement}} {error "Invalid stage"}
set board_dir [file join $source_root hw syn xilinx ypcb]
set part xc7k480tffg1156-2
set_param general.maxThreads 1
set_param synth.maxThreads 1
if {$stage eq "synthesize"} {
    set_part $part
    file mkdir [file join $output_dir ip]
    create_ip -name jtag_axi -vendor xilinx.com -library ip -version 1.2 \
        -module_name ypcb_jtag_axi -dir [file join $output_dir ip]
    set_property -dict [list CONFIG.PROTOCOL {2} CONFIG.M_AXI_ADDR_WIDTH {32} \
        CONFIG.M_AXI_DATA_WIDTH {32} CONFIG.RD_TXN_QUEUE_LENGTH {16} \
        CONFIG.WR_TXN_QUEUE_LENGTH {16}] [get_ips ypcb_jtag_axi]
    foreach property {RD_TXN_QUEUE_LENGTH WR_TXN_QUEUE_LENGTH} {
        if {[get_property CONFIG.$property [get_ips ypcb_jtag_axi]] != 16} {
            error "JTAG register batches require a 16-entry $property"
        }
    }
    generate_target all [get_ips ypcb_jtag_axi]
    synth_ip [get_ips ypcb_jtag_axi]
    set stream [open [file join $output_dir afu sources.txt] r]
    set defines {}
    set includes [list [file join $build_root hw] $board_dir]
    set files {}
    while {[gets $stream line] >= 0} {
        if {[string match "+define+*" $line]} {
            lappend defines [string range $line 8 end]
        } elseif {[string match "+incdir+*" $line]} {
            lappend includes [string range $line 8 end]
        } elseif {[string match "+*" $line]} {
            error "Unsupported source-list directive: $line"
        } elseif {[string trim $line] ne ""} {
            lappend files [string trim $line]
        }
    }
    close $stream
    set_property verilog_define [lsort -unique $defines] [current_fileset]
    set_property include_dirs [lsort -unique $includes] [current_fileset]
    lappend files {*}[glob [file join $board_dir VX_ypcb_*.sv]]
    lappend files [file join $board_dir ypcb_top.sv] [file join $ddr_dir gateware ypcb_ddr3.v] \
        [file join $cdc_dir cdc ypcb_axi_cdc.v] [file join $cdc_dir wb-cdc ypcb_wb_cdc.v]
    foreach name {xilinx_pcie_mmcm.v pcie_7x.v pcie_axi_rx.v pcie_axi_tx.v pcie_block.v \
                  pcie_brams.v pcie_tx_thrtl_ctl.v pipe_wrapper_gtx.v} {
        lappend files [file join $pcie_dir src $name]
    }
    foreach path $files {
        if {![file isfile $path]} {error "Missing source: $path"}
        read_verilog -sv $path
    }
    set input [open [file join $output_dir board ypcb-reference.xdc] r]
    set output [open [file join $output_dir ypcb-vivado.xdc] w]
    while {[gets $input line] >= 0} {
        if {[string match "reset_property INTERNAL_VREF*" [string trim $line]]} {continue}
        if {[string match "*ddr1_reset_n*" $line]} {
            set line [string map {"IOSTANDARD SSTL15" "IOSTANDARD LVCMOS15"} $line]
        }
        puts $output $line
    }
    close $input
    close $output
    read_xdc [file join $output_dir ypcb-vivado.xdc]
    set_property top ypcb_top [current_fileset]
    update_compile_order -fileset sources_1
    synth_design -top ypcb_top -part $part -flatten_hierarchy none
    set_property CFGBVS GND [current_design]
    set_property CONFIG_VOLTAGE 1.8 [current_design]
    set delays [get_cells -hier -filter {REF_NAME == IDELAYE2 && NAME =~ *ddr_1*}]
    set controls [get_cells -hier -filter {REF_NAME == IDELAYCTRL && NAME =~ *ddr_1*}]
    if {[llength $delays] != 72 || [llength $controls] != 1} {error "Incomplete CH1 delay coverage"}
    set_property IODELAY_GROUP ypcb_ddr1 [concat $delays $controls]
    set txout [get_nets -hier -filter {NAME =~ *PIPE_TXOUTCLK_OUT*}]
    if {[llength $txout] != 1} {error "Expected one PCIe TXOUTCLK"}
    create_clock -name pcie_gt_txoutclk -period 10.000 $txout
    write_checkpoint -force [file join $output_dir synth.dcp]
    report_utilization -file [file join $output_dir utilization-synth.rpt]
    report_drc -file [file join $output_dir drc-synth.rpt]
    puts "YPCB_CH1_JTAG_PCIE_SYNTHESIS_COMPLETE"
    exit
}
open_checkpoint [file join $output_dir synth.dcp]
source [file join $board_dir vivado_cdc.tcl]
source [file join $board_dir vivado_wl_clock.tcl]
set hub [get_debug_cores -quiet dbg_hub]
if {[llength $hub] != 1} {error "JTAG AXI debug hub is absent"}
set_property C_CLK_INPUT_FREQ_HZ 125000000 $hub
connect_debug_port dbg_hub/clk [get_nets bus_clk]
opt_design
source [file join $board_dir vivado_wl_clock.tcl]
source [file join $board_dir vivado_pcie_clock.tcl]
write_checkpoint -force [file join $output_dir optimized.dcp]
place_design -directive Explore
report_timing_summary -delay_type min_max -max_paths 30 \
    -file [file join $output_dir timing-placed.rpt]
phys_opt_design -directive AggressiveExplore
report_timing_summary -delay_type min_max -max_paths 30 \
    -file [file join $output_dir timing-preroute.rpt]
route_design -directive Explore
write_checkpoint -force [file join $output_dir routed-initial.dcp]
report_timing_summary -delay_type min_max -max_paths 30 \
    -file [file join $output_dir timing-initial-route.rpt]
# Post-route physical optimization maintains routing; rerouting can undo its gains.
for {set iteration 0} {$iteration < 3} {incr iteration} {
    set setup [get_timing_paths -delay_type max -max_paths 1]
    set hold [get_timing_paths -delay_type min -max_paths 1]
    if {[llength $setup] != 1 || [llength $hold] != 1} {error "Missing timing paths"}
    if {[get_property SLACK $setup] >= 0 && [get_property SLACK $hold] >= 0} {break}
    phys_opt_design -directive AggressiveExplore
    write_checkpoint -force [file join $output_dir [format "routed-phys-opt-%02d.dcp" $iteration]]
}
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup] != 1 || [llength $hold] != 1} {error "Missing final timing paths"}
report_bus_skew -file [file join $output_dir bus-skew.rpt]
report_cdc -details -file [file join $output_dir cdc-routed.rpt]
report_clock_interaction -file [file join $output_dir clock-interaction-routed.rpt]
report_route_status -file [file join $output_dir route-status.rpt]
check_timing -verbose -file [file join $output_dir check-timing-routed.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose \
    -file [file join $output_dir timing-summary.rpt]
report_io -file [file join $output_dir io-routed.rpt]
report_drc -file [file join $output_dir drc-routed.rpt]
report_utilization -file [file join $output_dir utilization-routed.rpt]
write_checkpoint -force [file join $output_dir routed.dcp]
if {[get_property SLACK $setup] < 0 || [get_property SLACK $hold] < 0} {error "Routed timing fails"}
set qualification [exec python3 [file join $board_dir verify_vivado_reports.py] $output_dir]
set receipt [open [file join $output_dir report-qualification.json] w]
puts $receipt $qualification
close $receipt
puts $qualification
write_debug_probes -force [file join $output_dir vortex_ypcb.ltx]
write_bitstream -force [file join $output_dir vortex_ypcb.bit]
puts "YPCB_CH1_JTAG_PCIE_BITSTREAM_WRITTEN_PHYSICAL_QUALIFICATION_PENDING"
