// GPL-3.0-or-later. Native threading primitives; rendering/audio live in the bridge.
#include "OSD/Thread.h"
#include <thread>
#include <mutex>
#include <condition_variable>
#include <chrono>
#include <stdexcept>
extern "C" { unsigned vf3_m68k_board = 0; }
struct ThreadState { std::thread thread; int result=0; };
struct SemaphoreState { std::mutex mutex; std::condition_variable cv; unsigned count; };
void CThread::Sleep(UINT32 ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
UINT32 CThread::GetTicks() { return (UINT32)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
CThread::CThread(const std::string& n,void* i):m_name(n),m_impl(i) {}
CThread* CThread::CreateThread(const std::string& n,ThreadStart start,void* arg) {
 auto s=new ThreadState; s->thread=std::thread([s,start,arg](){s->result=start(arg);}); return new CThread(n,s);
}
CThread::~CThread(){if(m_impl){auto s=(ThreadState*)m_impl;if(s->thread.joinable())s->thread.join();delete s;}}
const std::string& CThread::GetName() const{return m_name;}
UINT32 CThread::GetId(){return (UINT32)std::hash<std::thread::id>{}(((ThreadState*)m_impl)->thread.get_id());}
int CThread::Wait(){if(!m_impl)return 0;auto s=(ThreadState*)m_impl;s->thread.join();int r=s->result;delete s;m_impl=nullptr;return r;}
const char* CThread::GetLastError(){return "Native thread operation failed";}
CSemaphore* CThread::CreateSemaphore(UINT32 n){auto s=new SemaphoreState;s->count=n;return new CSemaphore(s);}
CSemaphore::CSemaphore(void* i):m_impl(i){} CSemaphore::~CSemaphore(){delete (SemaphoreState*)m_impl;}
UINT32 CSemaphore::GetValue(){auto s=(SemaphoreState*)m_impl;std::lock_guard<std::mutex> l(s->mutex);return s->count;}
bool CSemaphore::Wait(){auto s=(SemaphoreState*)m_impl;std::unique_lock<std::mutex> l(s->mutex);s->cv.wait(l,[s]{return s->count>0;});--s->count;return true;}
bool CSemaphore::Post(){auto s=(SemaphoreState*)m_impl;{std::lock_guard<std::mutex> l(s->mutex);++s->count;}s->cv.notify_one();return true;}
CMutex* CThread::CreateMutex(){return new CMutex(new std::mutex);}
CMutex::CMutex(void* i):m_impl(i){} CMutex::~CMutex(){delete (std::mutex*)m_impl;}
bool CMutex::Lock(){((std::mutex*)m_impl)->lock();return true;}bool CMutex::Unlock(){((std::mutex*)m_impl)->unlock();return true;}
CCondVar* CThread::CreateCondVar(){return new CCondVar(new std::condition_variable);}
CCondVar::CCondVar(void* i):m_impl(i){}CCondVar::~CCondVar(){delete (std::condition_variable*)m_impl;}
bool CCondVar::Wait(CMutex* mutex){std::unique_lock<std::mutex> l(*(std::mutex*)mutex->m_impl,std::adopt_lock);((std::condition_variable*)m_impl)->wait(l);l.release();return true;}
bool CCondVar::Signal(){((std::condition_variable*)m_impl)->notify_one();return true;}bool CCondVar::SignalAll(){((std::condition_variable*)m_impl)->notify_all();return true;}
