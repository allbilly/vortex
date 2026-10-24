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

foreach channel $ypcb_channels {
set wl_lanes [expr {$channel == 0 ? 8 : 9}]
set wl_mmcm [ypcb_wl_one [get_cells -hier -filter "NAME =~ ddr_${channel}/ldmmcm1 && REF_NAME == MMCME2_ADV"] "CH$channel write MMCM"]
foreach {property expected} {
    CLKIN1_PERIOD 10.0 CLKFBOUT_MULT_F 8.0 DIVCLK_DIVIDE 1
    CLKOUT0_DIVIDE_F 8.0 CLKOUT1_DIVIDE 2 CLKOUT2_DIVIDE 8
    CLKOUT3_DIVIDE 2 CLKOUT4_DIVIDE 2 CLKOUT5_DIVIDE 2 CLKOUT6_DIVIDE 2
    CLKOUT0_PHASE 0.0 CLKOUT1_PHASE 0.0 CLKOUT2_PHASE 0.0
    CLKOUT3_PHASE 0.0 CLKOUT4_PHASE 90.0 CLKOUT5_PHASE 0.0 CLKOUT6_PHASE 90.0
} {
    if {abs([get_property $property $wl_mmcm] - $expected) > 0.000001} {
        error "CH$channel clock contract mismatch: $property"
    }
}
foreach output {0 1 2 3 4 5 6} {
    set shifted [expr {$output < 2}]
    if {!![get_property CLKOUT${output}_USE_FINE_PS $wl_mmcm] != $shifted} {
        error "Unexpected fine phase mode on CH$channel output $output"
    }
}
set wl_sys [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $wl_mmcm CLKIN1]] "CH$channel controller clock"]
if {[get_property CLKFBOUT_USE_FINE_PS $wl_mmcm]
        || [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $wl_mmcm PSCLK]] "CH$channel phase-control clock"] ne $wl_sys} {
    error "CH$channel phase control does not preserve the controller clock"
}
foreach {pin period} {CLKIN1 10.0 CLKOUT0 10.0 CLKOUT1 2.5 CLKOUT2 10.0 CLKOUT3 2.5 CLKOUT4 2.5} {
    set clock [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $wl_mmcm $pin]] "CH$channel $pin clock"]
    if {abs([get_property PERIOD $clock] - $period) > 0.000001} {error "CH$channel clock period mismatch: $pin"}
}
set wl_lock_net [ypcb_wl_one [get_nets -hier -filter "NAME =~ ddr_${channel}/*wl_locked_sys"] "Synchronized CH$channel lock"]
set wl_lock_q [ypcb_wl_one [get_pins -leaf -of_objects $wl_lock_net -filter {DIRECTION == OUT}] "Lock second stage"]
set wl_second [ypcb_wl_one [get_cells -of_objects $wl_lock_q] "Lock second register"]
if {[get_property REF_NAME $wl_second] eq "LUT1"} {
    # KEEP on the status wire can retain an identity LUT after the synchronizer.
    if {![regexp {^2'[hH]0*2$} [get_property INIT $wl_second]]} {
        error "CH$channel lock wire is not driven by an identity buffer"
    }
    set wl_lock_q [ypcb_wl_driver [ypcb_wl_pin $wl_second I0]]
    set wl_second [ypcb_wl_one [get_cells -of_objects $wl_lock_q] "Buffered lock second register"]
}
set wl_first_q [ypcb_wl_driver [ypcb_wl_pin $wl_second D]]
set wl_first [ypcb_wl_one [get_cells -of_objects $wl_first_q] "Lock first register"]
foreach cell [list $wl_first $wl_second] {
    if {[get_property REF_NAME $cell] ne "FDRE" || ![get_property ASYNC_REG $cell]} {
        error "CH$channel lock stages were not preserved: $cell"
    }
    if {[ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $cell C]] "Lock register clock"] ne $wl_sys} {
        error "CH$channel lock synchronizer uses the wrong clock"
    }
}
if {[ypcb_wl_driver [ypcb_wl_pin $wl_first D]] ne [ypcb_wl_pin $wl_mmcm LOCKED]} {
    error "CH$channel lock synchronizer has an unexpected source"
}
set_false_path -to [ypcb_wl_pin $wl_first D]
if {[llength [get_timing_paths -from $wl_first -to $wl_second -max_paths 1]] != 1} {
    error "CH$channel lock synchronizer settling path is missing or cut"
}

