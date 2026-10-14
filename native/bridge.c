/* Native game-thread bridge. Exact executable fingerprints are verified by the
 * loader; hook prologues are also verified here before changing any code.
 * MinHook is used under its BSD-2-Clause license (see THIRD_PARTY_NOTICES).
 */
#include "bridge.h"
#include "MinHook.h"
#include "anchors.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include <math.h>

_Static_assert(sizeof(APShared) == 35432, "Shared ABI size");
_Static_assert(offsetof(APShared, routes) == 160, "Shared route offset");
_Static_assert(offsetof(APShared, events) == 10400, "Shared event offset");

typedef bool (*TickFn)(void *);
typedef void (*PlayFn)(void *, uint64_t, int, const int64_t *, bool, bool);
typedef bool (*BeginFn)(void *, uint64_t);
typedef void (*AutomaticFn)(void *);
typedef bool (*ReadyFn)(void *);
typedef bool (*PauseUpdateFn)(void *);
typedef void (*ClockUpdateFn)(void *, float);
typedef void (*PickupFn)(void *, uint64_t, bool, bool);
typedef void (*ProfileTreasureFn)(void *, uint64_t, bool);
typedef void (*CompleteFn)(void *, int);

static APShared *shared;
static uintptr_t base;
static TickFn original_tick;
static PlayFn original_play;
static BeginFn original_begin;
static AutomaticFn original_automatic;
static ReadyFn automatic_ready;
static PauseUpdateFn original_pause_update;
static ClockUpdateFn original_clock_update;
static int engine_mission = -1, engine_blocked = -1;
static bool engine_in_menu;
#define ENGINE_GATE_FLAG 0x20000000u
static PickupFn original_pickup;
static ProfileTreasureFn original_profile_treasure;
static CompleteFn original_complete;
static SRWLOCK event_lock = SRWLOCK_INIT;
static SRWLOCK pending_lock = SRWLOCK_INIT;
static volatile LONG running;
typedef enum { START_PLAY, START_BEGIN, START_AUTOMATIC } StartKind;
typedef struct {
    uint64_t sid, continuation;
    int64_t time;
    int state, mission;
    bool has_time, arg5, arg6;
    StartKind kind;
} PendingPlay;
static PendingPlay pending_plays[64];
static unsigned pending_count;
/* Admission belongs to the whole transition. A host mask update must not hold
 * the nested Play call after Begin has already cleaned up the current scene. */
static _Thread_local int admitted_mission = -1;
typedef struct { uint64_t id; int type, result; } Receipt;
static Receipt receipts[8192];
static unsigned receipt_count;
static void reset_supply_stage(void);
static void update_death_link(void);
static int receive_death(int expected_mission, uint64_t receipt);
static bool supply_playable(void *player);
static void update_airhorn(void);
static void update_timed_effects(uint64_t elapsed, bool ready);
static int receive_airhorn(int expected_mission, uint64_t receipt);
static void effects_task_started(uint64_t sid, int mission);

static void engine_start(uint64_t sid, int mission) {
    effects_task_started(sid, mission);
    if (sid == UINT64_C(0xa823deeb3a672718)) {
        engine_mission = -1;
        engine_in_menu = true;
    } else if (mission >= 0) {
        engine_mission = mission;
        engine_in_menu = false;
    }
}

static uint32_t start_flags(const PendingPlay *request) {
    return request->kind == START_BEGIN ? 0x80000000u
        : request->kind == START_AUTOMATIC ? 0x40000000u : (uint32_t)request->state;
}

static bool read_local(uintptr_t address, void *output, SIZE_T size) {
    SIZE_T actual = 0;
    return address >= 0x10000 && ReadProcessMemory(GetCurrentProcess(), (void *)address,
                                                  output, size, &actual) && actual == size;
}

static int mission_for(uint64_t sid) {
    uint32_t count = shared->route_count;
    if (count > AP_ROUTES) return -1;
    for (uint32_t i = 0; i < count; ++i)
        if (shared->routes[i].sid == sid) return shared->routes[i].mission;
    return -1;
}

static void event(uint32_t type, uint64_t sid, uint64_t extra, uint32_t flags,
                  uintptr_t caller, int mission) {
    AcquireSRWLockExclusive(&event_lock);
    uint32_t write = (uint32_t)shared->write, ack = (uint32_t)shared->ack;
    if (write - ack >= AP_EVENTS) {
        InterlockedIncrement(&shared->dropped);
    } else {
        APEvent *e = &shared->events[write % AP_EVENTS];
        e->sequence = (uint64_t)write + 1;
        e->ticks = GetTickCount64();
        e->sid = sid; e->extra = extra; e->type = type; e->flags = flags;
        e->caller = caller >= base && caller - base < 0x9000000 ? (uint32_t)(caller - base) : 0;
        e->mission = (uint32_t)(mission + 1);
        InterlockedExchange(&shared->write, (LONG)(write + 1));
    }
    ReleaseSRWLockExclusive(&event_lock);
}

static bool permitted(int mission) {
    if (!shared->mode || mission < 0) return true;
    if (GetTickCount64() - (uint64_t)shared->heartbeat > 5000) return false;
    return mission < 29 && ((uint32_t)shared->allowed & (1u << mission));
}

static void *find_node(uint64_t sid) {
    uint32_t count = 0, story = 1;
    uintptr_t cache = base + 0x47fe910;
    read_local(cache, &count, 4); read_local(cache + 4, &story, 4);
    if (count != 602 || story != 0) return NULL;
    uintptr_t nodes[602];
    if (!read_local(cache + 0x30, nodes, sizeof(nodes))) return NULL;
    for (unsigned i = 0; i < 602; ++i) {
        uint64_t actual = 0;
        if (read_local(nodes[i] + 0x28, &actual, 8) && actual == sid) return (void *)nodes[i];
    }
    return NULL;
}

static void defer_play(PendingPlay request, uintptr_t caller) {
    AcquireSRWLockExclusive(&pending_lock);
    bool duplicate = false;
    for (unsigned i = 0; i < pending_count; ++i)
        if (pending_plays[i].sid == request.sid && pending_plays[i].kind == request.kind) {
            /* A later checkpoint/menu request supersedes its earlier arguments. */
            pending_plays[i] = request;
            duplicate = true;
        }
    if (!duplicate && pending_count < 64) pending_plays[pending_count++] = request;
    else if (!duplicate) shared->error = 401;
    shared->pending = pending_count;
    shared->blocked = request.mission + 1;
    ReleaseSRWLockExclusive(&pending_lock);
    if (!duplicate) event(3, request.sid, request.continuation,
                          start_flags(&request), caller, request.mission);
}

static bool begin_admitted(void *node, uint64_t continuation, int mission) {
    int previous = admitted_mission;
    admitted_mission = mission;
    bool result = original_begin(node, continuation);
    admitted_mission = previous;
    return result;
}

static void play_admitted(void *node, const PendingPlay *request) {
    int previous = admitted_mission;
    admitted_mission = request->mission;
    original_play(node, request->continuation, request->state,
                  request->has_time ? &request->time : NULL, request->arg5, request->arg6);
    admitted_mission = previous;
}

/* Begin performs cleanup/setup before calling Play. Deferring only the nested
 * Play leaves a half-transitioned scene, notably when a cinematic is skipped. */
static bool consume_pending(uint64_t sid, StartKind kind) {
    bool removed = false;
    AcquireSRWLockExclusive(&pending_lock);
    for (unsigned i = 0; i < pending_count; ) {
        if (pending_plays[i].sid == sid && pending_plays[i].kind == kind) {
            memmove(&pending_plays[i], &pending_plays[i + 1],
                    (pending_count - i - 1) * sizeof(PendingPlay));
            --pending_count; removed = true;
        } else ++i;
    }
    shared->pending = pending_count;
    shared->blocked = pending_count ? pending_plays[0].mission + 1 : 0;
    ReleaseSRWLockExclusive(&pending_lock);
    return removed;
}

static bool hook_begin(void *node, uint64_t continuation) {
    reset_supply_stage();
    uint64_t sid = 0;
    read_local((uintptr_t)node + 0x28, &sid, 8);
    int mission = mission_for(sid);
    if (shared->mode == 2) {
        engine_start(sid, mission);
        return begin_admitted(node, continuation, mission);
    }
    if (!permitted(mission)) {
        defer_play((PendingPlay){.sid = sid, .continuation = continuation,
                                 .mission = mission, .kind = START_BEGIN},
                   (uintptr_t)__builtin_return_address(0));
        return true; /* Request accepted by our deferred queue. */
    }
    if (consume_pending(sid, START_BEGIN))
        event(4, sid, continuation, 0x80000000u, 0, mission);
    return begin_admitted(node, continuation, mission);
}

/* Graph Update normally advances ready nodes through 0x626e80, bypassing both
 * Begin and Play. Hold before it changes state 0 -> 2 or starts loading/scripts.
 * Graph Update clears its dirty flag afterward, so we retain a replay request
 * and recheck the original readiness predicate before executing it. */
