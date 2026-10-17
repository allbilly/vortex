proc ypcb_cdc_require {objects count description} {
    if {[llength $objects] != $count} {
        error "$description: expected $count objects, found [llength $objects]"
    }
    return $objects
}

proc ypcb_cdc_pin {cell pin} {
    return [ypcb_cdc_require [get_pins -of_objects $cell -filter "REF_PIN_NAME == $pin"] 1 "$cell/$pin"]
}

proc ypcb_cdc_clock {pin} {
    return [ypcb_cdc_require [get_clocks -of_objects $pin] 1 "Clock for $pin"]
}

proc ypcb_cdc_budget {source destination} {
    set source_period [get_property PERIOD $source]
    set destination_period [get_property PERIOD $destination]
    if {$source_period <= 0 || $destination_period <= 0} {
        error "Invalid CDC clock periods: $source_period / $destination_period"
    }
    return [expr {min($source_period, $destination_period)}]
}

set ypcb_gray_first [ypcb_cdc_require [get_cells -hier -filter {MR_FF == TRUE}] 84 "Gray-pointer first stages"]
set ypcb_gray_groups [dict create]
foreach destination $ypcb_gray_first {
    set data_pin [ypcb_cdc_pin $destination D]
    set data_net [ypcb_cdc_require [get_nets -of_objects $data_pin] 1 "Gray-pointer data net"]
    set source_pin [ypcb_cdc_require [get_pins -leaf -of_objects $data_net -filter {DIRECTION == OUT}] 1 "Gray-pointer driver"]
    set source [ypcb_cdc_require [get_cells -of_objects $source_pin] 1 "Gray-pointer source register"]
    if {![regexp {/(.*cdc_graycounter[0-9]+_q_reg)\[[0-9]+\]$} [get_property NAME $source]]} {
        error "First CDC stage $destination is not driven by a preserved Gray counter: $source"
    }
    if {![get_property ASYNC_REG $destination] || ![get_property DONT_TOUCH $source]} {
        error "Missing CDC preservation attributes: $source -> $destination"
    }
    set source_clock [ypcb_cdc_clock [ypcb_cdc_pin $source C]]
    set destination_clock [ypcb_cdc_clock [ypcb_cdc_pin $destination C]]
    if {$source_clock eq $destination_clock} {
        error "Gray-pointer crossing unexpectedly uses one clock: $destination"
    }
    set budget [ypcb_cdc_budget $source_clock $destination_clock]
    set_max_delay -datapath_only $budget -from $source -to $destination
    regsub {\[[0-9]+\]$} [get_property NAME $destination] {} group
    dict lappend ypcb_gray_groups $group [list $source $destination $budget]
}
if {[dict size $ypcb_gray_groups] != 28} {
    error "Expected 28 Gray-pointer buses, found [dict size $ypcb_gray_groups]"
}
dict for {group bits} $ypcb_gray_groups {
    if {[llength $bits] != 3} { error "Gray-pointer bus $group is not three bits" }
    set sources {}
    set destinations {}
    foreach bit $bits {
        lassign $bit source destination budget
        lappend sources $source
        lappend destinations $destination
    }
    set_bus_skew $budget -from $sources -to $destinations
}

foreach instance {axi_crossing_0 axi_crossing_1 csr_crossing_0 csr_crossing_1} {
    set bus_clock [ypcb_cdc_clock [get_pins $instance/bus_clk]]
    set memory_clock [ypcb_cdc_clock [get_pins $instance/memory_clk]]
    set budget [ypcb_cdc_budget $bus_clock $memory_clock]
    set storage [get_cells -hier -filter "NAME =~ $instance/storage* && REF_NAME =~ RAM*"]
    if {![llength $storage]} { error "No asynchronous FIFO memory in $instance" }
    set outputs [get_pins -of_objects $storage -filter {DIRECTION == OUT}]
    if {![llength $outputs]} { error "No FIFO data outputs in $instance" }
    # FIFO data becomes visible only after its Gray pointer crosses the synchronizer.
    set_max_delay -datapath_only $budget -from $bus_clock -through $outputs -to $memory_clock
    set_max_delay -datapath_only $budget -from $memory_clock -through $outputs -to $bus_clock
}

set ypcb_reset_first [get_cells -hier -filter {ARS_FF1 == TRUE}]
set ypcb_reset_second [get_cells -hier -filter {ARS_FF2 == TRUE}]
if {![llength $ypcb_reset_first] || [llength $ypcb_reset_first] != [llength $ypcb_reset_second]} {
    error "Incomplete asynchronous-reset synchronizer metadata"
}
set ypcb_reset_cells [concat $ypcb_reset_first $ypcb_reset_second]
set_false_path -to [get_pins -of_objects $ypcb_reset_cells -filter {REF_PIN_NAME == PRE}]
set_max_delay 2 -from [get_pins -of_objects $ypcb_reset_first -filter {REF_PIN_NAME == C}] \
    -to [get_pins -of_objects $ypcb_reset_second -filter {REF_PIN_NAME == D}]

foreach channel {0 1} {
    set first [ypcb_cdc_require [get_cells ddr_$channel/FDCE] 1 "DDR reset first stage"]
    set second [ypcb_cdc_require [get_cells ddr_$channel/FDCE_1] 1 "DDR reset second stage"]
    set_property ASYNC_REG TRUE [list $first $second]
    set_false_path -to [ypcb_cdc_pin $first D]
}
set ypcb_status_first [ypcb_cdc_require [get_cells -hier -filter {NAME =~ status_meta_reg*}] 6 "DDR status first stages"]
set_false_path -to [get_pins -of_objects $ypcb_status_first -filter {REF_PIN_NAME == D}]
set ypcb_bus_reset [ypcb_cdc_require [get_cells -hier -filter {NAME =~ reset_sync_reg*}] 2 "Bus reset stages"]
set_false_path -to [get_pins -of_objects $ypcb_bus_reset -filter {REF_PIN_NAME == PRE}]
set_false_path -from [ypcb_cdc_require [get_ports {SYS_RSTN pcie_perstn}] 2 "Asynchronous reset ports"]

set ypcb_pcie [ypcb_cdc_require [get_cells pcie/pcie_block_inst/pcie_2_1_block] 1 "PCIe hard block"]
set_property LOC PCIE_X0Y0 $ypcb_pcie
puts "YPCB_CDC_CONSTRAINTS_APPLIED gray_buses=28 gray_bits=84 reset_chains=[llength $ypcb_reset_first]"
