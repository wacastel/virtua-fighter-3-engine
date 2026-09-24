// Laboratory only: record exact executed PowerPC addresses and instruction words.
// No observer or trace admission exists in the native product executor.
#include <cstdio>
#include <cstdlib>
#include <vector>

static void vf3_ppc_observe(UINT32 pc, UINT32 word)
{
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