static void hook_automatic(void *node) {
    reset_supply_stage();
    uint64_t sid = 0;
    read_local((uintptr_t)node + 0x28, &sid, 8);
    int mission = mission_for(sid);
    if (shared->mode == 2) {
        engine_start(sid, mission);
        original_automatic(node);
        event(1, sid, 0, 0x40000000u, (uintptr_t)__builtin_return_address(0), mission);
        return;
    }
    if (!(mission >= 0 && admitted_mission == mission) && !permitted(mission)) {
        defer_play((PendingPlay){.sid = sid, .mission = mission, .kind = START_AUTOMATIC},
                   (uintptr_t)__builtin_return_address(0));
        return;
    }
    if (consume_pending(sid, START_AUTOMATIC))
        event(4, sid, 0, 0x40000000u, 0, mission);
    event(1, sid, 0, 0x40000000u, (uintptr_t)__builtin_return_address(0), mission);
    original_automatic(node);
    /* Telemetry resolves the active player task; automatic graph nodes can
     * also be non-player tasks, so do not assign shared->current here. */
}

static void replay_pending(void) {
    for (unsigned step = 0; step < 64; ++step) {
        PendingPlay request;
        bool found = false;
        AcquireSRWLockExclusive(&pending_lock);
        for (unsigned i = 0; i < pending_count; ++i) {
            if (permitted(pending_plays[i].mission)) {
                request = pending_plays[i];
                memmove(&pending_plays[i], &pending_plays[i + 1],
                        (pending_count - i - 1) * sizeof(PendingPlay));
                --pending_count; found = true; break;
            }
        }
        shared->pending = pending_count;
        if (!pending_count) shared->blocked = 0;
        ReleaseSRWLockExclusive(&pending_lock);
        if (!found) break;
        void *node = find_node(request.sid);
        if (!node) { shared->error = 402; continue; }
        if (request.kind == START_AUTOMATIC && !automatic_ready(node)) {
            event(8, request.sid, 0, start_flags(&request), 0, request.mission);
            continue; /* Another load/reset invalidated this graph request. */
        }
        event(4, request.sid, request.continuation, start_flags(&request), 0, request.mission);
        if (request.kind == START_BEGIN && !begin_admitted(node, request.continuation, request.mission)) {
            shared->error = 405; break;
        }
        else if (request.kind == START_PLAY) play_admitted(node, &request);
        else if (request.kind == START_AUTOMATIC) {
            int previous = admitted_mission;
            admitted_mission = request.mission;
            hook_automatic(node);
            admitted_mission = previous;
        }
        if (request.kind != START_AUTOMATIC) shared->current = request.mission + 1;
    }
}

typedef void *(*ObjectFn)(void *);
typedef void *(*PlayerWeaponFn)(void **);
typedef int (*QuantityFn)(void *, uint64_t);
typedef uint64_t *(*AmmoSidFn)(void *, uint64_t *);
typedef int (*CountFn)(void *);
typedef int (*AddAmmoFn)(void *, void *, int);
typedef void (*AddItemFn)(uint64_t, int);

typedef struct {
    void *player, *weapon, *inventory;
    uint64_t ammo_sid;
    int ammo, kits, shivs, kit_max, shiv_max, weapon_count;
    bool ready;
    APWeaponSupply weapons[AP_WEAPONS];
    int resources[8], resource_max[8];
} Supplies;
static const uint64_t resource_sids[8] = {
    UINT64_C(0xe93dfef138c585c1), UINT64_C(0x482c6a557353fa5d), UINT64_C(0x4006421e254c7891), UINT64_C(0xa98b958bc05e1da2), UINT64_C(0x995081d9b5b7eef4), UINT64_C(0x355f7b26b69abf05), UINT64_C(0x0104091a0ade59c5), UINT64_C(0xabe4a656ca19db60)};
#define KIT_SID UINT64_C(0x1ea95d464b68c80a)
#define SHIV_SID UINT64_C(0xf2fc45dc883b4b79)

/* GameInventory's maximum query uses the active checkpoint's entry when it
 * exists and falls back to its definition only for an absent (empty) slot. */
static int inventory_max(void *inventory, uint64_t sid) {
    return ((QuantityFn)(base + 0x17f0df4))(inventory, sid);
}

static bool supported_ammo(uint64_t sid) {
    /* Main-story inventory definitions from dc1/t1x-player-inventory.bin. */
    static const uint64_t ids[] = {
        UINT64_C(0xb4ce74acb1317617), UINT64_C(0xdde675074fc76559),
        UINT64_C(0xe908b9ecc7744100), UINT64_C(0xd40070113c4fc14c),
        UINT64_C(0xafdab42da5eaf722), UINT64_C(0xe6ecc33c5c55c8b4),
        UINT64_C(0x1f586b9100862fcb), UINT64_C(0x9265cc580d411f4a),
        UINT64_C(0x4226188df8bb50f0)};
    for (unsigned i = 0; i < sizeof(ids) / sizeof(ids[0]); ++i)
        if (sid == ids[i]) return true;
    return false;
}

static bool supplies(Supplies *value) {
    memset(value, 0, sizeof(*value));
    value->kits = value->ammo = value->shivs = value->kit_max = value->shiv_max = -1;
    void *context = ((PlayerWeaponFn)(base + 0x19e17e8))(&value->player);
    if (!value->player) return false;
    value->inventory = ((ObjectFn)(base + 0x1a95d44))(value->player);
    if (!value->inventory) return false;
    value->kits = ((QuantityFn)(base + 0x17f0e68))(value->inventory, KIT_SID);
    value->kit_max = inventory_max(value->inventory, KIT_SID);
    value->shivs = ((QuantityFn)(base + 0x17f0e68))(value->inventory, SHIV_SID);
    value->shiv_max = inventory_max(value->inventory, SHIV_SID);
    for (int i = 0; i < 8; ++i) {
        value->resources[i] = ((QuantityFn)(base + 0x17f0e68))(value->inventory, resource_sids[i]);
        value->resource_max[i] = inventory_max(value->inventory, resource_sids[i]);
    }
    value->ready = supply_playable(value->player);
    /* Ellie has a permanent switchblade. Keep crafted-shiv gifts queued. */
    if (((QuantityFn)(base + 0x17f0e68))(value->inventory, UINT64_C(0xdb3aa7387e4260cd)) > 0)
        value->shiv_max = 0;
    int count = 0;
    uintptr_t rows = 0;
    if (!read_local((uintptr_t)value->inventory, &count, 4) || count < 0 || count > 256
            || !read_local((uintptr_t)value->inventory + 8, &rows, 8)) return false;
    for (int i = 0; i < count; ++i) {
        unsigned char row[0x38];
        if (!read_local(rows + (uintptr_t)i * sizeof(row), row, sizeof(row))) return false;
        uint64_t ammo_sid = 0;
        memcpy(&ammo_sid, row + 8, 8);
        int owned = 0;
        memcpy(&owned, row + 0x10, 4);
        if (owned <= 0 || !supported_ammo(ammo_sid)) continue;
        void *object = ((ObjectFn)(base + 0x12001fc))(row + 0x28);
        void *weapon = ((ObjectFn)(base + 0x1dbde04))(object);
        if (!weapon) continue;
        uint64_t actual = 0;
        ((AmmoSidFn)(base + 0x1dbe3ac))(weapon, &actual);
        if (actual != ammo_sid) return false;
        /* One grant per ammo type even if a scripted inventory duplicates it. */
        bool duplicate = false;
        for (int j = 0; j < value->weapon_count; ++j)
            if (value->weapons[j].ammo_sid == ammo_sid) duplicate = true;
        if (duplicate) continue;
        /* PlayerInventory::IsFull (0x18ef82c) compares this maximum with
         * reserve + loaded. Clip upgrades are already included by the query. */
        int maximum = inventory_max(value->inventory, ammo_sid);
        int clip = ((CountFn)(base + 0x1dbec54))(weapon);
        int loaded = ((CountFn)(base + 0x12bc06c))(weapon);
        int reserve = ((QuantityFn)(base + 0x17f0e68))(value->inventory, ammo_sid);
        if (maximum < 1 || maximum > 11000 || clip < 1 || clip > 1000 || loaded < 0 || loaded > clip
                || reserve < 0 || reserve > 10000 || value->weapon_count >= AP_WEAPONS) return false;
        value->weapons[value->weapon_count++] = (APWeaponSupply){(uintptr_t)weapon, ammo_sid,
            loaded + reserve, maximum, clip, 0};
    }
    value->weapon = ((ObjectFn)(base + 0x1dbde04))(context);
    if (value->weapon) {
        ((AmmoSidFn)(base + 0x1dbe3ac))(value->weapon, &value->ammo_sid);
        if (supported_ammo(value->ammo_sid)) {
            value->ammo = ((CountFn)(base + 0x12bc06c))(value->weapon)
                + ((QuantityFn)(base + 0x17f0e68))(value->inventory, value->ammo_sid);
        }
    }
    return true;
}

static const uint64_t tool_sids[5] = {UINT64_C(0x9647115aeb40ab24),
    UINT64_C(0x9647145aeb40b03d), UINT64_C(0x9647135aeb40ae8a),
    UINT64_C(0x96470e5aeb40a60b), UINT64_C(0x96470d5aeb40a458)};

