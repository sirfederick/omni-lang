# Test-owned boot ADAPTER for the x86-64 conformance programs (OMNI-CORE-PRO-FOUNDATION-001, CP-09/CP-13).
#
# WHAT THIS PROVIDES (not Omni): QEMU's PVH loader enters 32-bit protected mode with paging off. This adapter performs the
# minimal transition to long mode (identity map of the first 1 GiB plus the local-APIC page, PAE, EFER.LME, paging, 64-bit GDT) and
# jumps to the Omni image `omni_boot_entry`, which is linked first in a flat payload at PAYLOAD_BASE. For the SMP conformance
# programs it also carries the application-processor (AP) start trampoline: after the Omni program on the bootstrap processor sends
# INIT/SIPI, the AP wakes in real mode at 0x8000, reaches long mode through the same page tables and calls the Omni function whose
# address the build passes in AP_ENTRY (--defsym). It is NOT a bootloader product, not an Omni feature and it contains no
# scheduler, drivers or runtime. Omni code starts at omni_boot_entry (BSP) and at AP_ENTRY (AP).
#
# Memory map: 0x8000 AP trampoline | 0x100000 adapter | 0x110000 page tables (16 KiB) | 0x200000 Omni payload |
#             0x400000 BSP stack top (AP n: 0x400000 - n * 0x10000) | 0x500000 provider per-CPU slots (256 B each) |
#             0x510000 atomic test cells | 0xFEE00000 local APIC (uncached 2 MiB page).
        .set PAYLOAD_BASE, 0x200000
        .set STACK_TOP,    0x400000

        .section .boot, "ax"
        .code32
        .global _start32
_start32:
        cli
        cld
        movl    $STACK_TOP, %esp
        # copy the AP start trampoline (loaded above 1 MiB) to its execution address 0x8000
        movl    $__ap_lma, %esi
        movl    $0x8000, %edi
        movl    $__ap_size, %ecx
        rep movsb
        # clear the four page-table pages
        movl    $pml4, %edi
        xorl    %eax, %eax
        movl    $4096, %ecx
        rep stosl
        # PML4[0] -> PDPT; PDPT[0] -> PD (first 1 GiB); PDPT[3] -> PD3 (3..4 GiB, only the APIC page is mapped)
        # Upper levels carry U/S=1 (present | writable | user): access control is decided by the leaf entries, which are supervisor-only
        # (0x83) until a program, such as the ring3 conformance program, flips the U bit of the 2 MiB pages it wants user code to reach.
        movl    $pdpt, %eax
        orl     $0x7, %eax
        movl    %eax, pml4
        movl    $pd, %eax
        orl     $0x7, %eax
        movl    %eax, pdpt
        movl    $pd3, %eax
        orl     $0x7, %eax
        movl    %eax, pdpt + 24
        # PD[i] = i * 2 MiB | present | writable | page-size
        movl    $pd, %edi
        movl    $0x83, %eax
        movl    $512, %ecx
1:      movl    %eax, (%edi)
        addl    $0x200000, %eax
        addl    $8, %edi
        decl    %ecx
        jnz     1b
        # PD3[503] = 0xFEE00000 | present | writable | page-size | write-through | cache-disable (the local APIC)
        movl    $(0xFEE00000 + 0x9B), pd3 + 503 * 8
        # PAE, long-mode enable, paging
        movl    %cr4, %eax
        orl     $0x20, %eax
        movl    %eax, %cr4
        movl    $pml4, %eax
        movl    %eax, %cr3
        movl    $0xC0000080, %ecx
        rdmsr
        orl     $0x100, %eax
        wrmsr
        lgdt    gdtr
        movl    %cr0, %eax
        orl     $0x80000001, %eax
        movl    %eax, %cr0
        ljmp    $0x08, $long_entry

        .code64
