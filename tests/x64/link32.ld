ENTRY(_start32)
PHDRS
{
  boot PT_LOAD FLAGS(7);
  ap PT_LOAD FLAGS(7);
  payload PT_LOAD FLAGS(7);
  note PT_NOTE;
}
/* Every section states its load address explicitly: QEMU loads PT_LOAD segments by p_paddr, and an AT() on one section would
   otherwise shift the load addresses of all that follow (measured: the payload landed at 0x2f9000 instead of 0x200000). */
SECTIONS
{
  .boot 0x100000 : AT(0x100000) { *(.boot) } :boot
  .note.pvh 0x100200 : AT(0x100200) { KEEP(*(.note.pvh)) } :boot :note
  .pagetables 0x110000 (NOLOAD) : AT(0x110000) { *(.pagetables) } :boot
  /* The AP trampoline must execute at 0x8000 but QEMU's PVH loader does not populate memory below 1 MiB for this image (measured:
     0x8000 reads as zero), so it is LOADED above the page tables and COPIED to 0x8000 by the adapter before Omni starts. */
  __ap_lma = 0x120000;
  .aptramp 0x8000 : AT(0x120000) { KEEP(*(.aptramp)) } :ap
  __ap_size = SIZEOF(.aptramp);
  .payload 0x200000 : AT(0x200000) { KEEP(*(.payload)) } :payload
  /DISCARD/ : { *(.comment) *(.eh_frame) }
}