/* Tool levels are consecutive treasure inventory entries, not the physical
 * toolbox locations. This is the same list serialized as "tool-level" by
 * InventoryState::Capture/Restore (0x17ed568 / 0x17eed9c). */
static int native_tool_level(void) {
    uintptr_t manager = 0;
    uint32_t count = 0, mask = 0;
    uint64_t entries[350];
    if (!read_local(base + 0x48a6ee8, &manager, 8) || !manager
            || !read_local(manager + 0xc50, &count, 4) || count > 350
            || (count && !read_local(manager, entries, count * 8))) return -1;
    for (uint32_t i = 0; i < count; ++i)
        for (int j = 0; j < 5; ++j) if (entries[i] == tool_sids[j]) mask |= 1u << j;
    for (int level = 0; level <= 5; ++level)
        if (mask == ((1u << level) - 1)) return level;
    return -1; /* Do not guess when a foreign inventory is nonconsecutive. */
}

static void native_tool_floor(int target) {
    uintptr_t manager = 0;
    if (!read_local(base + 0x48a6ee8, &manager, 8) || !manager) return;
    int current = native_tool_level();
    if (current < 0 || target < 1 || target > 5) return;
    for (int i = current; i < target; ++i)
        original_pickup((void *)manager, tool_sids[i], false, false);
}

static int (*read_tool_level)(void) = native_tool_level;
static void (*apply_tool_floor)(int) = native_tool_floor;

static void publish_supplies(const Supplies *value) {
    InterlockedIncrement(&shared->supply_revision);
    shared->reserved64[0] = (uintptr_t)value->player;
    shared->reserved64[1] = (uintptr_t)value->weapon;
    shared->reserved64[2] = (uint32_t)value->kits | ((uint64_t)(uint32_t)value->ammo << 32);
    shared->reserved64[3] = value->ammo_sid;
    shared->shivs = value->shivs; shared->shiv_max = value->shiv_max;
    shared->kit_max = value->kit_max; shared->weapon_count = value->weapon_count;
    shared->supply_ready = value->ready;
    memcpy(shared->resources, value->resources, sizeof(value->resources));
    memcpy(shared->resource_max, value->resource_max, sizeof(value->resource_max));
    memcpy(shared->weapons, value->weapons, sizeof(value->weapons));
    shared->weapons[0].reserved = read_tool_level();
    InterlockedIncrement(&shared->supply_revision);
}

static uint64_t active_task(void) {
    void *active = ((ObjectFn)(base + 0x5ea8f0))((void *)(base + 0x471ce10));
    uint64_t sid = 0;
    if (active) read_local((uintptr_t)active + 0x28, &sid, 8);
    return sid;
}

static int active_mission(void) { return mission_for(active_task()); }

/* The opening backpack script replaces the inventory after granting its
 * collectibles. Historical completion/profile flags survive checkpoint loads,
 * so eligibility follows the currently executing task and inventory instead. */
#define BACKPACK_TASK UINT64_C(0x767ea56e286f3e65)
/* Live testing found this opening deer-hunt task restores Ellie's arrows on
 * the next frame. Preserve the whole ammo gift until the task has ended. */
#define DEER_HUNT_TASK UINT64_C(0x8f50a5b5bb1a9bd0)
#define SUPPLY_SETTLE_MS 2000
static struct {
    void *player, *inventory;
    uint64_t task, since;
    int mission;
    bool valid;
} supply_stage;

static void reset_supply_stage(void) { supply_stage.valid = false; }

static bool supply_stage_ready(int mission, uint64_t task, const Supplies *value, uint64_t now) {
    if (mission < 2 || mission > 28 || mission_for(task) != mission
            || (mission == 2 && task == BACKPACK_TASK)
            || !value->player || !value->inventory) {
        supply_stage.valid = false;
        return false;
    }
    if (!supply_stage.valid || supply_stage.player != value->player
            || supply_stage.inventory != value->inventory || supply_stage.task != task
            || supply_stage.mission != mission || now < supply_stage.since) {
        supply_stage.player = value->player; supply_stage.inventory = value->inventory;
        supply_stage.task = task; supply_stage.mission = mission;
        supply_stage.since = now; supply_stage.valid = true;
    }
    return now - supply_stage.since >= SUPPLY_SETTLE_MS;
}

/* Materials use quarter-units; grant four for one full crafting unit.
 * Full slots are skipped, like full weapons in an Ammo Supply batch. */
static int resource_amount(int type, int index, const Supplies *value) {
    if (type < 11 || type > 13 || index < 0 || index >= 8) return 0;
    int amount = type == 11 && index < 6 ? 4 : type == 12 && index == 6 ? 25
                 : type == 13 && index == 7 ? 10 : 0;
    int cap = value->resource_max[index], count = value->resources[index];
    if (cap != (index < 6 ? 12 : 9999) || count < 0 || count > cap) return 0;
    return amount > cap - count ? cap - count : amount;
}
static bool resource_ready(int type, const Supplies *value) {
    bool room = false;
    for (int i = 0; i < 8; ++i) {
        if ((type == 11 && i < 6) || (type == 12 && i == 6) || (type == 13 && i == 7)) {
            int cap = value->resource_max[i];
            if (cap != (i < 6 ? 12 : 9999) || value->resources[i] < 0 || value->resources[i] > cap) return false;
            room |= resource_amount(type, i, value) > 0;
        }
    }
    return room;
}
static int resource_result(int type, const Supplies *before, const Supplies *after) {
    bool applied = false, missed = false;
    for (int i = 0; i < 8; ++i) {
        if (before->resource_max[i] != after->resource_max[i]) return 3;
        int amount = resource_amount(type, i, before), delta = after->resources[i] - before->resources[i];
        if (delta == amount) applied |= delta > 0;
        else if (delta == 0) missed |= amount > 0;
        else return 3;
    }
    return applied ? (missed ? 3 : 1) : 2;
}
static void add_supply(int type, int quantity, const Supplies *before) {
    if (type >= 11 && type <= 13) {
        for (int i = 0; i < 8; ++i) {
            int amount = resource_amount(type, i, before);
            if (amount) ((AddItemFn)(base + 0x19e02e4))(resource_sids[i], amount);
        }
    } else if (type == 1) ((AddAmmoFn)(base + 0x1db85d8))(before->weapon, before->inventory, quantity);
    else if (type == 4) {
        for (int i = 0; i < before->weapon_count; ++i) {
            const APWeaponSupply *w = &before->weapons[i];
            int amount = (w->maximum + 1) / 2;
            if (amount > w->maximum - w->ammo) amount = w->maximum - w->ammo;
            if (amount > 0) ((AddAmmoFn)(base + 0x1db85d8))((void *)(uintptr_t)w->weapon, before->inventory, amount);
        }
    } else ((AddItemFn)(base + 0x19e02e4))(type == 5 ? SHIV_SID : KIT_SID, quantity);
}

/* Recheck at application time: client telemetry can precede a weapon switch
 * or ammo pickup. Refusal leaves the receipt unconsumed for a later retry. */
static bool ammo_supply_ready(const Supplies *value) {
    if (!value->weapon || !supported_ammo(value->ammo_sid)
            || value->weapon_count < 1 || value->weapon_count > AP_WEAPONS) return false;
    bool drawn_low = false;
    for (int i = 0; i < value->weapon_count; ++i) {
        const APWeaponSupply *w = &value->weapons[i];
        if (!w->weapon || !supported_ammo(w->ammo_sid) || w->ammo < 0
                || w->maximum < 1 || w->maximum > 11000 || w->ammo > w->maximum) return false;
        if (w->weapon == (uintptr_t)value->weapon && w->ammo_sid == value->ammo_sid
                && w->ammo == value->ammo && w->ammo * 2 <= w->maximum) drawn_low = true;
    }
    return drawn_low;
}

static int ammo_result(const Supplies *before, const Supplies *after) {
    if (before->weapon_count != after->weapon_count) return 3;
    bool applied = false, missed = false;
    for (int i = 0; i < before->weapon_count; ++i) {
        const APWeaponSupply *a = &before->weapons[i], *b = &after->weapons[i];
        if (a->weapon != b->weapon || a->ammo_sid != b->ammo_sid || a->maximum != b->maximum) return 3;
        int amount = (a->maximum + 1) / 2;
        if (amount > a->maximum - a->ammo) amount = a->maximum - a->ammo;
        int delta = b->ammo - a->ammo;
        if (delta == amount) applied |= delta > 0;
        else if (delta == 0) missed |= amount > 0;
        else return 3;
    }
    /* Partial batches are uncertain, never automatically replayed. */
    return applied ? (missed ? 3 : 1) : 2;
}

/* Test seams invoke the real validation/receipt implementation with fake
 * inventory backends; production always uses the fingerprinted functions. */
static bool (*read_supplies)(Supplies *) = supplies;
static int (*read_active_mission)(void) = active_mission;
static uint64_t (*read_active_task)(void) = active_task;
static void (*apply_supply)(int, int, const Supplies *) = add_supply;

#include "test_commands.h"

