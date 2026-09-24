// Laboratory only: record exact executed PowerPC addresses and instruction words.
// No observer or trace admission exists in the native product executor.
#include <cstdio>
#include <cstdlib>
#include <vector>

extern "C" UINT64 vf3_reference_frame_number();
static void vf3_ppc_observe(UINT32 pc, UINT32 word)
{
  // Read-only original-instruction store observation for damage derivation.
  static FILE *damage = []() -> FILE * {
    const char *path = std::getenv("VF3_DAMAGE_TRACE");
    if (!path || !*path) return nullptr;
    FILE *result = std::fopen(path, "w");
    if (!result) std::abort();
    std::setvbuf(result, nullptr, _IOLBF, 0); return result;
  }();
  if (damage && ((word >> 26) == 44 || (word >> 26) == 36)) {
    const unsigned base = (word >> 16) & 31, value = (word >> 21) & 31;
    const UINT32 ea = (base ? ppc.r[base] : 0) + INT16(word);
    if ((ea <= 0x1087d6 && ea + 4 > 0x1087d6) || (ea <= 0x10a7d6 && ea + 4 > 0x10a7d6)) {
      std::fprintf(damage, "%llu %08x %08x %08x %08x %08x", vf3_reference_frame_number(), pc, word, ea, ppc.r[value], ppc.lr);
      for(unsigned r=0;r<32;r++)std::fprintf(damage," %08x",ppc.r[r]);
      std::fprintf(damage,"\n");
    }
  }
  static FILE *file = []() -> FILE * {
    const char *path = std::getenv("VF3_PPC_TRACE");
    if (!path || !*path) return nullptr;
    FILE *result = std::fopen(path, "a");
    if (!result) { std::perror(path); std::abort(); }
    std::setvbuf(result, nullptr, _IOLBF, 0);
    return result;
  }();
  if (!file) return;
  // Only these two instruction-fetch regions exist in the pinned Model 3 core.
  static std::vector<UINT64> seen(0x400000, 0);
  UINT32 index;
  if (pc < 0x800000 && !(pc & 3)) index = pc >> 2;
  else if (pc >= 0xff800000 && !(pc & 3)) index = 0x200000 + ((pc & 0x7fffff) >> 2);
  else { std::fprintf(file, "%08x %08x\n", pc, word); return; }
  const UINT64 identity = (UINT64(1) << 32) | word;
  if (seen[index] != identity) {
    seen[index] = identity;
    std::fprintf(file, "%08x %08x\n", pc, word);
  }
}
