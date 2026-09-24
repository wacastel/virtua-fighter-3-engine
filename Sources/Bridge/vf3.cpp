// GPL-3.0-or-later. Standalone serial Model 3 engine and native macOS platform.
#include <GL/glew.h>
#include <OpenGL/OpenGL.h>
#include <CommonCrypto/CommonDigest.h>
#include "Supermodel.h"
#include "Model3/Model3.h"
#include "Graphics/New3D/New3D.h"
#include "Graphics/Render2D.h"
#include "Graphics/FBO.h"
#include "GameLoader.h"
#include "Inputs/Inputs.h"
#include "Inputs/Input.h"
#include "OSD/Audio.h"
#include "DefaultConfig.h"
#include "media_identity.h"
#if __has_include("settings_identity.h")
#include "settings_identity.h"
#define VF3_HAS_SETTINGS_SEED 1
#endif
#include <filesystem>
#include <fstream>
#include <memory>
#include <vector>
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <sstream>
#include <iomanip>
#include <ctime>

namespace fs=std::filesystem;
struct vf3_context {
 Util::Config::Node config=DefaultConfig();
 std::unique_ptr<CModel3> model;
 std::unique_ptr<CInputs> inputs;
 std::unique_ptr<SuperAA> aa;
 std::unique_ptr<CRender2D> r2;
 std::unique_ptr<New3D::CNew3D> r3;
 CGLContextObj gl=nullptr;
 FBO framebuffer;
 std::string error, saves;
 std::vector<uint8_t> pixels=std::vector<uint8_t>(496*384*4);
 std::vector<uint8_t> bottom=std::vector<uint8_t>(496*384*4);
 std::vector<int16_t> audio;
 uint64_t frame=0;
 uint64_t clockFrames=0;
 std::time_t clockBase=std::time(nullptr);
 uint32_t fault=0;
 bool loaded=false;
 bool invincible=false;
};
static vf3_context* active=nullptr;
unsigned vf3_default_framebuffer(){return active?active->framebuffer.GetFBOID():0;}
std::time_t vf3_clock(){return active?active->clockBase+(std::time_t)(active->clockFrames/60):std::time(nullptr);}
static std::string createError;
static std::string digestFile(const fs::path& path) {
 std::ifstream in(path,std::ios::binary);if(!in)throw std::runtime_error("Missing media: "+path.filename().string());
 CC_SHA256_CTX ctx;CC_SHA256_Init(&ctx);char bytes[65536];
 while(in){in.read(bytes,sizeof(bytes));if(in.gcount())CC_SHA256_Update(&ctx,bytes,(CC_LONG)in.gcount());}
 if(!in.eof())throw std::runtime_error("Could not read media");
 unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256_Final(digest,&ctx);
 std::ostringstream s;for(auto b:digest)s<<std::hex<<std::setw(2)<<std::setfill('0')<<(int)b;return s.str();
}
bool BeginFrameVideo(){return true;} void EndFrameVideo(){}
void SetAudioCallback(AudioCallbackFPtr,void*){} void SetAudioEnabled(bool){} void SetAudioType(Game::AudioTypes){}
Result OpenAudio(const Util::Config::Node&){return Result::OKAY;}void CloseAudio(){}
bool OutputAudio(unsigned n,const float* fl,const float* fr,const float* rl,const float* rr,bool flip){
 if(!active)return false;
 if(n>8192 || active->audio.size()+n*2>16384)throw std::runtime_error("PCM capacity exceeded");
 auto clamp=[](float f){return (int16_t)std::clamp((int)f,-32768,32767);};
 for(unsigned i=0;i<n;i++){auto l=clamp((fl[i]+rl[i])*0.5f),r=clamp((fr[i]+rr[i])*0.5f);active->audio.push_back(flip?r:l);active->audio.push_back(flip?l:r);}
 return false;
}
extern "C" {
void vf3_native_fault(const char* message){throw std::runtime_error(message);}
#ifdef VF3_REFERENCE
void vf3_reference_probe_marker(){}
uint64_t vf3_reference_frame_number(){return active?active->frame:0;}
#endif
bool vf3_player_one_invincible(){return active && active->loaded && !active->fault && active->invincible;}
int vf3_set_invincible(vf3_context* c,int enabled){
 if(!c||c!=active||c->fault)return 0;
 if(enabled!=0&&enabled!=1){c->error="Invincibility must be 0 or 1";return 0;}
#if !defined(VF3_INVINCIBILITY_VERIFIED)
 if(enabled){c->error="Invincibility is unavailable in this engine";return 0;}
#endif
 c->invincible=enabled!=0;return 1;
}
int vf3_get_invincible(vf3_context* c){return c&&c==active&&!c->fault&&c->invincible?1:0;}
const char* vf3_error(const vf3_context* c){return c?c->error.c_str():createError.c_str();}
uint32_t vf3_fault_code(const vf3_context* c){return c?c->fault:1;}
void vf3_destroy(vf3_context* c){
 if(!c||c!=active)return;
 if(c->gl)CGLSetCurrentContext(c->gl);
 if(c->loaded){CBlockFile nv;if(nv.Create(c->saves+"/vf3.nv","VF3 NVRAM","Local original cabinet settings")==Result::OKAY)c->model->SaveNVRAM(&nv);}
 c->model.reset();c->r3.reset();c->r2.reset();c->aa.reset();c->framebuffer.Destroy();
 if(c->gl){CGLSetCurrentContext(nullptr);CGLDestroyContext(c->gl);}active=nullptr;delete c;
}
vf3_context* vf3_create(const char* assets,const char* saves){
 if(active){createError="A game session is already active";return nullptr;}
 if(!assets||!saves){createError="Missing asset or save directory";return nullptr;}
 auto c=new vf3_context;active=c;
 try {
  if(digestFile(fs::path(assets)/"vf3.zip")!=vf3_zip_sha256 || digestFile(fs::path(assets)/"Games.xml")!=vf3_xml_sha256)throw std::runtime_error("Game media does not match verified Revision D");
  fs::create_directories(saves);c->saves=saves;
#ifdef VF3_HAS_SETTINGS_SEED
  bool factory=false;
#ifdef VF3_REFERENCE
  factory=std::getenv("VF3_FACTORY_SETTINGS")!=nullptr;
#endif
  if(!factory&&!fs::exists(fs::path(saves)/"vf3.nv")){
   auto seed=fs::path(assets)/"default.nv";
   if(digestFile(seed)!=vf3_settings_sha256)throw std::runtime_error("Default cabinet settings identity mismatch");
   fs::copy_file(seed,fs::path(saves)/"vf3.nv");
  }
#endif
  if(const char* epoch=std::getenv("VF3_RTC_EPOCH")){
   char* end=nullptr;auto value=std::strtoll(epoch,&end,10);
   if(!*epoch||*end||value<946684800||value>4102444800LL)throw std::runtime_error("Invalid cabinet clock epoch");
   c->clockBase=(std::time_t)value;
  }
  SetLogger(std::make_shared<CConsoleErrorLogger>());
  CGLPixelFormatAttribute attrs[]={kCGLPFAOpenGLProfile,(CGLPixelFormatAttribute)kCGLOGLPVersion_GL4_Core,kCGLPFAAccelerated,kCGLPFAColorSize,(CGLPixelFormatAttribute)24,kCGLPFADepthSize,(CGLPixelFormatAttribute)24,(CGLPixelFormatAttribute)0};
  CGLPixelFormatObj pf=nullptr;GLint count=0;
  if(CGLChoosePixelFormat(attrs,&pf,&count)!=kCGLNoError||!pf)throw std::runtime_error("OpenGL 4.1 pixel format unavailable");
  auto result=CGLCreateContext(pf,nullptr,&c->gl);CGLDestroyPixelFormat(pf);
  if(result!=kCGLNoError||!c->gl)throw std::runtime_error("Could not create graphics context");
  CGLSetCurrentContext(c->gl);glewExperimental=GL_TRUE;
  if(glewInit()!=GLEW_OK)throw std::runtime_error("Could not initialize graphics functions");
  while(glGetError()!=GL_NO_ERROR){}
  if(!c->framebuffer.Create(496,384))throw std::runtime_error("Could not create game framebuffer");
  glViewport(0,0,496,384);glEnable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);
  glEnable(GL_SCISSOR_TEST);glScissor(2,2,492,380);
  c->inputs=std::make_unique<CInputs>(nullptr);
  c->model=std::make_unique<CModel3>(c->config);
  Game game;ROMSet roms;GameLoader loader((fs::path(assets)/"Games.xml").string());
  if(loader.Load(&game,&roms,(fs::path(assets)/"vf3.zip").string())||game.name!="vf3")throw std::runtime_error("Could not load verified Revision D");
  if(c->model->Init()!=Result::OKAY||c->model->LoadGame(game,roms)!=Result::OKAY)throw std::runtime_error("Could not initialize Model 3 hardware");
  c->model->AttachInputs(c->inputs.get());
  if(fs::exists(fs::path(saves)/"vf3.nv")){CBlockFile nv;if(nv.Load(c->saves+"/vf3.nv")!=Result::OKAY)throw std::runtime_error("Could not load cabinet settings");c->model->LoadNVRAM(&nv);}else c->model->ClearNVRAM();
  c->aa=std::make_unique<SuperAA>(1,CRTcolor::None);c->aa->Init(496,384);
  c->r2=std::make_unique<CRender2D>(c->config);c->r3=std::make_unique<New3D::CNew3D>(c->config,game.name);
  auto fbo=c->framebuffer.GetFBOID();
  if(c->r2->Init(0,0,496,384,496,384,fbo,UpscaleMode::Nearest)!=Result::OKAY||c->r3->Init(0,0,496,384,496,384,fbo)!=Result::OKAY)throw std::runtime_error("Could not initialize game renderer");
  c->model->AttachRenderers(c->r2.get(),c->r3.get(),c->aa.get());
  c->model->Reset();c->loaded=true;
  while(glGetError()!=GL_NO_ERROR){}
  return c;
 } catch(const std::exception& e){createError=e.what();vf3_destroy(c);return nullptr;}
}
int vf3_step(vf3_context* c,uint32_t player1,uint32_t player2){
 if(!c||c!=active||c->fault)return 0;
 uint32_t allowed1=1023u;
#ifdef VF3_REFERENCE
 allowed1|=(1u<<16)|(1u<<17);
#endif
 if((player1&~allowed1)||(player2&~1023u)||((player1&3)==3)||((player1&12)==12)||((player2&3)==3)||((player2&12)==12)){
  c->error="Invalid fighting input";return 0;
 }
 try{
  CGLSetCurrentContext(c->gl);auto& i=*c->inputs;
  const uint32_t players[]={player1,player2};
  for(unsigned p=0;p<2;p++){
   auto buttons=players[p];
   i.up[p]->value=(buttons>>0)&1;i.down[p]->value=(buttons>>1)&1;
   i.left[p]->value=(buttons>>2)&1;i.right[p]->value=(buttons>>3)&1;
   i.punch[p]->value=(buttons>>4)&1;i.kick[p]->value=(buttons>>5)&1;
   i.guard[p]->value=(buttons>>6)&1;i.escape[p]->value=(buttons>>7)&1;
   i.start[p]->value=(buttons>>8)&1;i.coin[p]->value=(buttons>>9)&1;
  }
#ifdef VF3_REFERENCE
  i.test[0]->value=(player1>>16)&1;i.service[0]->value=(player1>>17)&1;
#endif
  c->audio.clear();c->model->RunFrame();
  glBindFramebuffer(GL_READ_FRAMEBUFFER,c->framebuffer.GetFBOID());
  glReadBuffer(GL_COLOR_ATTACHMENT0);glPixelStorei(GL_PACK_ALIGNMENT,1);glReadPixels(0,0,496,384,GL_RGBA,GL_UNSIGNED_BYTE,c->bottom.data());
  auto glError=glGetError();if(glError!=GL_NO_ERROR)throw std::runtime_error("Graphics readback failed: "+std::to_string(glError));
  for(unsigned y=0;y<384;y++)std::copy_n(c->bottom.data()+(383-y)*496*4,496*4,c->pixels.data()+y*496*4);
  for(size_t n=3;n<c->pixels.size();n+=4)c->pixels[n]=255;
  ++c->frame;++c->clockFrames;return 1;
 }catch(const std::exception& e){c->error=e.what();c->fault=1;return 0;}
}
const uint8_t* vf3_pixels(const vf3_context* c){return c?c->pixels.data():nullptr;}
const int16_t* vf3_audio(const vf3_context* c){return c?c->audio.data():nullptr;}
int vf3_audio_count(const vf3_context* c){return c?(int)c->audio.size()/2:0;}
int vf3_width(const vf3_context*){return 496;}int vf3_height(const vf3_context*){return 384;}
double vf3_frame_rate(const vf3_context*){return 60.;}int vf3_audio_sample_rate(const vf3_context*){return 44100;}
uint64_t vf3_frame_number(const vf3_context* c){return c?c->frame:0;}
#if defined(VF3_REFERENCE) || defined(VF3_DIAGNOSTIC)
#ifdef VF3_DIAGNOSTIC
void vf3_diagnostic_engine_marker(){}
#endif
uint32_t vf3_diagnostic_read32(vf3_context* c,uint32_t address){return c->model->Read32(address);}
uint32_t vf3_diagnostic_pc(vf3_context*){return ppc_get_pc();}
uint32_t vf3_diagnostic_gpr(vf3_context*,unsigned n){return ppc_get_gpr(n);}
void vf3_diagnostic_save_state(vf3_context* c,const char* path){CBlockFile file;if(file.Create(path,"VF3 lab state","Original reference only")==Result::OKAY)c->model->SaveState(&file);}
#endif
}