static void execute_command(void) {
    LONG seq = shared->command_seq;
    if (seq == shared->reply_seq) return;
    int type = shared->command_type, quantity = shared->command_arg & 0xff;
    int expected_mission = ((uint32_t)shared->command_arg >> 8) - 1;
    uint64_t receipt = shared->command_receipt;
    Supplies before, after;
    int result = 2; /* 1 applied, 2 not applied, 3 uncertain, 4 invalid, 5 absent */
    if (type >= 8 && type <= 10) {
        result = execute_test_command(type, quantity, expected_mission, receipt);
        goto done;
    }
    if (type == 3) {
        result = receive_death(expected_mission, receipt);
        goto done;
    }
    if (type == 101) {
        /* Read-only recovery must work even when full, holstered or locked. */
        result = 5;
        if (!receipt || (quantity != 1 && quantity != 2 && quantity != 4 && quantity != 5 && quantity != 6 && quantity != 11 && quantity != 12 && quantity != 13)) result = 4;
        else for (unsigned i = 0; i < receipt_count; ++i) {
            if (receipts[i].id == receipt) {
                result = receipts[i].type == quantity ? receipts[i].result : 4;
                break;
            }
        }
        goto done;
    }
    if (type == 100) {
        shared->current = read_active_mission() + 1;
        if (!read_supplies(&before)) { memset(&before, 0, sizeof(before)); before.kits = before.shivs = -1; }
        publish_supplies(&before);
        supply_stage_ready(shared->current - 1, read_active_task(), &before, GetTickCount64());
        result = 1; goto done;
    }
    if (type == 6) {
        result = quantity == 1 ? receive_airhorn(expected_mission, receipt) : 4;
        goto done;
    }
    if (type == 7) {
        /* An absolute floor is idempotent across reloads and process restarts.
         * Never put it in the consumable receipt cache: a reload may need it again. */
        if (!receipt || quantity < 1 || quantity > 5) { result = 4; goto done; }
        int mission = read_active_mission();
        if (mission <= 1 || mission != expected_mission || !permitted(mission)
                || shared->pending || !read_supplies(&before) || !before.ready
                || before.shiv_max != 3
                || !supply_stage_ready(mission, read_active_task(), &before, GetTickCount64())) goto done;
        int level = read_tool_level();
        if (level < 0 || level > 5) goto done;
        if (level < quantity) apply_tool_floor(quantity);
        int after_level = read_tool_level();
        result = after_level >= quantity && after_level <= 5 ? 1 : 2;
        publish_supplies(&before);
        goto done;
    }
    if ((type != 1 && type != 2 && type != 4 && type != 5 && type != 11 && type != 12 && type != 13) || !receipt || quantity < 1 || quantity > 3
            || ((type == 4 || type == 5 || type >= 11) && quantity != 1)) { result = 4; goto done; }
    for (unsigned i = 0; i < receipt_count; ++i) {
        if (receipts[i].id == receipt) {
            result = receipts[i].type == type ? receipts[i].result : 4;
            goto done;
        }
    }
    if (receipt_count >= sizeof(receipts) / sizeof(receipts[0])) { result = 4; goto done; }
    int mission = read_active_mission();
    shared->current = mission + 1;
    /* Revalidate on the game thread: a queued command may outlive a load,
     * disconnect or transition. Never deliver into Sarah's prologue inventory. */
    if (mission <= 0 || mission != expected_mission || !permitted(mission)
            || shared->pending || !read_supplies(&before) || !before.ready) goto done;
    publish_supplies(&before);
    uint64_t task = read_active_task();
    if (!supply_stage_ready(mission, task, &before, GetTickCount64())) goto done;
    if ((type == 1 || type == 4) && task == DEER_HUNT_TASK) goto done;
    if ((type == 1 && (!before.weapon || !supported_ammo(before.ammo_sid)
                      || before.ammo < 0 || before.ammo > 10000))
            || (type == 2 && (before.kits < 0 || before.kit_max != 3 || before.kits >= before.kit_max || quantity != 1))
            || (type == 5 && (before.shivs < 0 || before.shiv_max != 3 || before.shivs >= before.shiv_max))
            || (type >= 11 && !resource_ready(type, &before))
            || (type == 4 && !ammo_supply_ready(&before))) goto done;
    unsigned index = receipt_count++;
    receipts[index] = (Receipt){receipt, type, 3};
    apply_supply(type, quantity, &before);
    if (!read_supplies(&after) || before.player != after.player || before.inventory != after.inventory
            || (type == 1 && (before.weapon != after.weapon || before.ammo_sid != after.ammo_sid))) result = 3;
    else if (type >= 11 && type <= 13) {
        publish_supplies(&after);
        result = resource_result(type, &before, &after);
        event(5, receipt, 0, type, 0, -1);
    } else if (type == 4) {
        publish_supplies(&after);
        result = ammo_result(&before, &after);
        event(5, receipt, before.weapon_count, type, 0, -1);
    } else {
        publish_supplies(&after);
        int old = type == 1 ? before.ammo : type == 5 ? before.shivs : before.kits;
        int current = type == 1 ? after.ammo : type == 5 ? after.shivs : after.kits;
        int delta = current - old;
        result = delta > 0 && delta <= quantity ? 1 : delta == 0 ? 2 : 3;
        event(5, receipt, ((uint64_t)(uint32_t)old << 32) | (uint32_t)current, type, 0, -1);
    }
    receipts[index].result = result;
    /* Capacity failures have no effect and may be retried after space opens. */
    if (result == 2) --receipt_count;
done:
    shared->reply_status = result;
    InterlockedExchange(&shared->reply_seq, seq);
}

static bool hook_tick(void *scheduler) {
    InterlockedExchange64(&shared->tick, (LONG64)GetTickCount64());
    bool result = original_tick(scheduler);
    if (shared->mode != 2) {
        replay_pending();
        execute_command();
    }
    return result;
}

/* A task starts before its asynchronous load creates the playable scene. The
 * script's get-black-fade native (0x233b3c4) reads this exact float. Holding its
 * clocks while fully black deadlocks that setup; even a non-null player can be
 * a temporary load actor. Wait for both the live player and completed fade.
 * Re-evaluate every frame so checkpoint/menu requests can finish their teardown.
 * No elapsed-time grace period is used. */
static bool scene_ready(void) {
    float fade = 1.0f;
    if (!read_local(base + 0x8220740, &fade, sizeof(fade)) || fade != 0.0f)
        return false;
    void *player = NULL;
    ((PlayerWeaponFn)(base + 0x19e17e8))(&player);
    return player != NULL;
}
static bool (*read_scene_ready)(void) = scene_ready;

/* DeathLink uses the same FSM test as player-already-dead? (0x19c34f0)
 * and the same event construction as kill-player (0x19c0d64). No health,
 * checkpoint, or global pause fields are overwritten. */
typedef struct { uint64_t value; uint32_t type, padding; } ScriptValue;
typedef struct { uintptr_t cell; uint32_t generation; } PlayerIdentity;
static bool same_player(PlayerIdentity a, PlayerIdentity b) {
    return a.cell && a.generation && a.cell == b.cell && a.generation == b.generation;
}
typedef struct { void *player; bool dead, playable; PlayerIdentity identity; } DeathSample;
static bool death_sample(DeathSample *value) {
    memset(value, 0, sizeof(*value));
    ((PlayerWeaponFn)(base + 0x19e17e8))(&value->player);
    if (!value->player) return false;
    /* The compacting heap relocates the object during movement. Its handle
     * cell/generation stays stable until a new player spawns. Recheck that the
     * handle still resolves to this sample before using it. */
    uintptr_t resolved = 0;
    uint32_t generation = 0;
    if (!read_local(base + 0x5ebeae0, &value->identity.cell, 8) ||
        !read_local(base + 0x5ebeae8, &value->identity.generation, 4) ||
        !value->identity.cell || !value->identity.generation ||
        !read_local(value->identity.cell + 8, &resolved, 8) || resolved != (uintptr_t)value->player ||
        !read_local(resolved + 0x98, &generation, 4) || generation != value->identity.generation)
        return false;
    uint64_t dead = 0;
    ((void *(*)(uint64_t *))(base + 0x19c34f0))(&dead);
    value->dead = dead != 0;
    if (value->dead || !read_scene_ready()) return true;
    uintptr_t context = 0, cinematic = 0, movie = 0;
    int32_t paused = 1;
    if (!read_local(base + 0x6426188, &context, 8) || !context) return true;
    for (unsigned i = 0; i < 3; ++i) {
        const unsigned offsets[] = {0xd8, 0x150, 0x2b8};
        if (!read_local(context + offsets[i] + 0x40, &paused, 4) || paused) return true;
    }
    /* cinematic-playing? checks both the scene and movie managers. */
    if (!read_local(base + 0x68ed198, &cinematic, 8) || !cinematic ||
        !read_local(base + 0x3554bb8, &movie, 8) || !movie) return true;
    uint64_t name = 0;
    if (!read_local(cinematic + 0x98, &name, 8)) return true;
    if (((bool (*)(void *, uint64_t, bool))(base + 0x2376db0))((void *)cinematic, name, false))
        return true;
    value->playable = true;
    return true;
}