set wl_pll_reset_first [ypcb_wl_one [get_cells ddr_${channel}/FDCE_8] "IDELAY PLL reset first stage"]
set wl_pll_reset_second [ypcb_wl_one [get_cells ddr_${channel}/FDCE_9] "IDELAY PLL reset second stage"]
if {[ypcb_wl_driver [ypcb_wl_pin $wl_pll_reset_second D]] ne [ypcb_wl_pin $wl_pll_reset_first Q]} {
    error "IDELAY PLL reset stages are not directly connected"
}
foreach cell [list $wl_pll_reset_first $wl_pll_reset_second] {
    set clock [ypcb_wl_one [get_clocks -of_objects [ypcb_wl_pin $cell C]] "IDELAY PLL reset clock"]
    if {abs([get_property PERIOD $clock] - 20.0) > 0.000001} {error "IDELAY PLL reset uses the wrong clock"}
    set_property ASYNC_REG TRUE $cell
}
set_false_path -to [ypcb_wl_pin $wl_pll_reset_first D]

set wl_compiled [file join $ddr_dir gateware ypcb_ddr3.v]
if {[llength $ypcb_channels] == 2} {
    set filename [expr {$channel == 0 ? "ypcb_ddr3_ch0.v" : "ypcb_ddr3.v"}]
    set wl_compiled [file join $ddr_dir ch$channel gateware $filename]
}
set wl_stream [open $wl_compiled r]
set wl_rtl [read $wl_stream]
close $wl_stream
set wl_dm_cells [dict create]
set wl_dm_bits [dict create]
foreach {match name bit} [regexp -all -inline {OSERDESE2\s+#\([^;]+\)\s+(\w+)\s*\([^;]*\.OQ\s*\(ddram_dm\[([0-8])\]\)[^;]*\);} $wl_rtl] {
    if {[dict exists $wl_dm_cells ddr_${channel}/$name] || [dict exists $wl_dm_bits $bit]} {
        error "Duplicate compiled data-mask serializer"
    }
    dict set wl_dm_cells ddr_${channel}/$name $bit
    dict set wl_dm_bits $bit 1
}
if {[dict size $wl_dm_cells] != $wl_lanes} {error "Compiled data-mask serializer map is incomplete"}
set wl_serdes {}
set wl_unused_dm 0
foreach cell [get_cells -hier -filter "NAME =~ ddr_${channel}/* && (REF_NAME == OSERDESE2 || REF_NAME == ISERDESE2)"] {
    if {[get_property REF_NAME $cell] eq "OSERDESE2"} {
        set net [ypcb_wl_one [get_nets -of_objects [ypcb_wl_pin $cell OQ]] "Serializer output"]
        # Synthesis renames the unconnected DM nets; bind their cells to compiled RTL.
        if {[dict exists $wl_dm_cells [get_property NAME $cell]]} {
            if {[llength [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == IN}]]} {
                error "YPCB data-mask output unexpectedly has a load"
            }
            incr wl_unused_dm
            continue
        }
    }
    lappend wl_serdes $cell
}
if {$wl_unused_dm > $wl_lanes} {error "Unexpected unconnected data-mask serializer count"}
set wl_targets [get_pins -of_objects $wl_serdes -filter {REF_PIN_NAME == RST}]
if {[llength $wl_targets] != (17 * $wl_lanes + 26)} {error "Incomplete CH$channel SERDES reset coverage (DM is unconnected)"}
set wl_sources [get_cells -hier -filter "NAME =~ ddr_${channel}/*wlrst* && REF_NAME == FDRE"]
if {[llength $wl_sources] < (9 * $wl_lanes)} {error "Missing per-pad CH$channel reset registers"}
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
puts "YPCB_WL_CLOCK_CHANNEL_PASS channel=$channel phase_bound_ns=1.3 serdes_resets=[llength $wl_targets] unused_dm=$wl_unused_dm lock_sync_stages=2"
}
source [file join $ddr_dir phase-constraints.tcl]
puts "YPCB_WL_CLOCK_CONTRACT_PASS channels=$ypcb_channels phase_bound_ns=1.3"
