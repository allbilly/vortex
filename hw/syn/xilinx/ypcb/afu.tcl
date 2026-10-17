if {$argc != 4} {
    error "Usage: afu.tcl output_dir device top elaborate|synth"
}
lassign $argv output_dir device top mode
if {$device ne "xc7k480tffg1156-2" || $top ne "vortex_afu"} {
    error "Unexpected YPCB device or AFU top"
}
if {$mode ni {elaborate synth}} {
    error "Unexpected action: $mode"
}
set output_dir [file normalize $output_dir]
create_project -in_memory -part $device
set handle [open [file join $output_dir sources.txt] r]
set sources [split [read $handle] "\n"]
close $handle
set defines {}
set include_dirs {}
set source_files {}
foreach source $sources {
    set source [string trim $source]
    if {[string match "+define+*" $source]} {
        lappend defines [string range $source 8 end]
    } elseif {[string match "+incdir+*" $source]} {
        lappend include_dirs [string range $source 8 end]
    } elseif {[string match "+*" $source]} {
        error "Unsupported file-list directive: $source"
    } elseif {$source ne ""} {
        if {![file isfile $source]} {
            error "Missing RTL source: $source"
        }
        lappend source_files $source
    }
}
set_property verilog_define $defines [current_fileset]
set_property include_dirs $include_dirs [current_fileset]
foreach source $source_files {
    read_verilog -sv $source
}
set_property top $top [current_fileset]
update_compile_order -fileset sources_1
if {$mode eq "elaborate"} {
    synth_design -rtl -top $top -part $device
} else {
    synth_design -mode out_of_context -top $top -part $device
    write_checkpoint -force [file join $output_dir afu_synth.dcp]
    report_utilization -file [file join $output_dir utilization.rpt]
    report_drc -file [file join $output_dir drc.rpt]
}