static void kill_player(void *player) {
    ScriptValue target = {0}, result = {0}, nil = {0};
    ((ScriptValue *(*)(ScriptValue *, void *))(base + 0x3edb7c))(&target, player);
    typedef ScriptValue *(*SendEventFn)(ScriptValue *, const ScriptValue *, uint64_t,
        const ScriptValue *, const ScriptValue *, const ScriptValue *, const ScriptValue *, const ScriptValue *);
    ((SendEventFn)(base + 0x10e3db8))(&result, &nil, UINT64_C(0xcaa82d18f46e4271),
                                   &target, &nil, &nil, &nil, &nil);
}
static bool (*read_death_sample)(DeathSample *) = death_sample;
static bool supply_playable(void *player) {
    DeathSample sample;
    return !engine_in_menu && read_death_sample(&sample) && sample.player == player
        && sample.playable && !sample.dead;
}

/* Fingerprinted tasks.bin routes: only free movement in Sarah's house and
 * Joel's town/alley/woods escape. A task can also contain an in-game scene;
 * death_sample still requires living, stable, unpaused gameplay. Vehicle
 * look-around and crash QTEs do not provide normal character control.
 * Unknown tasks fail closed, including hom-losing-daughter and hom-credits. */
static bool prologue_playable_task(uint64_t task) {
    switch (task) {
    case UINT64_C(0x112a5f80e30b214e): /* hom-house-daughter-room-phone */
    case UINT64_C(0xe69b45db45575c87): /* hom-house-daughter-room */
    case UINT64_C(0x93fdeb3dbc369f95): /* hom-house-joel-room */
    case UINT64_C(0x996a06a412c8b107): /* hom-house-downstairs */
    case UINT64_C(0xd80268ae227551c6): /* hom-house-study */
    case UINT64_C(0xf255ed0f3772df2f): /* hom-town-run-start */
    case UINT64_C(0x08eb2b7c833d81bb): /* hom-town-gas-station */
    case UINT64_C(0x382c63ebbd8006cb): /* hom-town-shops-start */
    case UINT64_C(0xd1a5df5d6d36cbae): /* hom-town-shops-end */
    case UINT64_C(0x83ef7aa79d76692a): /* hom-town-cinema */
    case UINT64_C(0x64b4842e9e21d1cf): /* hom-alley-clear */
    case UINT64_C(0x4ad08ce8818fed2e): /* hom-alley-start */
    case UINT64_C(0x4ff33c7bc60b30a8): /* hom-alley-bar-enter */
    case UINT64_C(0x1f7f35c41da66c64): /* hom-alley-bar-split-up */
    case UINT64_C(0x06bd1a40d00f58d8): /* hom-alley-parking-lot */
    case UINT64_C(0x63a5e41f4b84ad43): /* hom-woods-chase */
        return true;
    default: return false;
    }
}
static uint64_t prologue_start_task;
static bool effects_task_allowed(int mission, uint64_t task) {
    if (mission < 0 || mission > 28) return false;
    if (mission != 0) return !prologue_start_task;
    return prologue_playable_task(task) && (!prologue_start_task || prologue_start_task == task);
}

/* A horn is an AI hearing event, not a weapon shot or an awareness-field write.
 * The script audio-gameplay-event wrapper uses these exact position/handle
 * helpers. The separate client sound is original audio, not an extracted asset.
 * Return 1 only when our exact event occupies the expected queue slot. */
#define HORN_SID UINT64_C(0xc13f19d23ac210fb)
static int emit_horn(void *player) {
    _Alignas(16) float position[4] = {0};
    _Alignas(16) unsigned char handle[16] = {0};
    uintptr_t queue = base + 0x5bf8560, entries = 0;
    int32_t tail = -1, count = -1, capacity = 0;
    if (!read_local(queue + 0x24, &tail, 4) || !read_local(queue + 0x28, &count, 4) ||
            !read_local(queue + 0x30, &entries, 8) || !read_local(queue + 0x38, &capacity, 4) ||
            !entries || capacity < 1 || capacity > 4096 || tail < 0 || tail >= capacity ||
            count < 0 || count >= capacity) return 2;
    ((void *(*)(void *, void *))(base + 0x1f0a5fc))((unsigned char *)player + 0x180, position);
    for (unsigned i = 0; i < 3; ++i)
        if (!isfinite(position[i]) || fabsf(position[i]) > 1000000.0f) return 2;
    ((void *(*)(void *, void *))(base + 0x3f05c0))(handle, player);
    if (!memcmp(handle, (unsigned char[16]){0}, 12)) return 2;
    ((void (*)(uint64_t, const float *, const void *, float, void *))(base + 0x15b13d8))
        (HORN_SID, position, handle, 1.0f, NULL);
    unsigned char record[0x60];
    uint64_t sid = 0;
    int32_t next = -1;
    if (!read_local(queue + 0x24, &next, 4) ||
            !read_local(entries + (uintptr_t)tail * 0x60, record, sizeof(record))) return 3;
    memcpy(&sid, record + 0x48, 8);
    if (next == (tail + 1) % capacity && sid == HORN_SID &&
            !memcmp(record, position, 16) && !memcmp(record + 0x20, handle, 12)) return 1;
    return next == tail ? 2 : 3;
}
static int (*apply_horn)(void *) = emit_horn;
static struct { PlayerIdentity identity; uint64_t last, since; int mission; bool ready; } horn_clock;
static void update_airhorn(void) {
    uint64_t now = GetTickCount64();
    DeathSample sample;
    int mission = read_active_mission();
    uint64_t task = read_active_task();
    bool task_allowed = effects_task_allowed(mission, task);
    shared->prologue_stage = mission == 0 ? (task_allowed ? 1 : 2) : 0;
    bool ready = shared->mode == 2 && shared->death_state != 1 && shared->death_state != 3 &&
        !engine_in_menu && task_allowed &&
        GetTickCount64() - (uint64_t)shared->heartbeat <= 5000 && permitted(mission) &&
        !shared->pending && read_death_sample(&sample) && sample.playable && !sample.dead;
    if (!ready || !same_player(horn_clock.identity, sample.identity) || horn_clock.mission != mission) {
        horn_clock.since = now;
        horn_clock.ready = false;
    }
    if (ready) {
        bool stable = now - horn_clock.since >= 1000;
        uint64_t elapsed = now - horn_clock.last;
        if (stable && horn_clock.ready && elapsed <= 250)
            InterlockedExchangeAdd64(&shared->airhorn_clock_ms, (LONG64)elapsed);
        update_timed_effects(elapsed, stable && horn_clock.ready && elapsed <= 250);
        horn_clock.identity = sample.identity;
        horn_clock.mission = mission;
        horn_clock.ready = stable;
    }
    horn_clock.last = now;
    shared->airhorn_ready = horn_clock.ready;
}
/* Leased transient effects: no persistent game setting is overwritten.
 * Independent clocks allow two different traps to overlap, while same-kind
 * receipts stack in the client's durable journal. */
static bool effect_enabled(int index) {
    uint64_t now = GetTickCount64();
    return shared && index >= 0 && index < 2 && shared->mode == 2 &&
        (shared->effect_supported & shared->effect_mask & (1 << index)) &&
        shared->airhorn_ready && !engine_in_menu && !shared->pending &&
        now >= (uint64_t)shared->effect_lease && now - (uint64_t)shared->effect_lease <= 1500 &&
        now - (uint64_t)shared->heartbeat <= 5000 && permitted(read_active_mission()) &&
        shared->effect_clock[index] < shared->effect_until[index];
}
static void update_timed_effects(uint64_t elapsed, bool ready) {
    if (!ready) return;
    for (int i = 0; i < 2; ++i) if (effect_enabled(i)) {
        LONG64 remaining = shared->effect_until[i] - shared->effect_clock[i];
        InterlockedExchangeAdd64(&shared->effect_clock[i], (LONG64)elapsed < remaining ? (LONG64)elapsed : remaining);
    }
}
static float *(*original_aim_offset)(void *, float *) __attribute__((used));
/* Scope state belongs to the local weapon/aim controller. Its virtual getter
 * at +0x138 reads +0x698; camera sway is obtained separately at +0x158. */
