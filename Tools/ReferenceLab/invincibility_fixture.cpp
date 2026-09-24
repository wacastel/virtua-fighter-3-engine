// GPL-3.0-or-later. Isolated synthetic CPU comparison, no game state injection.
#include <cstdio>
#include <cstdarg>
#include <vector>
#include <map>
#include <stdexcept>
#include "FIXTURE_CORE"
static bool enabled=false;
extern "C" bool vf3_player_one_invincible(){return enabled;}
void DebugLog(const char *, ...) {} void InfoLog(const char *, ...) {}
Result ErrorLog(const char *, ...) { return Result::FAIL; }
struct InvincibilityBus: IBus {
 std::map<UINT32,UINT8> ram;unsigned reads=0,writes=0;
 UINT8 Read8(UINT32 a) override {
  if(a!=0x102108&&a!=0x102109&&a!=0x10210a&&a!=0x10210b&&a!=0x108784&&a!=0x10a784&&a!=0x102008&&a!=0x102009&&a!=0x10200a&&a!=0x10200b&&a!=0x106029)throw std::runtime_error("Non-RAM or unapproved predicate read");
  ++reads;return ram[a];
 }
 UINT16 Read16(UINT32 a) override{return UINT16(Read8(a))<<8|Read8(a+1);}
 UINT32 Read32(UINT32 a) override{return UINT32(Read16(a))<<16|Read16(a+2);}
 UINT64 Read64(UINT32 a) override{return UINT64(Read32(a))<<32|Read32(a+4);}
 void Write8(UINT32,UINT8) override{++writes;}
 void Write16(UINT32,UINT16) override{++writes;}
 void Write32(UINT32,UINT32) override{++writes;}
 void Write64(UINT32,UINT64) override{++writes;}
 void set32(UINT32 a,UINT32 v){for(int i=0;i<4;i++)ram[a+i]=v>>(24-i*8);}
};
static void emit(UINT64 v){std::fwrite(&v,sizeof(v),1,stdout);}
int main(){
 InvincibilityBus bus;std::vector<UINT32> memory(0x200000);PPC_FETCH_REGION fetch[]={{0,0x7fffff,memory.data()},{0,0,nullptr}};
 for(unsigned test=0;test<26;test++)for(unsigned seed=0;seed<8;seed++){
  PPC_CONFIG config={PPC_MODEL_603R,0x10,BUS_FREQUENCY_66MHZ};ppc_init(&config);ppc_attach_bus(&bus);ppc_set_fetch(fetch);
  ppc.pc=0x104a4;ppc.npc=ppc.pc+4;ppc_change_pc(ppc.npc);ppc.icount=1000;ppc.cur_cycles=1000;
  ppc.msr=0x2000;ppc.lr=0x148b8;ppc.ctr=seed+1;ppc.xer=seed<<29;
  for(unsigned r=0;r<32;r++){ppc.r[r]=0x1020304U*(r+1)^0xf00f00fU*seed;ppc.fpr[r].fd=(int(r)-16.+0.75)*(seed+1);}
  for(unsigned r=0;r<8;r++)ppc.cr[r]=(seed+r)&15;
  ppc.r[4]=28;ppc.r[10]=173;ppc.r[13]=0x108000;ppc.r[14]=0x108780;
  enabled=true;bus.ram.clear();bus.set32(0x102108,0x108780);bus.set32(0x102008,0x07090709);bus.ram[0x108784]=0;bus.ram[0x106029]=1;
  bool protect=test<4;
  switch(test){
   case 0:break;case 1:bus.ram[0x106029]=3;break;case 2:ppc.r[4]=999;break;case 3:ppc.r[10]=1;break;
   case 4:enabled=false;break;case 5:ppc.pc+=4;break;case 6:ppc.r[13]+=4;break;
   case 7:ppc.r[14]=0x10a780;break;case 8:bus.set32(0x102108,0x10a780);break;case 9:bus.ram[0x108784]=1;break;
   case 10:bus.ram[0x102008]=3;break;case 11:bus.ram[0x102009]=8;break;case 12:bus.ram[0x10200a]=8;break;case 13:bus.ram[0x10200b]=10;break;
   case 14:bus.ram[0x106029]=0;break;case 15:bus.ram[0x106029]=2;break;case 16:bus.ram[0x106029]=4;break;
   case 17:ppc.r[10]=0;break;case 18:ppc.r[10]=0xffffffff;break;case 19:ppc.r[10]=0x10000;break;
   case 20:ppc.r[4]=0;break;case 21:ppc.r[4]=0xffffffff;break;
   case 22:ppc.r[14]=0xf0040000;break;case 23:ppc.r[14]=0;break;
   case 24:bus.ram[0x102008]=0;break;case 25:bus.ram[0x102009]=17;break;
  }
  bus.reads=bus.writes=0;const UINT32 damage=ppc.r[4];
#ifdef FIXTURE_NATIVE
  // One deliberately different PC uses the same fixed operation wrapper to
  // exercise its internal address guard; dispatcher mismatch is tested below.
  if(test==5)vf3_ppc_incoming_damage();else vf3_ppc_fixed(ppc.pc,0x7d445051);
  if(bus.writes || (test==4&&bus.reads))return 10;
#else
  if(protect)ppc.r[4]=0;
  ppc_subfx(0x7d445051);
  if(protect)ppc.r[4]=damage;
#endif
  for(unsigned r=0;r<32;r++)emit(ppc.r[r]);for(unsigned r=0;r<32;r++)emit(ppc.fpr[r].id);for(unsigned r=0;r<8;r++)emit(ppc.cr[r]);
  emit(ppc.pc);emit(ppc.npc);emit(ppc.lr);emit(ppc.ctr);emit(ppc.xer);emit(ppc.msr);emit(ppc.icount);emit(ppc.cur_cycles);emit(bus.writes);
 }
#ifdef FIXTURE_NATIVE
 unsigned rejects=0;try{vf3_ppc_fixed(0x104a4,0x7d445050);}catch(const std::runtime_error&){++rejects;}
 try{vf3_ppc_fixed(0x800000,0x7d445051);}catch(const std::runtime_error&){++rejects;}if(rejects!=2)return 11;
#endif
}
