/* Differential SCSP fixture: same data/memory, independent reference/native. */
#include "SCSPDSP.h"
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>

extern "C" void vf3_native_fault(const char *message) { std::fprintf(stderr,"%s\n",message); std::abort(); }

static uint32_t next(uint32_t &seed) { seed=seed*1664525u+1013904223u; return seed; }
static uint64_t hash(const void *bytes, unsigned count, uint64_t value=1469598103934665603ULL) {
  const uint8_t *p=(const uint8_t *)bytes;
  for(unsigned i=0;i<count;i++) value=(value^p[i])*1099511628211ULL;
  return value;
}
static uint16_t ram[0x80000];
static void initialize(_SCSPDSP &dsp, uint32_t &seed) {
  SCSPDSP_Init(&dsp);
  dsp.SCSPRAM=ram; dsp.SCSPRAM_LENGTH=sizeof(ram);
  dsp.RBP=next(seed)&127; dsp.RBL=0x8000<<((next(seed)>>10)&3);
  dsp.DEC=next(seed);
  for(auto &x:ram) x=(uint16_t)next(seed);
  for(auto &x:dsp.COEF) x=(int16_t)next(seed);
  for(auto &x:dsp.MADRS) x=(uint16_t)next(seed);
  for(auto &x:dsp.TEMP) x=(int32_t)next(seed)>>8;
  for(auto &x:dsp.MEMS) x=(int32_t)next(seed)>>8;
  for(auto &x:dsp.EXTS) x=(int16_t)next(seed);
}
static uint64_t result(_SCSPDSP &dsp) {
  dsp.SCSPRAM=nullptr;
  return hash(&dsp,sizeof(dsp),hash(ram,sizeof(ram)));
}
extern "C" uint64_t sound_dsp_probe_limit(const uint16_t *program, uint32_t seed, unsigned steps, int last_step) {
  _SCSPDSP dsp;
  initialize(dsp,seed);
  memcpy(dsp.MPRO,program,sizeof(dsp.MPRO));
  SCSPDSP_Start(&dsp);
  if (last_step>=0) dsp.LastStep=last_step;
  for(unsigned i=0;i<steps;i++) {
    for(auto &x:dsp.MIXS) x=(int32_t)next(seed)>>12;
    SCSPDSP_Step(&dsp);
  }
  return result(dsp);
}
extern "C" uint64_t sound_dsp_probe(const uint16_t *program, uint32_t seed, unsigned steps) {
  return sound_dsp_probe_limit(program,seed,steps,-1);
}
extern "C" uint64_t sound_dsp_sequence_probe(const uint16_t *programs, const int *limits, unsigned count, uint32_t seed) {
  _SCSPDSP dsp;
  initialize(dsp,seed);
  dsp.Stopped=false;
  // Change upload progress without resetting DSP registers, sample memory or
  // the native pointer cache. Explicit limits model the separately latched
  // start register, including shorter and longer limits than the visible image.
  for(unsigned sample=0;sample<count;sample++) {
    memcpy(dsp.MPRO,programs+512*sample,sizeof(dsp.MPRO));
    dsp.LastStep=limits[sample];
    for(auto &x:dsp.MIXS) x=(int32_t)next(seed)>>12;
    SCSPDSP_Step(&dsp);
  }
  return result(dsp);
}
extern "C" void sound_dsp_cache_guard() {
  uint16_t programs[1024]={};
  int limits[2]={128,128};
  programs[512]=0xffff;
  (void)sound_dsp_sequence_probe(programs,limits,2,0x12345678);
}