static bool scoped_controller(uintptr_t player, uintptr_t *controller) {
    uintptr_t owner = 0; unsigned char zoomed = 0;
    return read_local(player + 0x3098, controller, 8) && *controller &&
        read_local(*controller + 8, &owner, 8) && owner == player &&
        read_local(*controller + 0x698, &zoomed, 1) && zoomed == 1;
}
static void shaky_wave(float *x, float *y) {
    float t = (float)(shared->effect_clock[0] % 60000) / 1000.0f * 1.25f;
    *x = 54.0f * sinf(t * 5.1f) + 21.0f * sinf(t * 9.3f);
    *y = 36.0f * sinf(t * 6.7f) + 15.0f * cosf(t * 11.1f);
}
static void __attribute__((used, noinline)) apply_aim_offset(void *reticle, float *out) {
    if (effect_enabled(0) && out && isfinite(out[0]) && isfinite(out[1])) {
        DeathSample sample;
        uintptr_t owner = 0, current = 0, controller = 0;
        if (read_death_sample(&sample) && sample.playable && !sample.dead &&
                read_local((uintptr_t)reticle, &owner, 8) && owner == (uintptr_t)sample.player &&
                read_local(owner + 0x3380, &current, 8) && current == (uintptr_t)reticle &&
                !scoped_controller(owner, &controller)) {
            /* The game uses a 1920x1080 reference plane for these offsets.
             * Stronger tuning after live feedback: triple the displacement
             * and run the mixed oscillations 25% faster. Duration is unchanged. */
            float x, y; shaky_wave(&x, &y); out[0] += x; out[1] += y;
        }
    }
}
static float *(*original_scope_sway)(void *, float *, void *) __attribute__((used));
static void __attribute__((used, noinline)) apply_scope_sway(void *aim, float *out) {
    if (!effect_enabled(0) || !out || !isfinite(out[0]) || !isfinite(out[1])) return;
    DeathSample sample; uintptr_t controller = 0;
    if (read_death_sample(&sample) && sample.playable && !sample.dead &&
            scoped_controller((uintptr_t)sample.player, &controller) && controller == (uintptr_t)aim) {
        /* This getter feeds native camera rotation in degrees, rather than
         * the unscoped 1920x1080 reticle plane. Never mutate saved sway state. */
        float x, y; shaky_wave(&x, &y); out[0] += x / 30.0f; out[1] += y / 30.0f;
    }
}
__attribute__((naked)) static float *hook_scope_sway(void *aim, float *out, void *key) {
    __asm__ volatile(
        "sub $200, %rsp\n" "mov %rcx, 192(%rsp)\n"
        "call *original_scope_sway(%rip)\n"
        "mov %rax, 32(%rsp)\n" "mov %rcx, 40(%rsp)\n" "mov %rdx, 48(%rsp)\n"
        "mov %r8, 56(%rsp)\n" "mov %r9, 64(%rsp)\n"
        "mov %r10, 72(%rsp)\n" "mov %r11, 80(%rsp)\n"
        "pushfq\n" "pop %rax\n" "mov %rax, 88(%rsp)\n"
        "movdqu %xmm0, 96(%rsp)\n" "movdqu %xmm1, 112(%rsp)\n"
        "movdqu %xmm2, 128(%rsp)\n" "movdqu %xmm3, 144(%rsp)\n"
        "movdqu %xmm4, 160(%rsp)\n" "movdqu %xmm5, 176(%rsp)\n"
        "mov 192(%rsp), %rcx\n" "mov 32(%rsp), %rdx\n" "call apply_scope_sway\n"
        "movdqu 96(%rsp), %xmm0\n" "movdqu 112(%rsp), %xmm1\n"
        "movdqu 128(%rsp), %xmm2\n" "movdqu 144(%rsp), %xmm3\n"
        "movdqu 160(%rsp), %xmm4\n" "movdqu 176(%rsp), %xmm5\n"
        "mov 40(%rsp), %rcx\n" "mov 48(%rsp), %rdx\n"
        "mov 56(%rsp), %r8\n" "mov 64(%rsp), %r9\n"
        "mov 72(%rsp), %r10\n" "mov 80(%rsp), %r11\n"
        "mov 88(%rsp), %rax\n" "push %rax\n" "popfq\n"
        "mov 32(%rsp), %rax\n" "lea 200(%rsp), %rsp\n" "ret\n");
}
/* The game's leaf callers retain volatile registers (notably R8) across this
 * function using whole-program knowledge. Preserve the original function's
 * complete volatile result state around our C helper, including flags/XMMs.
 * A normal C detour violates that private ABI even with the effect disabled. */
__attribute__((naked)) static float *hook_aim_offset(void *reticle, float *out) {
    __asm__ volatile(
        "sub $200, %rsp\n"
        "call *original_aim_offset(%rip)\n"
        "mov %rax, 32(%rsp)\n" "mov %rcx, 40(%rsp)\n" "mov %rdx, 48(%rsp)\n"
        "mov %r8, 56(%rsp)\n" "mov %r9, 64(%rsp)\n"
        "mov %r10, 72(%rsp)\n" "mov %r11, 80(%rsp)\n"
        "pushfq\n" "pop %rax\n" "mov %rax, 88(%rsp)\n"
        "movdqu %xmm0, 96(%rsp)\n" "movdqu %xmm1, 112(%rsp)\n"
        "movdqu %xmm2, 128(%rsp)\n" "movdqu %xmm3, 144(%rsp)\n"
        "movdqu %xmm4, 160(%rsp)\n" "movdqu %xmm5, 176(%rsp)\n"
        "call apply_aim_offset\n"
        "movdqu 96(%rsp), %xmm0\n" "movdqu 112(%rsp), %xmm1\n"
        "movdqu 128(%rsp), %xmm2\n" "movdqu 144(%rsp), %xmm3\n"
        "movdqu 160(%rsp), %xmm4\n" "movdqu 176(%rsp), %xmm5\n"
        "mov 40(%rsp), %rcx\n" "mov 48(%rsp), %rdx\n"
        "mov 56(%rsp), %r8\n" "mov 64(%rsp), %r9\n"
        "mov 72(%rsp), %r10\n" "mov 80(%rsp), %r11\n"
        "mov 88(%rsp), %rax\n" "push %rax\n" "popfq\n"
        "mov 32(%rsp), %rax\n" "lea 200(%rsp), %rsp\n" "ret\n");
}
/* PlayerFlashlight updates this light's render parameters each frame. Alter
 * only the arguments from its identified callsite; never toggle the player's
 * flashlight or overwrite the controller's saved intensity/settings. The next
 * ordinary update restores its normal parameters when the lease ends. */
static void (*original_flashlight_settings)(void *, uintptr_t, float, float, float, bool);
static float flashlight_factor(uint64_t clock) {
    static const float levels[] = {1.0f, .12f, .65f, .08f, .4f, 1.0f};
    unsigned phase = (unsigned)((clock / 800) % 6);
    float blend = (float)(clock % 800) / 800.0f;
    blend = blend * blend * (3.0f - 2.0f * blend);
    return levels[phase] + (levels[(phase + 1) % 6] - levels[phase]) * blend;
}
static void hook_flashlight_settings(void *model, uintptr_t unused, float intensity,
                                     float radius, float particle, bool flag) {
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    DeathSample sample;
    if (caller == base + 0x18c52df && effect_enabled(1) && isfinite(intensity) && isfinite(particle)
            && read_death_sample(&sample) && sample.playable && !sample.dead) {
        float factor = flashlight_factor((uint64_t)shared->effect_clock[1]);
        intensity *= factor;
        particle *= factor;
    }
    original_flashlight_settings(model, unused, intensity, radius, particle, flag);
}
static int receive_airhorn(int expected_mission, uint64_t receipt) {
    if (!receipt) return 4;
    for (unsigned i = 0; i < receipt_count; ++i)
        if (receipts[i].id == receipt) return receipts[i].type == 6 ? receipts[i].result : 4;
    update_airhorn();
    if (!shared->airhorn_ready || read_active_mission() != expected_mission) return 2;
    if (receipt_count >= sizeof(receipts) / sizeof(receipts[0])) return 4;
    DeathSample sample;
    if (!read_death_sample(&sample) || !same_player(sample.identity, horn_clock.identity) || !sample.playable || sample.dead)
        return 2;
    unsigned index = receipt_count++;
    receipts[index] = (Receipt){receipt, 6, 3};
    int result = apply_horn(sample.player);
    receipts[index].result = result;
    if (result == 2) --receipt_count;
    else event(11, receipt, HORN_SID, result, 0, expected_mission);
    return result;
}
static void (*apply_death)(void *) = kill_player;
static struct {
    void *player;
    PlayerIdentity identity;
    uint64_t since, remote_since, receipt, last_playable;
    bool armed, was_dead, remote, script_failed;
} death;

static void clear_death_tracking(void) {
    /* A transition after dispatch cannot silently consume the saved receipt.
     * Report uncertainty, never turn a story death into a confirmation/echo. */
    if (death.remote) event(10, death.receipt, 0, 0, 0, read_active_mission());
    memset(&death, 0, sizeof(death));
    shared->death_state = 0;
}

/* Observed fatal broken-glass QTE in Alone and Forsaken. */
#define PITTSBURGH_QTE_TASK UINT64_C(0x37658dd04095846a)
/* Captured Ellie death after the opening Pittsburgh ambush. */
#define PITTSBURGH_ELLIE_TASK UINT64_C(0x93f48466a5692ad5)
/* Observed hunter drowning struggle in Hotel Lobby. */
#define HOTEL_DROWNING_TASK UINT64_C(0xa78b83f44520de9e)
/* Captured fatal sniper knife struggle in The Suburbs. */
#define SUBURBS_SNIPER_TASK UINT64_C(0x294e65cdd312af38)
/* Captured team-death failure while covering allies with the sniper rifle. */
#define SUBURBS_TEAM_TASK UINT64_C(0xef3d134138308c13)
/* Captured fatal hunter grab during the opening Cabin Resort escape. */
#define CABIN_HUNTER_TASK UINT64_C(0x287c4dfeee8373a7)
/* Captured fatal two-hunter stabbing struggle after switching to Joel. */
#define CABIN_JOEL_TASK UINT64_C(0xd29720961b0dd730)
/* Captured fatal David strangling QTE in the burning restaurant. */
#define CABIN_DAVID_TASK UINT64_C(0xa1b5df858fcc16bb)
/* Captured fatal water fall in Bus Depot Underground Tunnel. */
#define BUS_WATER_TASK UINT64_C(0x42526a220348d020)
/* Captured fatal soldier gunfire while carrying Ellie out of Firefly Lab. */
#define FIREFLY_ESCAPE_TASK UINT64_C(0x1c9a2ef9f564b7ef)
/* Captured Ellie-grab/Joel-shot failures elsewhere along the escape route. */
#define FIREFLY_CAPTURE_TASK UINT64_C(0x89a12fd5192d1361)

