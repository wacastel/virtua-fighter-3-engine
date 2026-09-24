/* Differential one-instruction fixture, linked separately to reference/native. */
#include "m68kcpu.h"
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

void vf3_native_fault(const char *message) { fprintf(stderr,"%s\n",message); abort(); }

unsigned vf3_m68k_board;
static unsigned char rom[0x80000];
static unsigned seed;
static uint64_t reads, writes;
static struct { unsigned address, value; } mutations[2048];
static unsigned mutation_count;
static unsigned memory_byte(unsigned address) {
  address &= 0xffffff;
  for (unsigned i=mutation_count;i;i--) if(mutations[i-1].address==address) return mutations[i-1].value;
  if(vf3_m68k_board==0 && address>=0x600000 && address<0x700000) {
    unsigned offset=(address-0x600000)&0x7ffff;
    return rom[offset^1];
  }
  if(vf3_m68k_board==0 && address<16) return rom[address^1];
  unsigned value=(address^seed)*2654435761u;
  return (value ^ (value>>13))&255;
}
static void hash_byte(uint64_t *hash,unsigned address,unsigned value) {
  *hash=(*hash^(address&0xffffff))*1099511628211ULL;
  *hash=(*hash^value)*1099511628211ULL;
}
unsigned M68KRead8(unsigned address) { unsigned value=memory_byte(address); hash_byte(&reads,address,value); return value; }
unsigned M68KRead16(unsigned address) { unsigned high=M68KRead8(address); return (high<<8)|M68KRead8(address+1); }
unsigned M68KRead32(unsigned address) { unsigned high=M68KRead16(address); return (high<<16)|M68KRead16(address+2); }
unsigned M68KFetch8(unsigned address) { return M68KRead8(address); }
unsigned M68KFetch16(unsigned address) { return M68KRead16(address); }
unsigned M68KFetch32(unsigned address) { return M68KRead32(address); }
void M68KWrite8(unsigned address,unsigned value) {
  address &= 0xffffff; value &= 255;
  hash_byte(&writes,address,value);
  if(mutation_count<2048) { mutations[mutation_count].address=address; mutations[mutation_count++].value=value; }
}
void M68KWrite16(unsigned address,unsigned value) { M68KWrite8(address,value>>8); M68KWrite8(address+1,value); }
void M68KWrite32(unsigned address,unsigned value) { M68KWrite16(address,value>>16); M68KWrite16(address+2,value); }
int M68KIRQCallback(int level) { (void)level; return M68K_INT_ACK_AUTOVECTOR; }
void sound_probe_load(unsigned board,const unsigned char *data) { if(board!=0) abort(); memcpy(rom,data,sizeof(rom)); }
void sound_probe_run(unsigned board,unsigned pc,unsigned random_seed,uint64_t *result) {
  vf3_m68k_board=board; seed=random_seed; mutation_count=0;
  memset(&m68ki_cpu,0,sizeof(m68ki_cpu)); m68k_init(); m68k_set_cpu_type(M68K_CPU_TYPE_68000);
  m68k_pulse_reset();
  for(unsigned i=0;i<16;i++) m68k_set_reg((m68k_register_t)i,((seed*(i+1)*1103515245u)+12345u)&(i<8?0xffffffff:0xfffffe));
  m68k_set_reg(M68K_REG_SP,0xff00);
  m68k_set_reg(M68K_REG_USP,0xfe00);
  m68k_set_reg(M68K_REG_SR,0x2700|(seed&31));
  m68k_set_reg(M68K_REG_PC,pc);
  reads=writes=1469598103934665603ULL;
  result[0]=m68k_execute(1);
  for(unsigned i=0;i<=M68K_REG_CPU_TYPE;i++) result[1+i]=m68k_get_reg(0,(m68k_register_t)i);
  result[40]=reads; result[41]=writes; result[42]=mutation_count;
  result[43]=m68ki_cpu.stopped;
}
