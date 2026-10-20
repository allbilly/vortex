proc ypcb_wl_one {objects label} {
    if {[llength $objects] != 1} {error "$label: expected one object, found [llength $objects]"}
    return $objects
}
proc ypcb_wl_pin {cell name} {
    return [ypcb_wl_one [get_pins -of_objects $cell -filter "REF_PIN_NAME == $name"] "$cell/$name"]
}
proc ypcb_wl_driver {pin} {
    set nets [get_nets -segments -of_objects $pin]
    return [ypcb_wl_one [get_pins -leaf -of_objects $nets -filter {DIRECTION == OUT}] "Driver of $pin"]
}

set wl_mmcm [ypcb_wl_one [get_cells -hier -filter {NAME =~ ddr_1/ldmmcm1 && REF_NAME == MMCME2_ADV}] "CH1 write MMCM"]
foreach {property expected} {
    CLKIN1_PERIOD 10.0 CLKFBOUT_MULT_F 8.0 DIVCLK_DIVIDE 1
    CLKOUT0_DIVIDE_F 8.0 CLKOUT1_DIVIDE 2 CLKOUT2_DIVIDE 8
    CLKOUT3_DIVIDE 2 CLKOUT4_DIVIDE 2 CLKOUT5_DIVIDE 2 CLKOUT6_DIVIDE 2
    CLKOUT0_PHASE 0.0 CLKOUT1_PHASE 0.0 CLKOUT2_PHASE 0.0
    CLKOUT3_PHASE 0.0 CLKOUT4_PHASE 90.0 CLKOUT5_PHASE 0.0 CLKOUT6_PHASE 90.0
} {
    if {abs([get_property $property $wl_mmcm] - $expected) > 0.000001} {
        error "CH1 clock contract mismatch: $property"
    }
}
foreach output {0 1 2 3 4 5 6} {
    set shifted [expr {$output < 2}]
    if {!![get_property CLKOUT${output}_USE_FINE_PS $wl_mmcm] != $shifted} {
        error "Unexpected fine phase mode on CH1 output $output"
    }
}
set wl_sys [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $wl_mmcm CLKIN1]] "CH1 controller clock"]
if {[get_property CLKFBOUT_USE_FINE_PS $wl_mmcm]
        || [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $wl_mmcm PSCLK]] "CH1 phase-control clock"] ne $wl_sys} {
    error "CH1 phase control does not preserve the controller clock"
}
foreach {pin period} {CLKIN1 10.0 CLKOUT0 10.0 CLKOUT1 2.5 CLKOUT2 10.0 CLKOUT3 2.5 CLKOUT4 2.5} {
    set clock [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $wl_mmcm $pin]] "CH1 $pin clock"]
    if {abs([get_property PERIOD $clock] - $period) > 0.000001} {error "CH1 clock period mismatch: $pin"}
}
set wl_lock_net [ypcb_wl_one [get_nets -hier -filter {NAME =~ ddr_1/*wl_locked_sys}] "Synchronized CH1 lock"]
set wl_lock_q [ypcb_wl_one [get_pins -leaf -of_objects [get_nets -segments -of_objects $wl_lock_net] -filter {DIRECTION == OUT}] "Lock second stage"]
set wl_second [ypcb_wl_one [get_cells -of_objects $wl_lock_q] "Lock second register"]
set wl_first_q [ypcb_wl_driver [ypcb_wl_pin $wl_second D]]
set wl_first [ypcb_wl_one [get_cells -of_objects $wl_first_q] "Lock first register"]
foreach cell [list $wl_first $wl_second] {
    if {[get_property REF_NAME $cell] ne "FDRE" || ![get_property ASYNC_REG $cell]} {
        error "CH1 lock stages were not preserved: $cell"
    }
    if {[ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $cell C]] "Lock register clock"] ne $wl_sys} {
        error "CH1 lock synchronizer uses the wrong clock"
    }
}
if {[ypcb_wl_driver [ypcb_wl_pin $wl_first D]] ne [ypcb_wl_pin $wl_mmcm LOCKED]} {
    error "CH1 lock synchronizer has an unexpected source"
}
set_false_path -from [ypcb_wl_pin $wl_mmcm LOCKED] -to [ypcb_wl_pin $wl_first D]

set wl_pll_reset_first [ypcb_wl_one [get_cells ddr_1/FDCE_8] "IDELAY PLL reset first stage"]
set wl_pll_reset_second [ypcb_wl_one [get_cells ddr_1/FDCE_9] "IDELAY PLL reset second stage"]
if {[ypcb_wl_driver [ypcb_wl_pin $wl_pll_reset_second D]] ne [ypcb_wl_pin $wl_pll_reset_first Q]} {
    error "IDELAY PLL reset stages are not directly connected"
}
foreach cell [list $wl_pll_reset_first $wl_pll_reset_second] {
    set clock [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $cell C]] "IDELAY PLL reset clock"]
    if {abs([get_property PERIOD $clock] - 20.0) > 0.000001} {error "IDELAY PLL reset uses the wrong clock"}
    set_property ASYNC_REG TRUE $cell
}
set_false_path -to [ypcb_wl_pin $wl_pll_reset_first D]

set wl_serdes [get_cells -hier -filter {NAME =~ ddr_1/* && (REF_NAME == OSERDESE2 || REF_NAME == ISERDESE2)}]
set wl_targets [get_pins -of_objects $wl_serdes -filter {REF_PIN_NAME == RST}]
if {[llength $wl_targets] != 179} {error "Incomplete CH1 SERDES reset coverage (72 inputs, 107 outputs; DM is unconnected)"}
set wl_sources [get_cells -hier -filter {NAME =~ ddr_1/*wlrst* && REF_NAME == FDRE}]
if {[llength $wl_sources] < 81} {error "Missing per-pad CH1 reset registers"}
foreach target $wl_targets {
    set driver [ypcb_wl_driver $target]
    set cell [ypcb_wl_one [get_cells -of_objects $driver] "SERDES reset source"]
    if {[lsearch -exact $wl_sources $cell] < 0 || ![get_property DONT_TOUCH $cell]} {
        error "SERDES reset bypasses its preserved register: $target"
    }
    set primitive [ypcb_wl_one [get_cells -of_objects $target] "SERDES"]
    set source_clock [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $cell C]] "SERDES reset clock"]
    set target_clock [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $primitive CLKDIV]] "SERDES CLKDIV"]
    if {$source_clock ne $target_clock} {error "SERDES reset is registered in the wrong clock domain"}
}
source [file join $ddr_dir phase-constraints.tcl]
puts "YPCB_WL_CLOCK_CONTRACT_PASS phase_bound_ns=1.3 serdes_resets=[llength $wl_targets] lock_sync_stages=2"
