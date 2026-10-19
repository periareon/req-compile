# Embeds the source bundle and the bootstrap script as data in the module.
    .section .rodata.bundle,"",@
    .globl bundle_start
    .type bundle_start,@object
    .p2align 4
bundle_start:
    .incbin "bundle.bin"
    .size bundle_start, .-bundle_start
    .globl bundle_end
    .type bundle_end,@object
bundle_end:
    .byte 0
    .size bundle_end, 1

    .section .rodata.bootstrap,"",@
    .globl bootstrap_src
    .type bootstrap_src,@object
bootstrap_src:
    .incbin "bootstrap.py"
    .byte 0
    .size bootstrap_src, .-bootstrap_src
