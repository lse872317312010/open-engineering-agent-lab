#include "../oeal_current_pi_f32.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "qemu_vectors.h"

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss;
int main(void);

static uint32_t semihost(uint32_t operation, const void *argument)
{
    register uint32_t r0 __asm__("r0") = operation;
    register const void *r1 __asm__("r1") = argument;
    __asm__ volatile ("bkpt 0xab" : "+r" (r0) : "r" (r1) : "memory");
    return r0;
}

static void write_text(const char *text)
{
    (void)semihost(4U, text);
}

__attribute__((noreturn)) static void finish(uint32_t status)
{
    const uint32_t block[2] = {0x20026U, status};
    (void)semihost(0x20U, block);
    for (;;) {
        __asm__ volatile ("wfi");
    }
}

__attribute__((noreturn)) void Fault_Handler(void)
{
    write_text("FAULT\n");
    finish(1U);
}

__attribute__((noreturn)) void Reset_Handler(void)
{
    uint32_t *source = &_sidata;
    for (uint32_t *dest = &_sdata; dest < &_edata; ++dest) {
        *dest = *source++;
    }
    for (uint32_t *dest = &_sbss; dest < &_ebss; ++dest) {
        *dest = 0U;
    }
    /* QEMU Cortex-M4 CP10/CP11 access; emulated peripheral register only. */
    *(volatile uint32_t *)0xE000ED88U |= 0x00F00000U;
    __asm__ volatile ("dsb\nisb" ::: "memory");
    (void)main();
    finish(0U);
}

static char *hex_word(char *dest, uint32_t value)
{
    static const char digits[] = "0123456789abcdef";
    for (int shift = 28; shift >= 0; shift -= 4) {
        *dest++ = digits[(value >> (unsigned int)shift) & 15U];
    }
    return dest;
}

int main(void)
{
    float previous[2] = {0.0f, 0.0f};
    write_text("OEAL-QEMU-PI-v1\n");
    uint32_t fpscr;
    __asm__ volatile ("vmrs %0, fpscr" : "=r" (fpscr));
    char mode[17] = "FPSCR ";
    char *end = hex_word(mode + 6, fpscr);
    *end++ = '\n';
    *end = '\0';
    write_text(mode);
    for (uint32_t index = 0; index < QEMU_VECTOR_COUNT; ++index) {
        const struct qemu_vector *vector = &qemu_vectors[index];
        float p[7], state[2], input[7], output[8] = {0.0f};
        memcpy(p, vector->p, sizeof(p));
        memcpy(state, vector->state, sizeof(state));
        memcpy(input, vector->input, sizeof(input));
        if (vector->chain == 2U) {
            memcpy(state, previous, sizeof(state));
        }
        const int status = vector->chain == 3U
            ? oeal_pi_step_f32(NULL, NULL, NULL, NULL)
            : oeal_pi_step_f32(p, state, input, output);
        if (status == 0) {
            previous[0] = output[6];
            previous[1] = output[7];
        }
        char line[128];
        char *dest = line;
        *dest++ = 'V';
        *dest++ = ' ';
        dest = hex_word(dest, index);
        *dest++ = ' ';
        dest = hex_word(dest, (uint32_t)status);
        for (size_t column = 0; column < 8; ++column) {
            uint32_t bits;
            memcpy(&bits, &output[column], sizeof(bits));
            *dest++ = ' ';
            dest = hex_word(dest, bits);
        }
        *dest++ = '\n';
        *dest = '\0';
        write_text(line);
    }
    write_text("DONE\n");
    return 0;
}
