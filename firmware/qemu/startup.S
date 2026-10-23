.syntax unified
.cpu cortex-m4
.thumb

.section .vectors, "a", %progbits
.global vector_table
vector_table:
    .word _estack
    .word Reset_Handler
    .rept 14
    .word Fault_Handler
    .endr
