// GPL-3.0-or-later. The single-cabinet product fixes Network=false.
#pragma once
#include "Network/INetBoard.h"
class DetachedNetwork final : public INetBoard {
public:
 void SaveState(CBlockFile*) override {} void LoadState(CBlockFile*) override {}
 void RunFrame() override {} void Reset() override {}
 bool IsAttached() override { return false; } bool IsRunning() override { return false; }
 Result Init(UINT8*,UINT8*) override { return Result::OKAY; }
 void GetGame(const Game&) override {}
 UINT8 ReadCommRAM8(unsigned) override { return 0; }
 UINT16 ReadCommRAM16(unsigned) override { return 0; }
 UINT32 ReadCommRAM32(unsigned) override { return 0; }
 void WriteCommRAM8(unsigned,UINT8) override {} void WriteCommRAM16(unsigned,UINT16) override {}
 void WriteCommRAM32(unsigned,UINT32) override {}
 UINT16 ReadIORegister(unsigned) override { return 0; } void WriteIORegister(unsigned,UINT16) override {}
};
