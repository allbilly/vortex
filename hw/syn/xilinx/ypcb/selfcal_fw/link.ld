OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { mem : ORIGIN = 0, LENGTH = 16384 }
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS
{
    .text : { *(.text.start) *(.text .text.*) } > mem :text
    .rodata : { *(.rodata .rodata.* .srodata .srodata.*) } > mem :text
    .data : { *(.data .data.* .sdata .sdata.*) } > mem :data
    ASSERT(SIZEOF(.data) == 0, "Calibration restart requires immutable initialized memory")
    .bss (NOLOAD) : ALIGN(4) {
        _bss_start = .;
        *(.bss .bss.* .sbss .sbss.* COMMON)
        . = ALIGN(4);
        _bss_end = .;
    } > mem :data
    _stack_top = ORIGIN(mem) + LENGTH(mem);
    ASSERT(_stack_top - _bss_end >= 2048, "Calibration firmware leaves less than 2 KiB stack")
    /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.note*) *(.eh_frame*) }
}