static void effects_task_started(uint64_t sid, int mission) {
    bool qte_restart = (mission == 13 && (sid == PITTSBURGH_QTE_TASK || sid == PITTSBURGH_ELLIE_TASK)) ||
                       (mission == 14 && sid == HOTEL_DROWNING_TASK) ||
                       (mission == 18 && (sid == SUBURBS_SNIPER_TASK || sid == SUBURBS_TEAM_TASK)) ||
                       (mission == 24 && (sid == CABIN_HUNTER_TASK || sid == CABIN_JOEL_TASK || sid == CABIN_DAVID_TASK)) ||
                       (mission == 26 && sid == BUS_WATER_TASK) ||
                       (mission == 27 && (sid == FIREFLY_ESCAPE_TASK || sid == FIREFLY_CAPTURE_TASK));
    if (mission != 0 && !prologue_start_task && !qte_restart) return;
    if (mission < 0 && sid != UINT64_C(0xa823deeb3a672718)) return;
    /* Start hooks run before the task performs its scripted work, even when
     * the active-task pointer still names hom-woods-chase for this frame. */
    clear_death_tracking();
    memset(&horn_clock, 0, sizeof(horn_clock));
    shared->airhorn_ready = 0;
    prologue_start_task = mission == 0 ? sid : 0;
    shared->prologue_stage = mission == 0 ? (prologue_playable_task(sid) ? 1 : 2) : 0;
}

/* Local death cleanup is independent of opting into network DeathLink. */
static bool death_monitor_enabled(void) {
    return shared->mode == 2 && GetTickCount64() - (uint64_t)shared->heartbeat <= 5000;
}
static bool death_enabled(void) {
    return shared->death_enabled > 0 && death_monitor_enabled();
}

static void record_player_death(const DeathSample *sample, int mission) {
    if (!death.was_dead && death.armed) {
        /* Persisted client trap cancellation is acknowledged separately from
         * network DeathLink. Duplicate FSM/script reports share this latch. */
        event(AP_EVENT_PLAYER_DEATH, 0, (uintptr_t)sample->player, death.remote ? 1 : 0, 0, mission);
        shared->effect_mask = 0;
        shared->effect_lease = 0;
        shared->airhorn_ready = 0;
        memset(&horn_clock, 0, sizeof(horn_clock));
        if (death_enabled()) {
            if (death.remote) InterlockedIncrement(&shared->death_remote);
            else InterlockedIncrement(&shared->death_local);
            event(9, death.remote ? death.receipt : 0, (uintptr_t)sample->player,
                  death.remote ? 1 : 0, 0, mission);
        }
    }
    death.was_dead = true;
    death.armed = death.remote = false;
    death.since = 0;
    shared->death_state = 1;
}

/* Joel's prologue bites and the Pittsburgh opening QTE can bypass the Death
 * FSM. The latter was captured armed in task 0x37658dd04095846a. task-fail! sends this
 * explicit failure instead. Hotel drowning uses task-fail-if-active!.
 * Match each observed task and fingerprinted callsite, not arbitrary
 * "fail" events or checkpoint reloads. Scripted finale tasks remain excluded
 * even while the active-task pointer still names the preceding woods chase. */
static void observe_script_failure(uint64_t sid, uintptr_t caller) {
    if (sid != UINT64_C(0xef0166791679f92d)) return;
    DeathSample sample;
    int mission = read_active_mission();
    uint64_t task = read_active_task();
    bool supported_failure =
        (caller == base + 0x235c9ae && (mission == 0 || (mission == 13 && (task == PITTSBURGH_QTE_TASK || task == PITTSBURGH_ELLIE_TASK)) ||
         (mission == 18 && (task == SUBURBS_SNIPER_TASK || task == SUBURBS_TEAM_TASK)) ||
         (mission == 24 && (task == CABIN_HUNTER_TASK || task == CABIN_JOEL_TASK || task == CABIN_DAVID_TASK)) ||
         (mission == 26 && task == BUS_WATER_TASK) ||
         (mission == 27 && (task == FIREFLY_ESCAPE_TASK || task == FIREFLY_CAPTURE_TASK)))) ||
        (caller == base + 0x235cb34 && mission == 14 && task == HOTEL_DROWNING_TASK);
    if (!supported_failure || !death_monitor_enabled() || engine_in_menu || shared->pending ||
        !permitted(mission) || !effects_task_allowed(mission, read_active_task()) ||
        !death.armed || death.was_dead || !read_death_sample(&sample) ||
        !same_player(death.identity, sample.identity)) return;
    record_player_death(&sample, mission);
    /* The animation returns to Move before checkpoint teardown. Do not rearm
     * that same actor or accept another incoming death in the interim. */
    death.script_failed = true;
}

typedef void *(*SendEventFn)(void *, const void *, uint64_t, const void *,
                            const void *, const void *, const void *, const void *);
static SendEventFn original_send_event;
static void *hook_send_event(void *result, const void *sender, uint64_t sid, const void *target,
                             const void *a, const void *b, const void *c, const void *d) {
    observe_script_failure(sid, (uintptr_t)__builtin_return_address(0));
    return original_send_event(result, sender, sid, target, a, b, c, d);
}

static void update_death_link(void) {
    DeathSample sample;
    int mission = read_active_mission();
    uint64_t now = GetTickCount64();
    shared->death_state = 0;
    if (!death_monitor_enabled() || engine_in_menu || !effects_task_allowed(mission, read_active_task()) ||
            !read_death_sample(&sample)) {
        clear_death_tracking();
        return;
    }
    if (!same_player(death.identity, sample.identity)) {
        clear_death_tracking();
        death.identity = sample.identity;
    }
    death.player = sample.player;
    if (death.script_failed) { shared->death_state = 1; return; }
    /* The sniper's fatal animation removes control shortly before task-fail!.
     * Keep a previously armed detector for at most two seconds in this exact
     * task. Menus, transitions, identity changes and disconnect still clear it. */
    bool sniper = mission == 18 && read_active_task() == SUBURBS_SNIPER_TASK;
    if (sniper && !sample.playable && now - death.last_playable > 2000)
        death.armed = false;
    if (sample.dead) {
        record_player_death(&sample, mission);
        return;
    }
    if (death.remote) {
        shared->death_state = 3;
        /* A rejected die event must never be retried or echo as a local death. */
        if (now - death.remote_since >= 5000) {
            event(10, death.receipt, 0, 0, 0, mission);
            death.remote = death.armed = false;
            death.since = 0;
        }
        return;
    }
    if (!sample.playable || !permitted(mission) || shared->pending) {
        if (sniper && !sample.playable && permitted(mission) && !shared->pending &&
                death.armed && now - death.last_playable <= 2000) return;
        death.armed = false;
        death.since = 0;
        return;
    }
    death.last_playable = now;
    if (!death.since) death.since = now;
    if (now - death.since >= 1000) {
        death.armed = true;
        death.was_dead = false;
        shared->death_state = 2;
    }
}

static int receive_death(int expected_mission, uint64_t receipt) {
    if (!receipt) return 4;
    update_death_link();
    if ((uint32_t)(receipt >> 32) != (uint32_t)shared->death_enabled) return 2;
    if (death.receipt == receipt) return 1;
    if (!death_enabled() || shared->death_state != 2 ||
            read_active_mission() != expected_mission) return 2;
    DeathSample sample;
    if (!read_death_sample(&sample) || sample.dead || !sample.playable ||
            !same_player(sample.identity, death.identity)) return 2;
    death.remote = true;
    death.receipt = receipt;
    death.remote_since = GetTickCount64();
    shared->death_state = 3;
    apply_death(sample.player);
    return 1; /* Submitted once; death_remote confirms the actual death. */
}

/* This frame callback stays active while gameplay clocks are stopped. It only
 * publishes policy and services the mailbox; the original global pause state
 * remains untouched so menu input keeps running. */
static bool hook_pause_update(void *prog) {
    uintptr_t expected = 0;
    if (!read_local(base + 0x3644c88, &expected, sizeof(expected)) || expected != (uintptr_t)prog)
        return original_pause_update(prog);
    InterlockedExchange64(&shared->tick, (LONG64)GetTickCount64());
    int blocked = -1;
    if (shared->mode == 2) {
        int active = engine_in_menu ? -1 : read_active_mission();
        if (active >= 0) engine_mission = active;
        if (!engine_in_menu && engine_mission >= 0 && !permitted(engine_mission)
                && read_scene_ready())
            blocked = engine_mission;
    }
    bool result = original_pause_update(prog);
    if (shared->mode == 2 || engine_blocked >= 0) {
        if (blocked != engine_blocked) {
            if (engine_blocked >= 0) event(4, 0, 0, ENGINE_GATE_FLAG, 0, engine_blocked);
            if (blocked >= 0) event(3, 0, 0, ENGINE_GATE_FLAG, 0, blocked);
        }
        engine_blocked = blocked;
        shared->blocked = blocked + 1;
        shared->pending = blocked >= 0;
    }
    if (shared->mode == 2) {
        update_death_link();
        update_airhorn();
        execute_command();
    }
    return result;
}

