# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

set stream [open [lindex $argv 0] r]
while {[gets $stream line] >= 0} {
    if {![string match "proc *" $line]} {continue}
    set body $line
    while {![info complete $body]} {
        if {[gets $stream line] < 0} {error "Incomplete JTAG server procedure"}
        append body \n $line
    }
    eval $body
}
close $stream
set axis oracle
set client ""
set registers [dict create 12288 0x56595043 12292 3 12296 0]
set transactions {}
set queues {}
proc create_hw_axi_txn {name axis args} {
    global transactions
    if {[lindex $args 0] ne "-force"} {error "Transactions must replace stale definitions"}
    set options [dict create {*}[lrange $args 1 end]]
    if {[dict get $options -len] != 1 || [dict get $options -size] != 32} {
        error "Unexpected AXI Lite transaction geometry"
    }
    dict set transactions $name $options
}
proc get_hw_axi_txns {name} {return $name}
proc run_hw_axi {args} {
    global registers transactions queues
    if {[lindex $args 0] eq "-queue"} {
        set args [lrange $args 1 end]
        if {[llength $args] > 16} {error "Hardware queue overflow"}
        lappend queues $args
    }
    foreach name $args {
        set options [dict get $transactions $name]
        scan [dict get $options -address] %x address
        if {[dict get $options -type] eq "write"} {
            scan [dict get $options -data] %x value
            dict set registers $address $value
        } elseif {![dict exists $registers $address]} {
            error "Read from an uninitialized oracle register"
        }
        dict set transactions $name DATA [format %08x [dict get $registers $address]]
    }
}
proc get_property {property name} {
    global transactions
    return [dict get $transactions $name $property]
}
proc request {line} {
    set channel [file tempfile temporary]
    puts $channel $line
    flush $channel
    seek $channel 0
    consume $channel
    seek $channel 0
    set result [lindex [split [read $channel] \n] 1]
    close $channel
    file delete $temporary
    return $result
}
if {[lindex $argv 1] eq "--serve"} {
    for {set i 0} {$i < 16} {incr i} {dict set registers [expr {0x2100+4*$i}] [expr {0x100+$i}]}
    set listener [socket -server accept -myaddr 127.0.0.1 0]
    puts [lindex [fconfigure $listener -sockname] end]
    flush stdout
    vwait forever
}
set data {}
for {set i 0} {$i < 16} {incr i} {lappend data [format %08x [expr {0xabc00000+$i}]]}
if {[request "BW 2100 10 [join $data]"] ne "OK 00000000"} {error "Batch write failed"}
if {[request "BR 2100 10"] ne "OK [join $data]"} {error "Batch read ordering differs"}
set expected {}
for {set i 0} {$i < 16} {incr i} {lappend expected ypcb_batch_$i}
if {$queues ne [list $expected $expected]} {error "Transaction queue omitted or reordered registers"}
if {[request "R 3000"] ne "OK 56595043"} {error "Scalar signature read failed"}
foreach invalid {"BR fffc 02" "BR 2100 00" "BR 2100 11" "BR 2102 02" "BW 2100 02 00000000" "BR 2100 02 00000000"} {
    if {![string match "ERR *" [request $invalid]]} {error "Accepted invalid batch: $invalid"}
}
if {[llength $queues] != 2} {error "An invalid request reached the hardware queue"}
dict set registers 12296 0x1000
if {![string match "ERR *AXI transport error*" [request "BR 2100 10"]]} {
    error "Batch lost an AXI transport error"
}
puts "PASSED: actual JTAG Tcl parser and queued transactions, 16-word ordering, bounded requests and AXI errors; hardware API is an oracle"
