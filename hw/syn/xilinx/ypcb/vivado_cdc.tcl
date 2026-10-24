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

set ypcb_crossings {}
set ypcb_gray_first [ypcb_cdc_require [get_cells -hier -filter \
    {MR_FF == TRUE && (NAME =~ axi_crossing_*/* || NAME =~ csr_crossing_*/*)}] \
    [expr {42 * [llength $ypcb_channels]}] "Gray-pointer first stages"]
foreach channel $ypcb_channels {
    foreach kind {axi csr} {
        set instance ${kind}_crossing_$channel
        lappend ypcb_crossings $instance
        set count [expr {$kind eq "axi" ? 30 : 12}]
        ypcb_cdc_require [get_cells -hier -filter \
            "MR_FF == TRUE && NAME =~ $instance/*"] $count "$instance Gray-pointer first stages"
    }
}
set ypcb_all_first [get_cells -hier -filter {MR_FF == TRUE}]
set ypcb_non_gray_first {}
foreach cell $ypcb_all_first {
    if {[lsearch -exact $ypcb_gray_first $cell] < 0} {lappend ypcb_non_gray_first $cell}
}
ypcb_cdc_require $ypcb_non_gray_first [llength $ypcb_channels] "DDR lock first stages"
set ypcb_gray_count [expr {14 * [llength $ypcb_channels]}]
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
if {[dict size $ypcb_gray_groups] != $ypcb_gray_count} {
    error "Expected $ypcb_gray_count Gray-pointer buses, found [dict size $ypcb_gray_groups]"
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

foreach instance $ypcb_crossings {
    set stages [get_cells -hier -filter "MR_FF == TRUE && NAME =~ $instance/*"]
    set clocks [ypcb_cdc_require [get_clocks -of_objects \
        [get_pins -of_objects $stages -filter {REF_PIN_NAME == C}]] 2 "$instance FIFO clock domains"]
    set clock_a [ypcb_cdc_require [get_clocks [lindex $clocks 0]] 1 "$instance first FIFO clock"]
    set clock_b [ypcb_cdc_require [get_clocks [lindex $clocks 1]] 1 "$instance second FIFO clock"]
    set budget [ypcb_cdc_budget $clock_a $clock_b]
    set storage [get_cells -hier -filter "NAME =~ $instance/storage* && REF_NAME =~ RAM*"]
    if {![llength $storage]} { error "No asynchronous FIFO memory in $instance" }
    set outputs [get_pins -of_objects $storage -filter {DIRECTION == OUT}]
    if {![llength $outputs]} { error "No FIFO data outputs in $instance" }
    # FIFO data becomes visible only after its Gray pointer crosses the synchronizer.
    set_max_delay -datapath_only $budget -from $clock_a -through $outputs -to $clock_b
    set_max_delay -datapath_only $budget -from $clock_b -through $outputs -to $clock_a
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

foreach channel $ypcb_channels {
    set first [ypcb_cdc_require [get_cells ddr_$channel/FDCE] 1 "DDR reset first stage"]
    set second [ypcb_cdc_require [get_cells ddr_$channel/FDCE_1] 1 "DDR reset second stage"]
    set_property ASYNC_REG TRUE [list $first $second]
    set_false_path -to [ypcb_cdc_pin $first D]
}
set ypcb_status_pattern {^status_meta_reg\[(1|3|5)\]$}
if {[llength $ypcb_channels] == 2} {set ypcb_status_pattern {^status_meta_reg\[[0-5]\]$}}
set ypcb_status_first [ypcb_cdc_require [get_cells -regexp $ypcb_status_pattern] \
    [expr {3 * [llength $ypcb_channels]}] "DDR status first stages"]
set_false_path -to [get_pins -of_objects $ypcb_status_first -filter {REF_PIN_NAME == D}]
set ypcb_bus_reset [ypcb_cdc_require [get_cells -hier -filter {NAME =~ reset_sync_reg*}] 2 "Bus reset stages"]
set_false_path -to [get_pins -of_objects $ypcb_bus_reset -filter {REF_PIN_NAME == PRE}]
set_false_path -from [ypcb_cdc_require [get_ports {SYS_RSTN}] 1 "Asynchronous reset ports"]

set ypcb_pcie [ypcb_cdc_require [get_cells pcie/pcie_block_inst/pcie_2_1_block] 1 "PCIe hard block"]
set_property LOC PCIE_X0Y0 $ypcb_pcie
puts "YPCB_CDC_CONSTRAINTS_APPLIED gray_buses=$ypcb_gray_count gray_bits=[llength $ypcb_gray_first] reset_chains=[llength $ypcb_reset_first]"

set link_first [ypcb_cdc_require [get_cells -regexp {^link_sync_reg\[0\]$}] 1 "PCIe link first stage"]
set_false_path -to [ypcb_cdc_pin $link_first D]
foreach bit {0 1 2 3} {
    set first [ypcb_cdc_require [get_cells -hier -regexp [format {^shell/pcie_error_meta_reg\[%d\]$} $bit]] 1 "PCIe status first stage $bit"]
    set second [ypcb_cdc_require [get_cells -hier -regexp [format {^shell/pcie_error_sync_reg\[%d\]$} $bit]] 1 "PCIe status second stage $bit"]
    set source [ypcb_cdc_require [get_cells -hier -regexp [format {^shell/pcie/error_status_reg\[%d\]$} $bit]] 1 "PCIe status source $bit"]
    foreach cell [list $first $second] {
        if {![get_property ASYNC_REG $cell]} {error "Missing PCIe status synchronizer attribute: $cell"}
    }
    foreach pair [list [list $source $first] [list $first $second]] {
        lassign $pair driver receiver
        set outputs [get_pins -leaf -of_objects [get_nets -segments -of_objects [ypcb_cdc_pin $receiver D]] -filter {DIRECTION == OUT}]
        if {[llength $outputs] != 1 || $outputs ne [ypcb_cdc_pin $driver Q]} {
            error "PCIe status synchronizer is not directly connected: $driver -> $receiver"
        }
    }
    set source_clock [ypcb_cdc_clock [ypcb_cdc_pin $source C]]
    set first_clock [ypcb_cdc_clock [ypcb_cdc_pin $first C]]
    set second_clock [ypcb_cdc_clock [ypcb_cdc_pin $second C]]
    if {$source_clock eq $first_clock || $first_clock ne $second_clock} {
        error "Incorrect PCIe status synchronizer clocks: $source -> $first -> $second"
    }
    foreach receiver [all_fanout -flat -endpoints_only -from [ypcb_cdc_pin $source Q]] {
        if {$receiver eq [ypcb_cdc_pin $first D]} {continue}
        set cell [ypcb_cdc_require [get_cells -of_objects $receiver] 1 "PCIe status capture register"]
        if {[ypcb_cdc_clock [ypcb_cdc_pin $cell C]] ne $source_clock} {
            error "PCIe status bypasses its first synchronizer stage: $source -> $receiver"
        }
    }
    set_false_path -from $source -to [ypcb_cdc_pin $first D]
    if {[llength [get_timing_paths -from $first -to $second -max_paths 1]] != 1} {
        error "PCIe status synchronizer settling path missing or cut: $bit"
    }
}
puts "YPCB_PCIE_STATUS_CDC_APPLIED bits=4 stages=2"
set mailbox shell/pcie_control_crossing
foreach direction {request response} {
    set first [ypcb_cdc_require [get_cells -hier -regexp [format {^%s/%s_sync_reg\[0\]$} $mailbox $direction]] 1 "$direction first stage"]
    set second [ypcb_cdc_require [get_cells -hier -regexp [format {^%s/%s_sync_reg\[1\]$} $mailbox $direction]] 1 "$direction second stage"]
    if {![get_property ASYNC_REG $first] || ![get_property ASYNC_REG $second]} {
        error "Missing mailbox synchronizer attributes: $direction"
    }
    set drivers [get_pins -leaf -of_objects [get_nets -segments -of_objects [ypcb_cdc_pin $second D]] -filter {DIRECTION == OUT}]
    if {[llength $drivers] != 1 || $drivers ne [ypcb_cdc_pin $first Q]} {
        error "Mailbox synchronizer stages are not directly connected: $direction"
    }
    if {[ypcb_cdc_clock [ypcb_cdc_pin $first C]] ne [ypcb_cdc_clock [ypcb_cdc_pin $second C]]} {
        error "Mailbox synchronizer receiver clocks differ: $direction"
    }
    set_false_path -to [ypcb_cdc_pin $first D]
}
proc ypcb_mailbox_payload {name sources targets} {
    if {![llength $sources] || ![llength $targets]} {error "Mailbox $name payload is absent"}
    set source_clock [ypcb_cdc_clock [get_pins -of_objects $sources -filter {REF_PIN_NAME == C}]]
    set target_clock [ypcb_cdc_clock [get_pins -of_objects $targets -filter {REF_PIN_NAME == C}]]
    if {$source_clock eq $target_clock} {error "Mailbox $name payload unexpectedly uses one clock"}
    set budget [ypcb_cdc_budget $source_clock $target_clock]
    set_max_delay -datapath_only $budget -from $sources -to $targets
    # Payload stays held until the response handshake crosses both synchronizers.
    set_false_path -hold -from $sources -to $targets
    foreach target $targets {
        if {[llength [get_timing_paths -from $sources -to $target -max_paths 1]] != 1} {
            error "Mailbox $name payload setup path missing or cut: $target"
        }
    }
    puts "YPCB_MAILBOX_PAYLOAD name=$name sources=[llength $sources] targets=[llength $targets] budget_ns=$budget"
}
set source_payload [get_cells -hier -filter "NAME =~ $mailbox/request_data_reg*"]
set target_payload [get_cells -hier -filter "NAME =~ $mailbox/m_*_reg*"]
set is_write [ypcb_cdc_require [get_cells -hier -filter "NAME == $mailbox/is_write_reg"] 1 "Mailbox write discriminator"]
ypcb_mailbox_payload request $source_payload [concat $target_payload $is_write]
set response_payload [get_cells -hier -filter "NAME =~ $mailbox/response_data_reg*"]
set source_response [get_cells -hier -filter "NAME =~ $mailbox/s_rdata_reg* || NAME =~ $mailbox/s_rresp_reg* || NAME =~ $mailbox/s_bresp_reg*"]
ypcb_mailbox_payload response $response_payload $source_response

set tx_error_first [ypcb_cdc_require [get_cells -regexp {^tx_error_sync_reg\[0\]$}] 1 "PCIe error first stage"]
set_false_path -to [ypcb_cdc_pin $tx_error_first D]
set source_reset_stages [ypcb_cdc_require [get_cells -hier -filter "NAME =~ $mailbox/source_reset_sync_reg*"] 2 "PCIe source reset stages"]
set_false_path -to [get_pins -of_objects $source_reset_stages -filter {REF_PIN_NAME == PRE}]
