#ifndef TLOU_AP_BRIDGE_H
#define TLOU_AP_BRIDGE_H
#include <stdint.h>
#include <windows.h>

#define AP_MAGIC UINT64_C(0x3150474449524241)
#define AP_VERSION 5
#define AP_EVENT_PLAYER_DEATH 12
#define AP_EVENTS 512
#define AP_ROUTES 640
#define AP_WEAPONS 9

typedef struct {
    uint64_t weapon, ammo_sid;
    int32_t ammo, maximum, clip, reserved;
} APWeaponSupply;

typedef struct {
    uint64_t sid;
    int32_t mission;
    uint32_t reserved;
} APRoute;

typedef struct {
    uint64_t sequence, ticks, sid, extra;
    uint32_t type, flags, caller, mission;
} APEvent;

typedef struct {
    uint64_t magic;
    uint32_t version, size;
    volatile LONG status, error;
    uint64_t image_base, build_id;
    volatile LONG64 tick, heartbeat;
    volatile LONG mode, allowed, blocked, current;
    volatile LONG write, ack, dropped, pending;
    volatile LONG command_seq, command_type, command_arg, reply_seq;
    volatile LONG reply_status, detach;
    uint64_t command_receipt;
    uint32_t route_count, reserved;
    uint64_t reserved64[4];
    APRoute routes[AP_ROUTES];
    APEvent events[AP_EVENTS];
    /* Session-only DeathLink state. Counters reset with the game process. */
    volatile LONG death_enabled, death_state, death_local, death_remote;
    volatile LONG supply_revision;
    int32_t shivs, shiv_max, kit_max, weapon_count, supply_ready;
    APWeaponSupply weapons[AP_WEAPONS];
    volatile LONG64 airhorn_clock_ms;
    volatile LONG airhorn_ready;
    /* Reuses the ABI 4 reserved word: 0 outside, 1 playable task, 2 scripted. */
    uint32_t prologue_stage;
    int32_t resources[8], resource_max[8];
    volatile LONG64 effect_clock[2], effect_until[2], effect_lease;
    volatile LONG effect_mask, effect_supported;

} APShared;

#endif
