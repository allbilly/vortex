proc ypcb_pcie_mux_one {objects description} {
    if {[llength $objects] != 1} {
        error "$description: expected one object, found [llength $objects]"
    }
    return $objects
}

proc ypcb_pcie_mux_pin {cell name} {
    return [ypcb_pcie_mux_one [get_pins -of_objects $cell -filter "REF_PIN_NAME == $name"] "$cell/$name"]
}

proc ypcb_pcie_mux_driver {pin} {
    set nets [get_nets -segments -of_objects $pin]
    return [ypcb_pcie_mux_one [get_pins -leaf -of_objects $nets -filter {DIRECTION == OUT}] "Driver for $pin"]
}

proc ypcb_pcie_mux_inverted {cell name} {
    set value [get_property IS_${name}_INVERTED $cell]
    switch -- $value {
        "1'b0" { return 0 }
        "1'b1" { return 1 }
        default { error "Unsupported polarity value for $cell/$name: $value" }
    }
}

set ypcb_pcie_mux [ypcb_pcie_mux_one [get_cells -hier -filter {NAME == pcie/in_module_mmcm.pipe_clock_i/pclk_i1_bufgctrl.pclk_i1 && REF_NAME == BUFGCTRL}] "PCIe clock mux"]
foreach {name expected} {CE0 1 CE1 1 IGNORE0 0 IGNORE1 0} {
    set driver [ypcb_pcie_mux_driver [ypcb_pcie_mux_pin $ypcb_pcie_mux $name]]
    set cell [ypcb_pcie_mux_one [get_cells -of_objects $driver] "Constant driver for $name"]
    switch -- [get_property REF_NAME $cell] {
        VCC { set value 1 }
        GND { set value 0 }
        default { error "PCIe clock mux $name is not constant" }
    }
    set effective [expr {$value ^ [ypcb_pcie_mux_inverted $ypcb_pcie_mux $name]}]
    if {$effective != $expected} {
        error "Glitchless PCIe clock mux requires $name=$expected"
    }
}
if {[get_property INIT_OUT $ypcb_pcie_mux] != 0} {
    error "Unexpected PCIe clock mux INIT_OUT"
}
set ypcb_pcie_select0 [ypcb_pcie_mux_pin $ypcb_pcie_mux S0]
set ypcb_pcie_select1 [ypcb_pcie_mux_pin $ypcb_pcie_mux S1]
set ypcb_pcie_select_driver [ypcb_pcie_mux_driver $ypcb_pcie_select1]
set ypcb_pcie_select_register [ypcb_pcie_mux_one [get_cells -of_objects $ypcb_pcie_select_driver] "PCIe selector register"]
if {[ypcb_pcie_mux_driver $ypcb_pcie_select0] ne $ypcb_pcie_select_driver
    || [get_property REF_NAME $ypcb_pcie_select_register] ne "FDRE"
    || [get_property REF_PIN_NAME $ypcb_pcie_select_driver] ne "Q"
    || ![ypcb_pcie_mux_inverted $ypcb_pcie_mux S0]
    || [ypcb_pcie_mux_inverted $ypcb_pcie_mux S1]} {
    error "PCIe clock selects are not complementary outputs of the expected register"
}
foreach {name period} {I0 8.0 I1 4.0} {
    set clock [ypcb_pcie_mux_one [get_clocks -of_objects [ypcb_pcie_mux_pin $ypcb_pcie_mux $name]] "PCIe $name clock"]
    if {abs([get_property PERIOD $clock] - $period) > 0.001} {
        error "Unexpected PCIe $name clock period"
    }
}

# UG953 permits asynchronous S selection with variable latency in this glitchless mode.
set_false_path -to [list $ypcb_pcie_select0 $ypcb_pcie_select1]
puts "YPCB_PCIE_GLITCHLESS_SELECT_CONSTRAINTS_APPLIED pins=2 CE=1 IGNORE=0"
