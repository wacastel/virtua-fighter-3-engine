// GPL-3.0-or-later
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct vf3_context vf3_context;
enum vf3_button {
 VF3_UP=1, VF3_DOWN=2, VF3_LEFT=4, VF3_RIGHT=8,
 VF3_PUNCH=16, VF3_KICK=32, VF3_GUARD=64, VF3_EVADE=128,
 VF3_START=256, VF3_COIN=512
};
/* One serialized process-wide session. Independent processes keep separate
 * cabinet state. assets contains canonical vf3.zip and Games.xml; saves
 * is writable app-owned storage. Every media identity is checked before load.
 */
vf3_context* vf3_create(const char* assets,const char* saves);
void vf3_destroy(vf3_context*);
const char* vf3_error(const vf3_context*);
uint32_t vf3_fault_code(const vf3_context*);
/* One video interval with per-player masks. Opposite directions and unknown
 * bits are rejected without advancing. Returns 1 on success, 0 on error.
 * Buffers survive until the next call. Top-down RGBA8888 and interleaved
 * native-endian signed16 stereo; audio_count is stereo sample frames.
 * Restart by destroying and recreating the context on its owning thread.
 */
int vf3_step(vf3_context*,uint32_t player1,uint32_t player2);
/* Optional first-player damage protection, initially OFF. The value must be
 * exactly 0 or 1; the original reference rejects enabling. Returns 1 on success.
 * Destroy/recreate resets this setting to OFF. */
int vf3_set_invincible(vf3_context*,int enabled);
int vf3_get_invincible(vf3_context*);
const uint8_t* vf3_pixels(const vf3_context*);
const int16_t* vf3_audio(const vf3_context*);
int vf3_audio_count(const vf3_context*);
int vf3_width(const vf3_context*);
int vf3_height(const vf3_context*);
double vf3_frame_rate(const vf3_context*);
int vf3_audio_sample_rate(const vf3_context*);
uint64_t vf3_frame_number(const vf3_context*);
#ifdef __cplusplus
}
#endif
