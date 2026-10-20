if {$argc != 1} {error "Usage: vivado_finalize.tcl output_directory"}
set output_dir [file normalize [lindex $argv 0]]
set_param general.maxThreads 1
set_param synth.maxThreads 1
open_checkpoint [file join $output_dir routed.dcp]
if {[get_property PART [current_design]] ne "xc7k480tffg1156-2"} {error "Unexpected routed FPGA part"}
set clocks [get_clocks clock_125_raw]
if {[llength $clocks] != 1 || abs([get_property PERIOD $clocks] - 8.0) > 0.000001} {
    error "Routed GPU clock is not 125 MHz"
}
if {[llength [get_ports -quiet ddr0_*]] != 0
        || [llength [get_ports -regexp {^ddr1_dq\[[0-9]+\]$}]] != 72} {
    error "Routed image does not preserve the CH1-only DDR interface"
}
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
set result [exec python3 [file join $output_dir finalization verify_vivado_reports.py] $output_dir]
set stream [open [file join $output_dir report-qualification.json] w]
puts $stream $result
close $stream
puts $result
write_debug_probes -force [file join $output_dir vortex_ypcb.ltx]
write_bitstream -force [file join $output_dir vortex_ypcb.bit]
puts "YPCB_ROUTED_CHECKPOINT_FINALIZATION_COMPLETE_PHYSICAL_QUALIFICATION_PENDING"
exit
