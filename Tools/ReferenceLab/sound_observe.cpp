#include "sound_observe.h"
#include <array>
#include <cstdio>
#include <cstdlib>
#include <set>
#include <mutex>

namespace {
std::mutex capture_mutex;
FILE *output() {
  static FILE *f = []() {
    const char *path = std::getenv("VF3_SOUND_CAPTURE");
    return path && *path ? std::fopen(path, "a") : nullptr;
  }();
  return f;
}
}
extern "C" void vf3_sound_observe68k(unsigned board, unsigned pc, unsigned (*read_word)(unsigned)) {
  if (!output()) return;
  std::array<unsigned,14> key{};
  key[0] = board; key[1] = pc;
  for (unsigned i = 0; i < 12; ++i) key[2+i] = read_word((pc+2*i)&0xffffff);
  std::lock_guard<std::mutex> guard(capture_mutex);
  static std::set<std::array<unsigned,14>> seen;
  if (!seen.insert(key).second) return;
  std::fprintf(output(), "{\"kind\":\"m68k\",\"board\":%u,\"pc\":%u,\"words\":[", board, pc);
  for (unsigned i = 0; i < 12; ++i) std::fprintf(output(), "%s%u", i ? "," : "", key[2+i]);
  std::fprintf(output(), "]}\n"); std::fflush(output());
}
extern "C" void vf3_sound_observe_dsp(const unsigned short *words) {
  if (!output()) return;
  std::array<unsigned short,512> key{};
  for (unsigned i = 0; i < 512; ++i) key[i] = words[i];
  std::lock_guard<std::mutex> guard(capture_mutex);
  static std::set<std::array<unsigned short,512>> seen;
  if (!seen.insert(key).second) return;
  std::fprintf(output(), "{\"kind\":\"scspdsp\",\"words\":[");
  for (unsigned i = 0; i < 512; ++i) std::fprintf(output(), "%s%u", i ? "," : "", key[i]);
  std::fprintf(output(), "]}\n"); std::fflush(output());
}
