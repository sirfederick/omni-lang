ENTRY(omni_boot_entry)
SECTIONS
{
  /* The exception stubs emitted by --exception-handler (32 stubs of 16 bytes) live at a fixed address the IDT-building Omni programs use
     as a constant. This rule must come BEFORE the .text rule: ld gives an input section to the first matching statement and
     `.text.*` would otherwise swallow `.text.omni_isr`. The image must end below 0x210000; ld fails on overlap and the suite asserts it. */
  .isr 0x210000 : { KEEP(*(.text.omni_isr)) }
  .text 0x200000 : { KEEP(*(.text.omni_entry)) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) }
  .data : { *(.data .data.*) *(.bss .bss.* COMMON) }
  /DISCARD/ : { *(.comment) *(.eh_frame) *(.note*) }
}
