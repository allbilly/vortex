if {$argc != 4} {error "Usage: program_sram.tcl bitstream status_file hw_server_url tck_hz"}
lassign $argv bitstream status_file server_url tck_hz
if {![file isfile $bitstream] || $tck_hz ni {3000000 6000000}} {error "Invalid SRAM programming inputs"}
open_hw_manager
connect_hw_server -url $server_url
set targets [get_hw_targets]
if {[llength $targets] != 1} {error "Expected exactly one JTAG target"}
current_hw_target [lindex $targets 0]
set_property PARAM.FREQUENCY $tck_hz [current_hw_target]
open_hw_target
set devices [get_hw_devices]
if {[llength $devices] != 1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {
    error "Expected single YPCB XC7K480T"
}
close_hw_target
open_hw_target -jtag_mode 1
run_state_hw_jtag RESET
run_state_hw_jtag IDLE
scan_ir_hw_jtag 6 -tdi 09
set ident [scan_dr_hw_jtag 32 -tdi 0]
if {[expr "0x$ident"] != 0x23751093} {error "Unexpected raw IDCODE"}
close_hw_target
open_hw_target
set devices [get_hw_devices]
if {[llength $devices] != 1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {
    error "Programming target changed"
}
set device [lindex $devices 0]
set_property PROGRAM.FILE $bitstream $device
program_hw_devices $device
refresh_hw_device $device
set init [get_property REGISTER.IR.BIT4_INIT_COMPLETE $device]
set done [get_property REGISTER.IR.BIT5_DONE $device]
if {![string is boolean -strict $init] || ![string is boolean -strict $done] || !$init || !$done} {
    error "Native programming INIT/DONE failed"
}
close_hw_target
open_hw_target -jtag_mode 1
run_state_hw_jtag RESET
run_state_hw_jtag IDLE
scan_ir_hw_jtag 6 -tdi 09
set ident [scan_dr_hw_jtag 32 -tdi 0]
if {[expr "0x$ident"] != 0x23751093} {error "Post-load IDCODE changed"}
set stream [open $status_file w]
puts $stream "INIT=1 DONE=1 IDCODE=23751093"
close $stream
close_hw_target
disconnect_hw_server
close_hw_manager
exit