/* The global Prog pause freezes UI input too. Use the same three clocks as the
 * ordinary pause menu (indices 1, 2 and 5). The leaf clock update only reads its
 * pause counter and calls no callbacks. A temporary reference produces a zero
 * delta without changing other pause owners or leaving a lease across reloads.
 * Menu and real-time clocks retain their normal updates. */
static void hook_clock_update(void *clock, float delta) {
    uintptr_t context = 0;
    if (shared->mode == 2 && engine_blocked >= 0 &&
            read_local(base + 0x6426188, &context, sizeof(context)) && context) {
        uintptr_t address = (uintptr_t)clock;
        if (address == context + 0xd8 || address == context + 0x150 ||
                address == context + 0x2b8) {
            int32_t *count = (int32_t *)((unsigned char *)clock + 0x40);
            int32_t previous = *count;
            if (!previous) *count = 1;
            original_clock_update(clock, delta);
            *count = previous;
            return;
        }
    }
    original_clock_update(clock, delta);
}

static void hook_play(void *node, uint64_t continuation, int state, const int64_t *time,
                      bool arg5, bool arg6) {
    reset_supply_stage();
    uint64_t sid = 0;
    read_local((uintptr_t)node + 0x28, &sid, sizeof(sid));
    int mission = mission_for(sid);
    if (shared->mode == 2) {
        engine_start(sid, mission);
        int previous = admitted_mission;
        admitted_mission = mission;
        original_play(node, continuation, state, time, arg5, arg6);
        admitted_mission = previous;
        if (mission >= 0) shared->current = mission + 1;
        event(1, sid, continuation, (uint32_t)state, (uintptr_t)__builtin_return_address(0), mission);
        return;
    }
    if (sid == UINT64_C(0xa823deeb3a672718)) {
        AcquireSRWLockExclusive(&pending_lock);
        pending_count = 0; shared->pending = 0; shared->blocked = 0;
        ReleaseSRWLockExclusive(&pending_lock);
    }
    if (!(mission >= 0 && admitted_mission == mission) && !permitted(mission)) {
        PendingPlay request = {.sid = sid, .continuation = continuation, .state = state,
                               .mission = mission, .has_time = time != NULL, .arg5 = arg5, .arg6 = arg6};
        if (time && !read_local((uintptr_t)time, &request.time, 8)) {
            shared->error = 403; return;
        }
        defer_play(request, (uintptr_t)__builtin_return_address(0));
        return;
    }
    if (consume_pending(sid, START_PLAY)) event(4, sid, continuation, (uint32_t)state, 0, mission);
    event(1, sid, continuation, (uint32_t)state | ((uint32_t)arg5 << 16) | ((uint32_t)arg6 << 17),
          (uintptr_t)__builtin_return_address(0), mission);
    int previous = admitted_mission;
    admitted_mission = mission;
    original_play(node, continuation, state, time, arg5, arg6);
    admitted_mission = previous;
    if (mission >= 0) InterlockedExchange(&shared->current, mission + 1);
}

static void hook_pickup(void *manager, uint64_t sid, bool arg3, bool arg4) {
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    original_pickup(manager, sid, arg3, arg4);
    event(2, sid, 0, (uint32_t)arg3 | ((uint32_t)arg4 << 1), caller, -1);
}

static void hook_profile_treasure(void *manager, uint64_t sid, bool award) {
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    original_profile_treasure(manager, sid, award);
    /* give-profile-treasure (0x132f5b8) bypasses inventory insertion. This
     * covers inspection awards as well as nested ordinary pickup awards.
     * Save restoration has award=false; the host ignores those events. */
    event(7, sid, 0, award ? 1 : 0, caller, shared->current - 1);
}

static void hook_complete(void *node, int kind) {
    uint64_t sid = 0;
    uint16_t before = 0, after = 0;
    int16_t difficulty = -1;
    read_local((uintptr_t)node + 0x28, &sid, 8);
    read_local((uintptr_t)node + 0x64, &before, 2);
    original_complete(node, kind);
    read_local((uintptr_t)node + 0x64, &after, 2);
    read_local((uintptr_t)node + 0x6a, &difficulty, 2);
    if (!(before & 8) && (after & 8) && (kind == 1 || kind == 2) && difficulty >= 0)
        event(6, sid, difficulty, kind, (uintptr_t)__builtin_return_address(0), mission_for(sid));
}

static bool verify_anchors(void) {
    for (unsigned i = 0; i < sizeof(ap_anchors) / sizeof(ap_anchors[0]); ++i) {
        unsigned char actual[32];
        const APAnchor *a = &ap_anchors[i];
        if (!read_local(base + a->rva, actual, a->size) || memcmp(actual, a->data, a->size)) return false;
    }
    return true;
}

static DWORD WINAPI worker(void *unused) {
    (void)unused;
    if (InterlockedCompareExchange(&running, 1, 0)) return 6;
    wchar_t name[80];
    swprintf(name, 80, L"Local\\TLOUAP_v2_%lu", GetCurrentProcessId());
    HANDLE mapping = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, name);
    if (!mapping) return 1;
    shared = (APShared *)MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(APShared));
    if (!shared || shared->magic != AP_MAGIC || shared->version != AP_VERSION
            || shared->size != sizeof(APShared) || shared->build_id != AP_BUILD_ID) return 2;
    base = (uintptr_t)GetModuleHandleW(NULL);
    automatic_ready = (ReadyFn)(base + 0x62b680);
    shared->image_base = base;
    if (!verify_anchors()) { shared->error = 100; shared->status = -1; return 3; }
    MH_STATUS result = MH_Initialize();
    if (result == MH_ERROR_ALREADY_INITIALIZED) {
        result = MH_EnableHook(MH_ALL_HOOKS);
        if (result != MH_OK) goto failed;
        goto enabled;
    }
    if (result != MH_OK) { shared->error = 200 + result; shared->status = -1; return 4; }
    void *targets[] = {(void *)(base + 0x5ebea0), (void *)(base + 0x62aa10),
                      (void *)(base + 0x13664ec), (void *)(base + 0x62b1a0),
                      (void *)(base + 0x62b6d0), (void *)(base + 0x1366884),
                      (void *)(base + 0x626e80), (void *)(base + 0x431ab0),
                      (void *)(base + 0x20050ac), (void *)(base + 0x10e3db8), (void *)(base + 0x199bab4), (void *)(base + 0x17e9f5c), (void *)(base + 0x18178c8)};
    void *hooks[] = {(void *)hook_tick, (void *)hook_play, (void *)hook_pickup,
                    (void *)hook_complete, (void *)hook_begin, (void *)hook_profile_treasure,
                    (void *)hook_automatic, (void *)hook_pause_update, (void *)hook_clock_update,
                    (void *)hook_send_event, (void *)hook_aim_offset, (void *)hook_flashlight_settings, (void *)hook_scope_sway};
    void **originals[] = {(void **)&original_tick, (void **)&original_play,
                         (void **)&original_pickup, (void **)&original_complete,
                         (void **)&original_begin, (void **)&original_profile_treasure,
                         (void **)&original_automatic, (void **)&original_pause_update,
                         (void **)&original_clock_update, (void **)&original_send_event, (void **)&original_aim_offset, (void **)&original_flashlight_settings, (void **)&original_scope_sway};
    for (unsigned i = 0; i < sizeof(targets) / sizeof(targets[0]); ++i) {
        result = MH_CreateHook(targets[i], hooks[i], originals[i]);
        if (result != MH_OK) goto failed;
        result = MH_QueueEnableHook(targets[i]);
        if (result != MH_OK) goto failed;
    }
    result = MH_ApplyQueued();
    if (result != MH_OK) goto failed;
enabled:
    shared->effect_supported = 3;
    InterlockedExchange(&shared->status, 1);
    while (!shared->detach) Sleep(100);
    InterlockedExchange(&shared->mode, 0);
    for (unsigned i = 0; shared->pending && i < 50; ++i) Sleep(100);
    if (shared->pending) { shared->error = 404; return 7; }
    result = MH_DisableHook(MH_ALL_HOOKS);
    if (result != MH_OK) goto failed;
    InterlockedExchange(&shared->status, 3);
    InterlockedExchange(&running, 0);
    /* Keep DLL, mapping and trampolines alive until game exit. A thread could
       already be returning through our wrapper when the hook is disabled. */
    return 0;
failed:
    MH_DisableHook(MH_ALL_HOOKS);
    shared->error = 300 + result;
    InterlockedExchange(&shared->status, -1);
    return 5;
}

__declspec(dllexport) DWORD WINAPI APStart(void *unused) { return worker(unused); }

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(instance);
        HANDLE thread = CreateThread(NULL, 0, worker, NULL, 0, NULL);
        if (thread) CloseHandle(thread);
    }
    return TRUE;
}
