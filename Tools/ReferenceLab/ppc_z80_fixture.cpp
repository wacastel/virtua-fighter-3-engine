// Laboratory single-instruction comparison; never compiled into the product.
#include <cstdio>
#include <cstdarg>
#include <stdexcept>
#include "Supermodel.h"
#include "CPU/Bus.h"
#include "BlockFile.h"
#define private public
#include "CPU/Z80/Z80.h"
#undef private
#include "FIXTURE_CORE"

void DebugLog(const char *, ...) {}
void InfoLog(const char *, ...) {}
Result ErrorLog(const char *, ...) { return Result::FAIL; }

struct FixtureBus: IBus {
  UINT8 rom[0x10000]{};
  UINT8 ram[0x2000]{};
  UINT64 writes=0;
  UINT8 Read8(UINT32 a) override { return a<0x9000?rom[a]:a>=0xe000?ram[a&0x1fff]:0xff; }
  void Write8(UINT32 a,UINT8 d) override {
    if(a>=0xe000)ram[a&0x1fff]=d;
    writes=(writes*0x100000001b3ULL)^a^d;
  }
  UINT8 boardData = 0;
  UINT8 IORead8(UINT32 a) override {
    // The original billboard ports: DIP bank, main-board command and unused.
    return a==0x20 ? 0x0f : a==0x21 ? boardData : 0xff;
  }
  void IOWrite8(UINT32 a,UINT8 d) override { writes=(writes*0x100000001b3ULL)^a^d^0x80000000U; }
};
static void emit(UINT64 value) { std::fwrite(&value,sizeof(value),1,stdout); }
static int interruptVector(CZ80 *cpu) {
  cpu->SetINT(false);
  return Z80_INT_RST_38;
}
int main(int argc,char **argv) {
  if(argc!=2)return 2;
  FixtureBus bus;
  FILE *f=std::fopen(argv[1],"rb");if(!f)return 3;
  if(std::fread(bus.rom,1,sizeof(bus.rom),f)!=sizeof(bus.rom))return 4;
  std::fclose(f);
  CZ80 cpu;cpu.Init(&bus,interruptVector);
  for(unsigned pc=0;pc<0x9000;++pc)for(unsigned seed=0;seed<5;++seed) {
    cpu.Reset();
    cpu.pc=pc;cpu.sp=0xff80;cpu.ix=0xe300;cpu.iy=0xe500;
    cpu.regs[0]={UINT16(1+seed),UINT16(0xe200+seed),UINT16(0xe100+seed)};
    cpu.regs[1]={UINT16(2+seed),UINT16(0xe500+seed),UINT16(0xe300+seed)};
    cpu.af[0]=0x8100|seed*0x55;cpu.af[1]=0x7000|seed*0x35;
    // Baseline, enabled IM0/IM1/IM2, then NMI. The interrupt is evaluated
    // after the selected instruction, so DI/IM instructions retain their effect.
    cpu.im=seed>=1&&seed<=3 ? seed-1 : 0;
    cpu.iff=seed ? 3 : 0;
    cpu.intLine=seed>=1&&seed<=3;cpu.nmiTrigger=seed==4;
    cpu.ir=0xe100;
    bus.boardData=UINT8(0x35*seed);
    for(unsigned i=0;i<sizeof(bus.ram);++i)bus.ram[i]=UINT8(i*13+seed);
    bus.writes=0;
    int cycles=cpu.Run(1);
    emit(cycles);emit(cpu.pc);emit(cpu.sp);emit(cpu.ix);emit(cpu.iy);emit(cpu.ir);
    emit(cpu.af[0]);emit(cpu.af[1]);emit(cpu.af_sel);emit(cpu.regs_sel);
    for(unsigned i=0;i<2;++i){emit(cpu.regs[i].bc);emit(cpu.regs[i].de);emit(cpu.regs[i].hl);}
    emit(cpu.iff);emit(cpu.im);emit(cpu.intLine);emit(cpu.nmiTrigger);emit(bus.writes);
  }
#ifdef FIXTURE_NATIVE
  unsigned rejected=0;
  cpu.Reset();cpu.pc=0x9000;
  try { cpu.Run(1); } catch(const std::runtime_error &) { ++rejected; }
  for(unsigned byte=0;byte<4;++byte) {
    cpu.Reset();bus.rom[byte]^=1;
    try { cpu.Run(1); } catch(const std::runtime_error &) { ++rejected; }
    bus.rom[byte]^=1;
  }
  if(rejected!=5)return 5;
#endif
}