long_entry:
        movw    $0x10, %ax
        movw    %ax, %ds
        movw    %ax, %es
        movw    %ax, %ss
        xorl    %eax, %eax
        movw    %ax, %fs
        movw    %ax, %gs
        .ifdef SSE
        # Images built for --target-isa sse2: enable x87/SSE (CR0.EM=0, CR0.MP=1, CR4.OSFXSR=1, CR4.OSXMMEXCPT=1) before any Omni code
        # runs, because the compiler may use SSE anywhere in such an image. Images without it must never execute an SSE instruction.
        movq    %cr0, %rax
        andq    $~0x4, %rax
        orq     $0x2, %rax
        movq    %rax, %cr0
        movq    %cr4, %rax
        orq     $0x600, %rax
        movq    %rax, %cr4
        fninit
        .endif
        movq    $STACK_TOP, %rsp
        xorl    %ebp, %ebp
        # omni_boot_entry is an ordinary function that never returns: it must be entered as if it had been called (SysV: a 16-aligned stack plus a return address, so rsp = 8 mod 16),
        # or every 16-byte stack slot the compiler assumes aligned (movdqa/movaps spills of vectors) faults with #GP. --defsym ALIGNED_ENTRY=1 builds the faulty loader for the test of that rule.
        .ifndef ALIGNED_ENTRY
        pushq   $0
        .endif
        movabsq $PAYLOAD_BASE, %rax
        jmp     *%rax

        .align 8
gdt:
        .quad   0x0000000000000000
        .quad   0x00AF9A000000FFFF      # 64-bit code, ring 0
        .quad   0x00CF92000000FFFF      # data, ring 0
gdtr:
        .word   gdtr - gdt - 1
        .long   gdt

        .section .note.pvh, "a", @note
        .align 4
        .long   4
        .long   4
        .long   18                      # XEN_ELFNOTE_PHYS32_ENTRY
        .asciz  "Xen"
        .long   _start32

        .section .pagetables, "aw", @nobits
        .align 4096
        .global pml4
pml4:   .skip 4096
pdpt:   .skip 4096
pd:     .skip 4096
pd3:    .skip 4096

        .section .payload, "a", @progbits
        .incbin "payload.bin"

        # Optional bring-up trace for QEMU (-debugcon): one character per stage, only when assembled with --defsym APDEBUG=1.
        .macro DBG c
        .ifdef APDEBUG
        movb    $\c, %al
        outb    %al, $0xe9
        .endif
        .endm

        # ---- AP start trampoline, linked at 0x8000 (SIPI vector 0x08: CS=0x0800, IP=0) ----
        .section .aptramp, "ax"
        .code16
        .global ap_start
ap_start:
        ljmpw   $0x0, $ap_cont          # CS base 0x8000 with IP 0 -> CS=0 and the absolute IP the code was linked for
ap_cont:
        DBG     '1'
        cli
        cld
        xorw    %ax, %ax
        movw    %ax, %ds
        movw    %ax, %es
        movw    %ax, %ss
        lgdtl   ap_gdtr
        movl    %cr0, %eax
        orl     $0x1, %eax
        movl    %eax, %cr0
        DBG     '2'
        ljmpl   $0x08, $ap_pm

        .code32
ap_pm:
        DBG     '3'
        movw    $0x10, %ax
        movw    %ax, %ds
        movw    %ax, %es
        movw    %ax, %ss
        movw    %ax, %fs
        movw    %ax, %gs
        movl    %cr4, %eax
        orl     $0x20, %eax
        movl    %eax, %cr4
        movl    $pml4, %eax
        movl    %eax, %cr3
        movl    $0xC0000080, %ecx
        rdmsr
        orl     $0x100, %eax
        wrmsr
        movl    %cr0, %eax
        orl     $0x80000000, %eax
        movl    %eax, %cr0
        DBG     '4'
        ljmpl   $0x18, $ap_long

        .code64
ap_long:
        DBG     '5'
        movw    $0x10, %ax
        movw    %ax, %ds
        movw    %ax, %es
        movw    %ax, %ss
        movl    $1, %eax
        cpuid                           # EBX[31:24] = initial APIC id of this CPU
        shrl    $24, %ebx
        movq    $STACK_TOP, %rsp
        movl    %ebx, %eax
        shlq    $16, %rax
        subq    %rax, %rsp
        andq    $-16, %rsp
        xorl    %ebp, %ebp
        DBG     '6'
        movabsq $AP_ENTRY, %rax
        call    *%rax
        DBG     '7'
1:      cli
        hlt
        jmp     1b

        .align 8
ap_gdt:
        .quad   0x0000000000000000
        .quad   0x00CF9A000000FFFF      # 0x08: 32-bit code
        .quad   0x00CF92000000FFFF      # 0x10: data
        .quad   0x00AF9A000000FFFF      # 0x18: 64-bit code
ap_gdtr:
        .word   ap_gdtr - ap_gdt - 1
        .long   ap_gdt
