proc ypcb_cache_clock_signature {} {
    set clocks {}
    foreach clock [lsort [get_clocks]] {
        lappend clocks [list $clock [get_property PERIOD $clock] [get_property WAVEFORM $clock]]
    }
    return $clocks
}

set ypcb_cache_clocks [ypcb_cache_clock_signature]
set ypcb_cache_ports [lsort [get_ports]]
set ypcb_cache_seen [dict create]
set ypcb_cache_targets {}
set ypcb_cache_inventory [open [file join $output_dir cache-address-drivers.txt] w]
foreach net [get_nets -hier -filter {NAME =~ *l2cache* && NAME =~ *cache_data* && NAME =~ */addr*}] {
    set loads [get_pins -leaf -of_objects $net -filter {DIRECTION == IN}]
    set drivers [get_pins -leaf -of_objects $net -filter {DIRECTION == OUT}]
    if {[llength $loads] < 128 || [llength $drivers] != 1} {continue}
    set cell [get_cells -of_objects $drivers]
    if {[llength $cell] != 1 || ![string match LUT* [get_property REF_NAME $cell]]
            || [dict exists $ypcb_cache_seen $cell]} {continue}
    dict set ypcb_cache_seen $cell 1
    puts $ypcb_cache_inventory "$net loads=[llength $loads] driver=$cell"
    lappend ypcb_cache_targets $net
}
close $ypcb_cache_inventory
if {[llength $ypcb_cache_targets]} {
    set ypcb_cache_before [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]
    phys_opt_design -force_replication_on_nets $ypcb_cache_targets
    set ypcb_cache_after [llength [get_cells -hier -filter {REF_NAME =~ LUT*}]]
    if {$ypcb_cache_after <= $ypcb_cache_before} {
        error "Cache address replication produced no additional LUT drivers"
    }
    puts "YPCB_CACHE_ADDRESS_REPLICATION drivers=[llength $ypcb_cache_targets] additional_luts=[expr {$ypcb_cache_after - $ypcb_cache_before}]"
} else {
    puts "YPCB_CACHE_ADDRESS_REPLICATION drivers=0"
}
if {$ypcb_cache_clocks ne [ypcb_cache_clock_signature]
        || $ypcb_cache_ports ne [lsort [get_ports]]} {
    error "Cache address optimization changed clock or port definitions"
}
