/* MinHook's HDE64 predates VEX. Admit only the two exact VMOVSS loads at our
 * fingerprinted aiming entry, both with an ordinary RCX+disp8 memory operand.
 * No RIP-relative address, branch, immediate or VEX extension is involved.
 * Every other instruction retains the unmodified upstream decoder.
 */
#define hde64_disasm ap_legacy_disasm
#include "../.deps/minhook/src/hde/hde64.c"
#undef hde64_disasm

unsigned int hde64_disasm(const void *code, hde64s *hs) {
    const unsigned char *p = code;
    if (p[0] == 0xc5 && p[1] == 0xfa && p[2] == 0x10 &&
            ((p[3] == 0x59 && p[4] == 0x18) || (p[3] == 0x61 && p[4] == 0x1c))) {
        memset(hs, 0, sizeof(*hs));
        hs->len = 5;
        hs->opcode = 0x10;
        hs->modrm = p[3];
        hs->modrm_mod = 1;
        hs->modrm_reg = (p[3] >> 3) & 7;
        hs->modrm_rm = 1;
        hs->disp.disp8 = p[4];
        hs->flags = F_MODRM | F_DISP8;
        return 5;
    }
    return ap_legacy_disasm(code, hs);
}
