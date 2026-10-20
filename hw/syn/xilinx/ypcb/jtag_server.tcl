if {$argc < 2 || $argc > 3} {error "Usage: jtag_server.tcl hw_server_url listen_port ?tck_hz?"}
lassign $argv server_url listen_port tck_hz
if {$tck_hz eq ""} {set tck_hz 3000000}
if {$tck_hz ni {3000000 6000000}} {error "Unsupported JTAG frequency"}
open_hw_manager
connect_hw_server -url $server_url
set targets [get_hw_targets]
if {[llength $targets] != 1} {error "Expected exactly one JTAG target"}
current_hw_target [lindex $targets 0]
set_property PARAM.FREQUENCY $tck_hz [current_hw_target]
open_hw_target
set devices [get_hw_devices -filter {PART =~ xc7k480t*}]
if {[llength $devices] != 1} {error "Expected one XC7K480T"}
current_hw_device [lindex $devices 0]
refresh_hw_device [current_hw_device]
set axes [get_hw_axis]
if {[llength $axes] != 1} {error "Expected exactly one JTAG AXI master"}
set axis [lindex $axes 0]
set client ""
proc access_word {write address value} {
    global axis
    set name ypcb_read
    set args [list -force -address [format %08x $address] -len 1 -size 32]
    if {$write} {
        set name ypcb_write
        lappend args -type write -data [format %08x $value]
    } else {
        lappend args -type read
    }
    create_hw_axi_txn $name $axis {*}$args
    run_hw_axi [get_hw_axi_txns $name]
    if {$write} {return 0}
    return [expr "0x[get_property DATA [get_hw_axi_txns $name]]"]
}
if {[access_word 0 0x3000 0] != 0x56595043 || [access_word 0 0x3004 0] != 2} {
    error "JTAG AXI does not expose the CH1 YPCB register ABI"
}
proc consume {channel} {
    global client
    if {[eof $channel]} {
        close $channel
        set client ""
        return
    }
    if {[gets $channel line] < 0} {return}
    if {[catch {
        if {![regexp {^([RW]) ([0-9a-fA-F]{4})(?: ([0-9a-fA-F]{8}))?$} $line all op addr data]} {
            error "invalid request"
        }
        scan $addr %x address
        if {$address & 3} {error "unaligned register"}
        if {($op eq "W") != ($data ne "")} {error "invalid data field"}
        set value 0
        if {$op eq "W"} {scan $data %x value}
        set result [access_word [expr {$op eq "W"}] $address $value]
        set status [access_word 0 0x3008 0]
        if {$status & 0x7800} {error [format "AXI transport error status=0x%08x" $status]}
        puts $channel [format "OK %08x" $result]
    } diagnostic]} {
        puts $channel "ERR $diagnostic"
    }
    flush $channel
}
proc accept {channel address port} {
    global client
    fconfigure $channel -buffering line -blocking 0 -translation lf
    if {$client ne ""} {
        puts $channel "ERR client already connected"
        close $channel
        return
    }
    set client $channel
    fileevent $channel readable [list consume $channel]
}
set listener [socket -server accept -myaddr 127.0.0.1 $listen_port]
puts "YPCB_JTAG_MMIO_READY port=$listen_port"
flush stdout
vwait forever
