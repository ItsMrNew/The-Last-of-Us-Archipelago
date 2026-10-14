/* Exercise the actual bridge's admission/defer/replay code in an isolated
 * process. The fake task cache and callbacks never touch the running game. */
#include <assert.h>
#include <stdlib.h>
#include "../native/bridge.c"

#define TEST_SID UINT64_C(0x1234567812345678)
static unsigned char test_node[0x130];
static int begins, plays;
static bool revoke_during_begin;
static int64_t observed_time;
static uint64_t observed_continuation;
static Supplies test_inventory;
static int supply_effects, ammo_capacity, test_mission;
static bool change_character, partial_ammo;
static uint64_t test_task;
static int automatic_starts;
static bool graph_ready, automatic_during_play;
static unsigned char test_prog[0x100];
static int pause_updates;
static bool test_scene_ready;
static DeathSample test_death;
static int death_effects;
static int horn_effects, horn_result;
static unsigned char tool_manager[0x1000];
static int tool_grants;
static void fake_tool_pickup(void *manager, uint64_t sid, bool award, bool inspect) {
    assert(manager == tool_manager && !award && !inspect);
    uint32_t *count = (uint32_t *)(tool_manager + 0xc50);
    ((uint64_t *)tool_manager)[(*count)++] = sid;
    ++tool_grants;
}
static int fake_horn(void *player) { assert(player == test_death.player); ++horn_effects; return horn_result; }
static bool fake_death_sample(DeathSample *out) {
    *out = test_death;
    if (!out->identity.cell) out->identity = (PlayerIdentity){(uintptr_t)out->player, 1};
    return out->player != NULL;
}
static void fake_death(void *player) { assert(player == test_death.player); ++death_effects; }
static bool fake_scene_ready(void) { return test_scene_ready; }
static unsigned char test_context[0x600];
static void fake_clock_update(void *clock, float delta) {
    unsigned char *p = clock;
    *(float *)(p + 0x20) = *(int32_t *)(p + 0x40) ? 0 : delta;
}
static void engine_frame(void) {
    hook_pause_update(test_prog);
    for (int i = 0; i < 10; ++i)
        hook_clock_update(test_context + 0x60 + i * 0x78, 0.016f);
}

static bool fake_pause_update(void *ptr) {
    unsigned char *p = ptr;
    bool previous = p[0x63];
    p[0x60] = p[0x63];
    p[0x63] = p[0x62];
    p[0x62] = p[0x61] && !p[0x64];
    ++pause_updates;
    return previous != p[0x63];
}

static bool fake_ready(void *node) {
    return graph_ready && *(uint32_t *)((unsigned char *)node + 0x60) == 0;
}
static void fake_automatic(void *node) {
    ++automatic_starts;
    *(uint32_t *)((unsigned char *)node + 0x60) = 2;
}

static bool fake_supplies(Supplies *out) { *out = test_inventory; return out->player != NULL; }
static int fake_mission(void) { return test_mission; }
static uint64_t fake_task(void) { return test_task; }
static void fake_supply(int type, int quantity, const Supplies *before) {
    (void)before;
    ++supply_effects;
    if (type == 1) {
        test_inventory.ammo += quantity;
        if (test_inventory.ammo > ammo_capacity) test_inventory.ammo = ammo_capacity;
    } else if (type == 4) {
        for (int i = 0; i < before->weapon_count; ++i) {
            if (partial_ammo && i) break;
            APWeaponSupply *w = &test_inventory.weapons[i];
            w->ammo += (w->maximum + 1) / 2;
            if (w->ammo > w->maximum) w->ammo = w->maximum;
            if (w->weapon == (uintptr_t)test_inventory.weapon) test_inventory.ammo = w->ammo;
        }
    } else if (type >= 11 && type <= 13) {
        for (int i = 0; i < 8; ++i) {
            if (partial_ammo && i) break;
            test_inventory.resources[i] += resource_amount(type, i, before);
        }
    } else if (type == 5) test_inventory.shivs += quantity;
    else test_inventory.kits += quantity;
    if (change_character) test_inventory.player = (void *)9;
}
static int command(int type, int arg, uint64_t receipt) {
    shared->command_type = type; shared->command_arg = arg;
    shared->command_receipt = receipt; ++shared->command_seq;
    execute_command();
    assert(shared->command_seq == shared->reply_seq);
    return shared->reply_status;
}

static void fake_play(void *node, uint64_t continuation, int state,
                      const int64_t *time, bool arg5, bool arg6) {
    (void)node; (void)continuation; (void)state; (void)arg5; (void)arg6;
    ++plays;
    observed_continuation = continuation;
    observed_time = time ? *time : -1;
    if (automatic_during_play) {
        shared->allowed = 0;
        hook_automatic(node);
    }
}

static bool fake_begin(void *node, uint64_t continuation) {
    ++begins;
    if (revoke_during_begin) shared->allowed = 0;
    int64_t time = 0;
    hook_play(node, continuation, 11, &time, true, true);
    return true;
}

static void reset_test(void) {
    memset(shared, 0, sizeof(*shared));
    shared->mode = 1;
    shared->heartbeat = GetTickCount64();
    shared->route_count = 1;
    shared->routes[0] = (APRoute){TEST_SID, 1, 0};
    pending_count = begins = plays = 0;
    admitted_mission = -1;
    engine_mission = engine_blocked = -1; engine_in_menu = false;
    prologue_start_task = 0;
    test_scene_ready = true;
    memset(&death, 0, sizeof(death));
    memset(&horn_clock, 0, sizeof(horn_clock)); horn_effects = 0; horn_result = 1;
    test_death = (DeathSample){.player=(void *)1, .playable=true}; death_effects = 0;
    memset(test_prog, 0, sizeof(test_prog)); pause_updates = 0;
    memset(test_context, 0, sizeof(test_context));
    revoke_during_begin = false;
    receipt_count = supply_effects = 0;
    test_mission = 1; ammo_capacity = 20; change_character = partial_ammo = false;
    test_task = TEST_SID; reset_supply_stage();
    automatic_starts = 0; graph_ready = true; automatic_during_play = false;
    *(uint32_t *)(test_node + 0x60) = 0;
    test_inventory = (Supplies){.player=(void *)1, .weapon=(void *)2, .inventory=(void *)3,
        .ammo_sid=UINT64_C(0xb4ce74acb1317617), .ammo=5, .kits=2,
        .kit_max=3, .shiv_max=3, .ready=true};
}

static void prepare_supplies(void) {
    reset_test(); test_mission = 3; shared->allowed = 8;
    shared->routes[0].mission = 3;
    supply_stage_ready(3, TEST_SID, &test_inventory, GetTickCount64() - SUPPLY_SETTLE_MS);
}

static void prepare_prologue_failure(void) {
    reset_test(); shared->mode = 2; shared->allowed = 1; shared->death_enabled = 17;
    test_mission = 0; test_task = UINT64_C(0x4ff33c7bc60b30a8);
    test_death.identity = (PlayerIdentity){100, 77};
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    assert(death.armed);
}
static void scripted_bite(void) {
    observe_script_failure(UINT64_C(0xef0166791679f92d), base + 0x235c9ae);
}

static int test_owned, test_grants;
static int fake_has_collectible(uint64_t sid) { assert(sid==test_collectibles[0]); return test_owned; }
static void fake_collectible(uint64_t sid) { assert(sid==test_collectibles[0]); test_owned=1; ++test_grants; }

int main(void) {
    shared = calloc(1, sizeof(*shared));
    assert(shared);
    /* find_node uses the same bounds/read checks as it does in the DLL. */
    base = (uintptr_t)calloc(1, 0x6427000);
    assert(base);
    *(uint32_t *)(base + 0x47fe910) = 602;
    *(uintptr_t *)(base + 0x47fe940) = (uintptr_t)test_node;
    memcpy(test_node + 0x28, &(uint64_t){TEST_SID}, 8);
    original_play = fake_play;
    original_begin = fake_begin;
    original_automatic = fake_automatic;
    original_pause_update = fake_pause_update;
    original_clock_update = fake_clock_update;
    *(uintptr_t *)(base + 0x6426188) = (uintptr_t)test_context;
    *(uintptr_t *)(base + 0x3644c88) = (uintptr_t)test_prog;
    automatic_ready = fake_ready;
    read_supplies = fake_supplies;
    read_active_mission = fake_mission;
    read_active_task = fake_task;
    read_scene_ready = fake_scene_ready;
    read_death_sample = fake_death_sample;
    apply_death = fake_death;
    apply_supply = fake_supply;
    apply_horn = fake_horn;

    reset_test();
    assert(hook_begin(test_node, 42));
    assert(hook_begin(test_node, 42));
    assert(begins == 0 && plays == 0); /* No cleanup/setup before the permit. */
    assert(pending_count == 1 && pending_plays[0].kind == START_BEGIN);
    assert(shared->events[0].type == 3 && shared->events[0].flags == 0x80000000u);
    replay_pending();
    assert(begins == 0 && pending_count == 1);
    shared->allowed = 2;
    replay_pending();
    assert(begins == 1 && plays == 1 && pending_count == 0 && !shared->blocked);
    puts("PASS: transition preparation waits and replays once");

    reset_test();
    shared->allowed = 2;
    revoke_during_begin = true;
    assert(hook_begin(test_node, 42));
    assert(begins == 1 && plays == 1 && pending_count == 0);
    assert(admitted_mission == -1 && shared->allowed == 0);
    assert(hook_begin(test_node, 43));
    assert(begins == 1 && pending_count == 1);
    puts("PASS: permission revocation cannot interrupt an admitted transition");

    reset_test();
    int64_t time = 1234;
    hook_play(test_node, 42, 2, &time, true, true);
    time = 9999;
    assert(plays == 0 && pending_count == 1 && pending_plays[0].kind == START_PLAY);
    shared->allowed = 2;
    replay_pending();
    assert(plays == 1 && observed_time == 1234 && pending_count == 0);
    puts("PASS: direct task requests retain copied arguments");

    reset_test();
    shared->allowed = 2;
    shared->heartbeat = GetTickCount64() - 6000;
    hook_begin(test_node, 1);
    for (int i = 0; i < 1000; ++i) replay_pending();
    assert(begins == 0 && pending_count == 1);
    shared->heartbeat = GetTickCount64();
    hook_begin(test_node, 2);
    replay_pending();
    assert(begins == 1 && pending_count == 0);
    puts("PASS: expired heartbeat holds across repeated scheduler ticks");

    reset_test();
    hook_begin(test_node, 1); hook_begin(test_node, 2);
    assert(pending_count == 1);
    shared->allowed = 2; replay_pending();
    assert(observed_continuation == 2 && begins == 1);
    puts("PASS: repeated locked requests use the latest continuation");

    reset_test();
    hook_begin(test_node, 1);
    uint64_t menu = UINT64_C(0xa823deeb3a672718);
    memcpy(test_node + 0x28, &menu, 8);
    hook_play(test_node, 0, 0, NULL, false, false);
    assert(!pending_count && !shared->blocked);
    memcpy(test_node + 0x28, &(uint64_t){TEST_SID}, 8);
    shared->allowed = 2; replay_pending();
    assert(begins == 0);
    puts("PASS: returning to the main menu cancels deferred starts");

    prepare_supplies();
    assert(command(2, 1 | (4 << 8), 100) == 1 && test_inventory.kits == 3);
    shared->allowed = 0; test_inventory.player = NULL;
    assert(command(101, 2, 100) == 1 && supply_effects == 1);
    assert(command(101, 1, 100) == 4);
    assert(command(101, 2, 101) == 5);
    assert(command(2, 1 | (4 << 8), 100) == 1 && supply_effects == 1);
    puts("PASS: receipt lookup works when full/locked/no player without a second effect");

    const uint64_t ammo_types[] = {UINT64_C(0xb4ce74acb1317617), UINT64_C(0xdde675074fc76559),
        UINT64_C(0xe908b9ecc7744100), UINT64_C(0xd40070113c4fc14c), UINT64_C(0xafdab42da5eaf722),
        UINT64_C(0xe6ecc33c5c55c8b4), UINT64_C(0x1f586b9100862fcb), UINT64_C(0x9265cc580d411f4a),
        UINT64_C(0x4226188df8bb50f0)};
    for (unsigned i = 0; i < 9; ++i) {
        prepare_supplies(); test_inventory.ammo_sid = ammo_types[i];
        test_inventory.ammo = 19;
        assert(command(1, 3 | (4 << 8), 200) == 1 && test_inventory.ammo == 20);
        assert(command(1, 3 | (4 << 8), 201) == 2 && test_inventory.ammo == 20);
        assert(command(101, 1, 201) == 5);
        test_inventory.ammo = 10;
        assert(command(1, 3 | (4 << 8), 201) == 1 && test_inventory.ammo == 13);
    }
    puts("PASS: nine ammo types honor native caps, partial delivery and capacity retry");

    prepare_supplies();
    test_inventory.ammo_sid = KIT_SID;
    assert(command(1, 3 | (4 << 8), 300) == 2 && !supply_effects);
    test_inventory.ammo_sid = UINT64_C(0xb4ce74acb1317617);
    test_mission = 2;
    assert(command(1, 3 | (4 << 8), 300) == 2 && !supply_effects);
    test_mission = 0; shared->allowed = 1;
    assert(command(2, 1 | (1 << 8), 300) == 2 && !supply_effects);
    test_mission = 3; shared->allowed = 8; shared->pending = 1;
    assert(command(1, 3 | (4 << 8), 300) == 2 && !supply_effects);
    shared->pending = 0; shared->heartbeat = GetTickCount64() - 6000;
    assert(command(1, 3 | (4 << 8), 300) == 2 && !supply_effects);
    puts("PASS: supplies reject unsupported ammo, stale mission, prologue, pending gate and disconnect");

    prepare_supplies(); change_character = true;
    assert(command(1, 3 | (4 << 8), 400) == 3 && supply_effects == 1);
    assert(command(1, 3 | (4 << 8), 400) == 3 && supply_effects == 1);
    assert(command(101, 1, 400) == 3);
    puts("PASS: character changes make a reward uncertain and prevent replay");

    reset_test(); shared->allowed = 2;
    assert(command(2, 1 | (2 << 8), 500) == 2 && !receipt_count && !supply_effects);
    test_mission = 2; shared->allowed = 4; shared->route_count = 2;
    shared->routes[0].mission = 2;
    shared->routes[1] = (APRoute){BACKPACK_TASK, 2, 0};
    test_task = BACKPACK_TASK;
    assert(command(2, 1 | (3 << 8), 500) == 2 && !receipt_count);
    assert(command(101, 2, 500) == 5);
    test_task = TEST_SID;
    assert(command(2, 1 | (3 << 8), 500) == 2 && !receipt_count);
    supply_stage.since -= SUPPLY_SETTLE_MS;
    assert(command(2, 1 | (3 << 8), 500) == 1 && supply_effects == 1);
    test_task = BACKPACK_TASK; test_inventory.kits = 1;
    assert(command(2, 1 | (3 << 8), 501) == 2 && supply_effects == 1);
    puts("PASS: early gifts wait through backpack reset and an earlier checkpoint cannot reuse readiness");

    prepare_supplies(); test_inventory.inventory = (void *)7;
    assert(command(2, 1 | (4 << 8), 600) == 2 && !receipt_count);
    supply_stage.since -= SUPPLY_SETTLE_MS;
    assert(command(2, 1 | (4 << 8), 600) == 1 && supply_effects == 1);
    test_inventory.player = (void *)8; test_inventory.kits = 1;
    assert(command(2, 1 | (4 << 8), 601) == 2 && supply_effects == 1);
    puts("PASS: replaced inventories and characters must settle before delivery");

    reset_test();
    /* Match Graph Update's independent readiness/activation path: it never
       calls Begin or Play, and clears its dirty flag after the activation. */
    assert(fake_ready(test_node));
    hook_automatic(test_node); hook_automatic(test_node);
    assert(automatic_starts == 0 && begins == 0 && plays == 0);
    assert(*(uint32_t *)(test_node + 0x60) == 0 && pending_count == 1);
    assert(shared->events[0].type == 3 && shared->events[0].flags == 0x40000000u);
    replay_pending();
    assert(automatic_starts == 0 && pending_count == 1);
    shared->allowed = 2; replay_pending(); replay_pending();
    assert(automatic_starts == 1 && !pending_count && !shared->blocked);
    assert(shared->events[1].type == 4 && shared->events[2].type == 1);
    assert(!shared->current); /* Non-player graph nodes cannot change telemetry. */
    puts("PASS: automatic graph activation waits before loading and resumes exactly once");

    for (int invalidation = 0; invalidation < 2; ++invalidation) {
        reset_test(); hook_automatic(test_node);
        if (invalidation) *(uint32_t *)(test_node + 0x60) = 3;
        else graph_ready = false;
        shared->allowed = 2; replay_pending();
        assert(!automatic_starts && !pending_count && !shared->blocked);
        assert(shared->events[1].type == 8);
    }
    puts("PASS: automatic replay discards changed state or invalid prerequisites");

    reset_test(); shared->allowed = 2; automatic_during_play = true;
    hook_play(test_node, 0, 3, NULL, false, false);
    assert(plays == 1 && automatic_starts == 1 && !pending_count && !shared->allowed);
    assert(admitted_mission == -1);
    reset_test(); automatic_during_play = true;
    hook_play(test_node, 0, 3, NULL, false, false);
    shared->allowed = 2; replay_pending();
    assert(plays == 1 && automatic_starts == 1 && !pending_count && !shared->allowed);
    assert(admitted_mission == -1);
    puts("PASS: direct and deferred Play retain admission through nested automatic activation");

    reset_test(); hook_automatic(test_node);
    shared->allowed = 2; hook_automatic(test_node); replay_pending();
    assert(automatic_starts == 1 && !pending_count);
    reset_test(); hook_automatic(test_node);
    memcpy(test_node + 0x28, &menu, 8);
    hook_play(test_node, 0, 0, NULL, false, false);
    memcpy(test_node + 0x28, &(uint64_t){TEST_SID}, 8);
    shared->allowed = 2; replay_pending();
    assert(!automatic_starts && !pending_count);
    puts("PASS: native retry consumes automatic request and menu return cancels it");

    reset_test(); shared->allowed = 2;
    shared->heartbeat = GetTickCount64() - 6000;
    hook_automatic(test_node); replay_pending();
    assert(!automatic_starts && pending_count == 1);
    shared->heartbeat = GetTickCount64(); replay_pending();
    assert(automatic_starts == 1 && !pending_count);
    puts("PASS: automatic activation stays held while the client heartbeat is stale");

    reset_test(); shared->mode = 2;
    hook_automatic(test_node);
    assert(automatic_starts == 1 && !pending_count);
    assert(*(uint32_t *)(test_node + 0x60) == 2);
    engine_frame();
    assert(!test_prog[0x63] && shared->blocked == 2 && shared->pending == 1);
    for (int i = 0; i < 10; ++i) {
        unsigned char *clock = test_context + 0x60 + i * 0x78;
        assert((*(float *)(clock + 0x20) == 0) == (i == 1 || i == 2 || i == 5));
        assert(*(int32_t *)(clock + 0x40) == 0);
    }
    assert(shared->events[1].type == 3 && shared->events[1].flags == ENGINE_GATE_FLAG);
    for (int i = 0; i < 1000; ++i) engine_frame();
    assert(pause_updates == 1001 && shared->write == 2 && !pending_count);
    shared->allowed = 2; engine_frame();
    assert(!test_prog[0x63] && !shared->blocked && !shared->pending);
    assert(*(float *)(test_context + 0xf8) > 0);
    assert(shared->events[2].type == 4 && automatic_starts == 1);
    puts("PASS: game clocks stop while menu clocks advance, without persistent counters or duplicate events");

    reset_test(); shared->mode = 2;
    *(int32_t *)(test_context + 0x118) = 2;
    test_prog[0x61] = 1; engine_frame();
    shared->allowed = 2; engine_frame();
    assert(test_prog[0x61] && test_prog[0x62] && test_prog[0x63]);
    assert(*(int32_t *)(test_context + 0x118) == 2 && *(float *)(test_context + 0xf8) == 0);
    assert(!shared->blocked && !shared->pending);
    puts("PASS: unlocking preserves a pause requested by the player/game");

    reset_test(); shared->mode = 2; hook_pause_update(test_prog);
    memcpy(test_node + 0x28, &menu, 8);
    hook_play(test_node, 0, 0, NULL, false, false);
    hook_pause_update(test_prog);
    assert(!shared->pending && !test_prog[0x63] && engine_in_menu);
    memcpy(test_node + 0x28, &(uint64_t){TEST_SID}, 8);
    shared->allowed = 2;
    hook_play(test_node, 0, 0, NULL, false, false); hook_pause_update(test_prog);
    assert(!engine_in_menu && !shared->pending && plays == 2);
    puts("PASS: returning to the menu clears the hold even while old task telemetry is stale");

    reset_test(); shared->mode = 2; shared->allowed = 2;
    shared->heartbeat = GetTickCount64() - 6000;
    engine_frame();
    assert(!test_prog[0x63] && shared->pending && *(float *)(test_context + 0xf8) == 0);
    shared->heartbeat = GetTickCount64(); engine_frame();
    assert(!test_prog[0x63] && !shared->pending);
    assert(*(float *)(test_context + 0xf8) > 0);
    puts("PASS: engine gate blocks stale-heartbeat gameplay and recovers on reconnect");

    reset_test(); shared->mode = 2; hook_pause_update(test_prog);
    shared->mode = 0; hook_pause_update(test_prog);
    assert(!test_prog[0x63] && !shared->pending && !shared->blocked);
    puts("PASS: shutting down the offline lab removes only its engine pause");

    reset_test(); shared->mode = 2;
    assert(hook_begin(test_node, 123));
    assert(begins == 1 && plays == 1 && !pending_count);
    engine_frame();
    assert(shared->pending && !test_prog[0x63]);
    shared->command_type = 101; shared->command_arg = 2;
    shared->command_receipt = 999; shared->command_seq = 1;
    hook_pause_update(test_prog);
    assert(shared->reply_seq == 1 && shared->reply_status == 5);
    puts("PASS: original setup callbacks run and the paused frame still services client commands");

    reset_test(); shared->mode = 2; engine_frame();
    memset(test_context, 0, sizeof(test_context)); engine_frame();
    assert(*(float *)(test_context + 0xf8) == 0 && *(int32_t *)(test_context + 0x118) == 0);
    shared->allowed = 2; engine_frame();
    assert(*(float *)(test_context + 0xf8) > 0);
    puts("PASS: reset clocks reapply the hold without underflow or residual pause counts");

    reset_test(); shared->mode = 2; test_scene_ready = false;
    hook_play(test_node, 0, 3, NULL, false, false);
    for (int frame = 0; frame < 1000; ++frame) engine_frame();
    assert(plays == 1 && !shared->pending && !shared->blocked && !shared->allowed);
    for (int i = 0; i < 10; ++i)
        assert(*(float *)(test_context + 0x60 + i * 0x78 + 0x20) > 0);
    test_scene_ready = true; engine_frame();
    assert(shared->pending && shared->blocked == 2 && *(float *)(test_context + 0xf8) == 0);
    puts("PASS: a denied mission may finish asynchronous loading before its clocks are held");

    test_scene_ready = false; engine_frame();
    assert(!shared->pending && !shared->blocked && !shared->allowed);
    assert(*(float *)(test_context + 0xf8) > 0);
    test_scene_ready = true; engine_frame();
    assert(shared->pending && shared->blocked == 2 && !shared->allowed);
    shared->allowed = 2; engine_frame();
    assert(!shared->pending && *(float *)(test_context + 0xf8) > 0);
    puts("PASS: checkpoint teardown can run and the denied mission re-locks when ready");
    reset_test(); shared->mode = 2; shared->allowed = 2;
    update_death_link(); assert(shared->death_state == 0);
    shared->death_enabled = 17;
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    assert(shared->death_state == 2);
    test_death.dead = true; update_death_link(); update_death_link();
    assert(shared->death_local == 1 && shared->death_remote == 0 && shared->death_state == 1);
    puts("PASS: DeathLink is opt-in and one natural death creates one local event");

    test_death.dead = false; update_death_link();
    death.since = GetTickCount64() - 1100; update_death_link();
    uint64_t death_receipt = (UINT64_C(17) << 32) | 123;
    assert(command(3, 2 << 8, death_receipt) == 1 && death_effects == 1);
    assert(command(3, 2 << 8, death_receipt) == 1 && death_effects == 1);
    assert(shared->death_state == 3);
    test_death.dead = true; update_death_link(); update_death_link();
    assert(shared->death_local == 1 && shared->death_remote == 1);
    puts("PASS: received death is submitted once and its actual death never echoes");

    test_death.dead = false; update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    test_death.playable = false;
    assert(command(3, 2 << 8, death_receipt + 1) == 2 && death_effects == 1);
    test_death.playable = true; shared->allowed = 0;
    assert(command(3, 2 << 8, death_receipt + 1) == 2 && death_effects == 1);
    shared->allowed = 2; death.since = GetTickCount64() - 1100; update_death_link();
    assert(command(3, 3 << 8, death_receipt + 1) == 2);
    assert(command(3, 2 << 8, (UINT64_C(16) << 32) | 5) == 2);
    shared->heartbeat = GetTickCount64() - 6000;
    assert(command(3, 2 << 8, death_receipt + 1) == 2);
    puts("PASS: pause/load/cinematic, denied mission, stale epoch, mission and heartbeat refuse DeathLink");

    shared->heartbeat = GetTickCount64(); update_death_link();
    death.since = GetTickCount64() - 1100; update_death_link();
    assert(command(3, 2 << 8, death_receipt + 2) == 1);
    death.remote_since = GetTickCount64() - 6000; update_death_link();
    assert(shared->death_remote == 1 && shared->death_local == 1 && !death.remote);
    puts("PASS: rejected death times out without retransmission or false death confirmation");

    engine_in_menu = true; update_death_link();
    assert(!death.armed && !shared->death_state);
    engine_in_menu = false; test_mission = 0; update_death_link();
    assert(!death.armed && !shared->death_state);
    puts("PASS: main menu and Hometown scripted finale are excluded from DeathLink");

    /* The real 1.1.3.0 Prologue task routes, in story order. */
    const uint64_t playable_home[] = {
        UINT64_C(0x112a5f80e30b214e), UINT64_C(0xe69b45db45575c87),
        UINT64_C(0x93fdeb3dbc369f95), UINT64_C(0x996a06a412c8b107),
        UINT64_C(0xd80268ae227551c6), UINT64_C(0xf255ed0f3772df2f),
        UINT64_C(0x08eb2b7c833d81bb), UINT64_C(0x382c63ebbd8006cb),
        UINT64_C(0xd1a5df5d6d36cbae), UINT64_C(0x83ef7aa79d76692a),
        UINT64_C(0x64b4842e9e21d1cf), UINT64_C(0x4ad08ce8818fed2e),
        UINT64_C(0x4ff33c7bc60b30a8), UINT64_C(0x1f7f35c41da66c64),
        UINT64_C(0x06bd1a40d00f58d8), UINT64_C(0x63a5e41f4b84ad43)};
    const uint64_t scripted_home[] = {
        UINT64_C(0xcfccb229e125cd9c), UINT64_C(0x865d7d47931fa212),
        UINT64_C(0x9883e7538de879ae), UINT64_C(0x92ac028e47f6b463),
        UINT64_C(0x7373d27bfb7a1546), UINT64_C(0x3986da46077b7c82),
        UINT64_C(0x5fe70475c5a83158), UINT64_C(0xd819304ac85f1348),
        UINT64_C(0x7a6208b9892fd6e9), UINT64_C(0xf4275f1f961e3127),
        UINT64_C(0xd6020e591a6c3b10), UINT64_C(0xeeeff838825c0b8f),
        UINT64_C(0xe548e177d9c789a4), UINT64_C(0xaae7cde2a9f10f63), 0, TEST_SID};
    for (unsigned i = 0; i < sizeof(playable_home) / sizeof(*playable_home); ++i) {
        reset_test(); shared->mode = 2; shared->allowed = 1; shared->death_enabled = 17;
        test_mission = 0; test_task = playable_home[i];
        update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
        assert(shared->death_state == 2);
        update_airhorn(); horn_clock.since = GetTickCount64() - 1100; update_airhorn();
        assert(shared->airhorn_ready && shared->prologue_stage == 1);
        assert(command(6, 1 | (1 << 8), 9000) == 1 && horn_effects == 1);
        assert(command(3, 1 << 8, death_receipt) == 1 && death_effects == 1);
        test_death.dead = true; update_death_link(); update_death_link();
        assert(shared->death_remote == 1 && shared->death_local == 0);
    }
    puts("PASS: all 16 playable Prologue tasks accept Airhorn and incoming DeathLink without echo");

    for (unsigned i = 0; i < sizeof(scripted_home) / sizeof(*scripted_home); ++i) {
        reset_test(); shared->mode = 2; shared->allowed = 1; shared->death_enabled = 17;
        test_mission = 0; test_task = playable_home[15];
        update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
        test_task = scripted_home[i]; test_death.dead = true;
        update_death_link(); update_airhorn();
        assert(shared->death_local == 0 && shared->death_remote == 0 && !death.armed);
        test_death.dead = false;
        assert(command(3, 1 << 8, death_receipt) == 2 && !death_effects);
        assert(command(6, 1 | (1 << 8), 9001) == 2 && !horn_effects);
        assert(!shared->airhorn_clock_ms && shared->prologue_stage == 2);
    }
    puts("PASS: intro, car, crash/QTE, story death, credits and unknown tasks never emit or consume effects");

    for (unsigned kind = 0; kind < 3; ++kind) {
        reset_test(); shared->mode = 2; shared->allowed = 1; shared->death_enabled = 17;
        test_mission = 0; test_task = playable_home[15];
        update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
        shared->routes[0] = (APRoute){UINT64_C(0xeeeff838825c0b8f), 0, 0};
        *(uint64_t *)(test_node + 0x28) = shared->routes[0].sid;
        if (kind == 0) hook_begin(test_node, 0);
        else if (kind == 1) hook_play(test_node, 0, 0, NULL, false, false);
        else hook_automatic(test_node);
        /* Active pointer still says woods chase, and dead appears this frame. */
        test_death.dead = true; update_death_link(); update_airhorn();
        assert(!shared->death_local && !shared->death_remote && !shared->death_state);
        assert(!shared->airhorn_ready && shared->prologue_stage == 2);
    }
    *(uint64_t *)(test_node + 0x28) = TEST_SID;
    puts("PASS: Begin, Play and automatic finale starts disarm before stale-task story death samples");

    reset_test(); shared->mode = 2; shared->allowed = 1; shared->death_enabled = 17;
    test_mission = 0; test_task = playable_home[0];
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    test_death.dead = true; update_death_link(); update_death_link();
    assert(shared->death_local == 1 && !shared->death_remote);
    test_death.dead = false;
    engine_start(UINT64_C(0xeeeff838825c0b8f), 0);
    engine_start(playable_home[0], 0); /* Earlier checkpoint restores gameplay policy. */
    update_death_link(); assert(!shared->death_state);
    death.since = GetTickCount64() - 1100; update_death_link(); assert(shared->death_state == 2);
    test_death.dead = true; update_death_link(); assert(shared->death_local == 2);
    puts("PASS: natural playable Prologue deaths emit once and checkpoint reload rearms after stability");

    reset_test(); shared->mode = 2; shared->allowed = 1; shared->death_enabled = 17;
    test_mission = 0; test_task = playable_home[0];
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    update_airhorn(); horn_clock.since = GetTickCount64() - 1100; update_airhorn();
    horn_clock.last = GetTickCount64() - 50; update_airhorn();
    LONG64 prologue_time = shared->airhorn_clock_ms;
    test_death.playable = false; update_death_link(); update_airhorn();
    assert(!death.armed && !shared->airhorn_ready && shared->airhorn_clock_ms == prologue_time);
    assert(command(3, 1 << 8, death_receipt) == 2);
    assert(command(6, 1 | (1 << 8), 9002) == 2);
    test_death.playable = true; shared->allowed = 0; update_death_link(); update_airhorn();
    assert(!death.armed && !shared->airhorn_ready);
    shared->allowed = 1; engine_start(UINT64_C(0xeeeff838825c0b8f), 0);
    test_task = UINT64_C(0xeeeff838825c0b8f); update_airhorn();
    assert(shared->airhorn_clock_ms == prologue_time);
    test_mission = 1; test_task = TEST_SID; engine_start(TEST_SID, 1); shared->allowed = 2;
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    update_airhorn(); horn_clock.since = GetTickCount64() - 1100; update_airhorn();
    assert(shared->death_state == 2 && shared->airhorn_ready && !shared->prologue_stage);
    puts("PASS: Prologue scenes/locks pause timers and queued effects become ready in 20 Years Later");

    assert(command(3, 2 << 8, death_receipt) == 1);
    engine_start(playable_home[0], 0); /* Load while a remote death is unconfirmed. */
    assert(shared->events[shared->write - 1].type == 10 && !death.remote);
    test_mission = 0; test_task = UINT64_C(0xeeeff838825c0b8f); test_death.dead = true;
    update_death_link(); assert(!shared->death_remote && !shared->death_local);
    puts("PASS: transition during remote dispatch reports uncertainty, never consumes a story death");

    prepare_prologue_failure();
    test_death.player = (void *)9; update_death_link();
    assert(death.armed && death.player == (void *)9);
    test_death.dead = true; update_death_link();
    assert(shared->death_local == 1);
    puts("PASS: relocating a living player object preserves natural death detection");

    prepare_prologue_failure();
    update_airhorn(); horn_clock.since = GetTickCount64() - 1100; update_airhorn();
    horn_clock.last = GetTickCount64() - 50;
    test_death.player = (void *)9; update_airhorn();
    assert(shared->airhorn_ready && shared->airhorn_clock_ms > 0);
    ++test_death.identity.generation; update_death_link(); update_airhorn();
    assert(!death.armed && !shared->airhorn_ready);
    scripted_bite(); assert(!shared->death_local);
    puts("PASS: stable handles preserve Airhorn time; a new generation requires fresh stability");

    prepare_prologue_failure();
    test_death.player = (void *)9;
    scripted_bite(); scripted_bite(); update_death_link();
    death.since = GetTickCount64() - 1100; update_death_link(); scripted_bite();
    assert(shared->death_local == 1 && !shared->death_remote && death.script_failed && !death.armed);
    assert(command(3, 1 << 8, death_receipt) == 2);
    test_death.dead = true; update_death_link();
    assert(shared->death_local == 1);
    test_death.dead = false; ++test_death.identity.generation;
    engine_start(test_task, 0); update_death_link();
    death.since = GetTickCount64() - 1100; update_death_link(); scripted_bite();
    assert(shared->death_local == 2);
    puts("PASS: scripted bites count once through Move/Death and rearm only after respawn or task restart");

    prepare_prologue_failure();
    assert(command(3, 1 << 8, death_receipt) == 1);
    scripted_bite(); scripted_bite(); test_death.dead = true; update_death_link();
    assert(shared->death_remote == 1 && !shared->death_local);
    prepare_prologue_failure();
    assert(command(3, 1 << 8, death_receipt) == 1);
    test_death.dead = true; update_death_link(); scripted_bite();
    assert(shared->death_remote == 1 && !shared->death_local);
    puts("PASS: script/FSM confirmations in either order never echo or double-count a remote death");

    prepare_prologue_failure();
    observe_script_failure(TEST_SID, base + 0x235c9ae);
    observe_script_failure(UINT64_C(0xef0166791679f92d), base + 0x235cb34);
    engine_start(test_task, 0); update_death_link();
    assert(!shared->death_local);
    puts("PASS: unrelated failure events and checkpoint restarts are not deaths");

    for (unsigned i = 0; i < sizeof(scripted_home) / sizeof(*scripted_home); ++i) {
        prepare_prologue_failure(); test_task = scripted_home[i]; scripted_bite();
        assert(!shared->death_local && !shared->death_remote);
    }
    prepare_prologue_failure(); engine_start(UINT64_C(0xeeeff838825c0b8f), 0);
    /* Active task still names playable alley at the moment of the event. */
    scripted_bite(); assert(!shared->death_local && !shared->death_remote);
    puts("PASS: scripted failures in the finale, car, movies and unknown tasks remain excluded");

    for (unsigned i = 0; i < 7; ++i) {
        prepare_prologue_failure();
        if (i == 0) shared->death_enabled = 0;
        if (i == 1) shared->heartbeat = GetTickCount64() - 6000;
        if (i == 2) shared->allowed = 0;
        if (i == 3) shared->pending = 1;
        if (i == 4) engine_in_menu = true;
        if (i == 5) { test_death.playable = false; update_death_link(); }
        if (i == 6) test_mission = 1;
        scripted_bite(); assert(!shared->death_local && !shared->death_remote);
    }
    puts("PASS: disabled, disconnected, locked, paused and non-Prologue failures cannot send DeathLink");

    prepare_supplies(); test_inventory.weapon = NULL; test_inventory.weapon_count = 3;
    test_inventory.weapons[0] = (APWeaponSupply){2, UINT64_C(0xb4ce74acb1317617), 12, 20, 6, 0};
    test_inventory.weapons[1] = (APWeaponSupply){3, UINT64_C(0xdde675074fc76559), 0, 20, 6, 0};
    test_inventory.weapons[2] = (APWeaponSupply){4, UINT64_C(0x1f586b9100862fcb), 0, 9, 1, 0};
    /* No drawn gun: refuse without consuming the reward. */
    assert(command(4, 1 | (4 << 8), 700) == 2 && !receipt_count && !supply_effects);
    test_inventory.weapon = (void *)2; test_inventory.ammo = 12;
    assert(command(4, 1 | (4 << 8), 700) == 2 && !receipt_count && !supply_effects);
    /* Empty holstered guns do not trigger it. Drawing one does. */
    test_inventory.weapon = (void *)3; test_inventory.ammo_sid = ammo_types[1]; test_inventory.ammo = 0;
    assert(command(4, 1 | (4 << 8), 700) == 1);
    assert(test_inventory.weapons[0].ammo == 20 && test_inventory.weapons[1].ammo == 10
           && test_inventory.weapons[2].ammo == 5);
    assert(command(4, 1 | (4 << 8), 700) == 1 && supply_effects == 1);
    assert(command(101, 4, 700) == 1 && command(101, 1, 700) == 4);
    assert(command(4, 1 | (4 << 8), 701) == 1);
    assert(command(4, 1 | (4 << 8), 702) == 2 && supply_effects == 2);
    puts("PASS: drawn gun at or below half triggers all owned guns; caps, odd rounding and duplicate receipts hold");

    test_inventory.weapons[0].ammo = test_inventory.weapons[1].ammo = 0;
    test_inventory.ammo = 0;
    partial_ammo = true;
    assert(command(4, 1 | (4 << 8), 702) == 3);
    assert(command(4, 1 | (4 << 8), 702) == 3 && supply_effects == 3);
    assert(command(101, 4, 702) == 3);
    puts("PASS: partially applied ammo batch remains uncertain and cannot replay");

    prepare_supplies(); test_inventory.weapon_count = 0;
    assert(command(4, 1 | (4 << 8), 800) == 2 && !supply_effects);
    test_inventory.shivs = 2;
    assert(command(5, 1 | (4 << 8), 801) == 1 && test_inventory.shivs == 3);
    assert(command(5, 1 | (4 << 8), 802) == 2 && supply_effects == 1);
    test_inventory.shivs = 1; test_inventory.shiv_max = 0;
    assert(command(5, 1 | (4 << 8), 802) == 2);
    test_inventory.shiv_max = 3;
    assert(command(5, 1 | (4 << 8), 802) == 1 && test_inventory.shivs == 2);
    assert(command(101, 5, 802) == 1);
    puts("PASS: no owned guns queues ammo; shiv cap, Ellie wait, capacity retry and receipts");

    prepare_supplies(); test_inventory.weapon_count = 1;
    test_inventory.weapons[0] = (APWeaponSupply){2, UINT64_C(0xb4ce74acb1317617), 11, 20, 6, 0};
    test_inventory.ammo = 11;
    assert(command(4, 1 | (4 << 8), 850) == 2 && !receipt_count && !supply_effects);
    assert(command(101, 4, 850) == 5);
    test_inventory.ammo = test_inventory.weapons[0].ammo = 10;
    assert(command(4, 1 | (4 << 8), 850) == 1 && test_inventory.weapons[0].ammo == 20);
    assert(command(4, 1 | (4 << 8), 850) == 1 && supply_effects == 1);
    prepare_supplies(); test_inventory.weapon_count = 1;
    test_inventory.weapons[0] = (APWeaponSupply){2, UINT64_C(0xb4ce74acb1317617), 5, 9, 1, 0};
    test_inventory.ammo = 5;
    assert(command(4, 1 | (4 << 8), 851) == 2 && !receipt_count);
    test_inventory.ammo = test_inventory.weapons[0].ammo = 4;
    test_inventory.weapon = (void *)99;
    assert(command(4, 1 | (4 << 8), 851) == 2 && !receipt_count);
    test_inventory.weapon = (void *)2;
    assert(command(4, 1 | (4 << 8), 851) == 1 && test_inventory.weapons[0].ammo == 9);
    puts("PASS: application-time half-ammo guard rejects stale eligibility, switches and odd >half totals; same receipt retries once");


    prepare_supplies(); test_inventory.ready = false;
    assert(command(2, 1 | (4 << 8), 900) == 2);
    assert(command(4, 1 | (4 << 8), 901) == 2);
    assert(command(5, 1 | (4 << 8), 902) == 2 && !supply_effects);
    test_inventory.ready = true;
    assert(command(5, 1 | (4 << 8), 902) == 1);
    puts("PASS: supplies wait for playable state then deliver the same queued receipt");
    prepare_supplies();
    assert(supply_playable((void *)1));
    engine_in_menu = true; assert(!supply_playable((void *)1));
    engine_in_menu = false; test_death.playable = false;
    assert(!supply_playable((void *)1));
    test_death.playable = true; test_death.dead = true;
    assert(!supply_playable((void *)1));
    test_death.dead = false; assert(!supply_playable((void *)9));
    assert(supply_playable((void *)1));
    puts("PASS: supply readiness requires matching living player, playable scene and no main menu");

    prepare_supplies();
    shared->route_count = 2; shared->routes[1] = (APRoute){DEER_HUNT_TASK, 23, 0};
    shared->allowed |= 1 << 23; test_mission = 23; test_task = DEER_HUNT_TASK;
    supply_stage_ready(23, DEER_HUNT_TASK, &test_inventory, GetTickCount64() - SUPPLY_SETTLE_MS);
    test_inventory.weapon_count = 1;
    test_inventory.weapons[0] = (APWeaponSupply){2, UINT64_C(0x1f586b9100862fcb), 0, 9, 1, 0};
    test_inventory.ammo_sid = ammo_types[6]; test_inventory.ammo = 0;
    assert(command(4, 1 | (24 << 8), 1000) == 2 && !supply_effects);
    assert(command(101, 4, 1000) == 5);
    assert(command(2, 1 | (24 << 8), 1001) == 1 && test_inventory.kits == 3);
    test_mission = 3; test_task = TEST_SID;
    supply_stage_ready(3, TEST_SID, &test_inventory, GetTickCount64() - SUPPLY_SETTLE_MS);
    assert(command(4, 1 | (4 << 8), 1000) == 1 && test_inventory.weapons[0].ammo == 5);
    puts("PASS: scripted deer-hunt ammo reset queues the entire gift; same receipt delivers later");
    prepare_supplies(); shared->mode = 2;
    update_airhorn(); assert(!shared->airhorn_ready);
    horn_clock.since = GetTickCount64() - 1100; update_airhorn();
    assert(shared->airhorn_ready);
    horn_clock.last = GetTickCount64() - 50; update_airhorn();
    assert(shared->airhorn_clock_ms >= 50);
    assert(command(6, 1 | (4 << 8), 2000) == 1 && horn_effects == 1);
    assert(shared->events[(shared->write-1) % AP_EVENTS].type == 11);
    assert(AP_EVENT_PLAYER_DEATH != 11);
    assert(command(6, 1 | (4 << 8), 2000) == 1 && horn_effects == 1);
    assert(shared->events[(shared->write-1) % AP_EVENTS].type == 11);
    assert(AP_EVENT_PLAYER_DEATH != 11);
    assert(command(101, 6, 2000) == 1 && command(101, 5, 2000) == 4);
    puts("PASS: stable playable Airhorn clock and receipt-protected single pulse");

    LONG64 old_clock = shared->airhorn_clock_ms;
    test_death.playable = false; horn_clock.last = GetTickCount64() - 50;
    update_airhorn(); assert(!shared->airhorn_ready && shared->airhorn_clock_ms == old_clock);
    assert(command(6, 1 | (4 << 8), 2001) == 2 && horn_effects == 1);
    test_death.playable = true; shared->allowed = 0; update_airhorn();
    assert(!shared->airhorn_ready && shared->airhorn_clock_ms == old_clock);
    assert(command(6, 1 | (4 << 8), 2001) == 2);
    shared->allowed = 8; engine_in_menu = true; update_airhorn(); assert(!shared->airhorn_ready);
    engine_in_menu = false; test_death.dead = true; update_airhorn(); assert(!shared->airhorn_ready);
    test_death.dead = false; shared->heartbeat = GetTickCount64() - 6000;
    update_airhorn(); assert(!shared->airhorn_ready);
    puts("PASS: pause/cinematic, mission lock, menu, death and stale heartbeat defer noise and freeze its clock");

    shared->heartbeat = GetTickCount64(); update_airhorn();
    horn_clock.since = GetTickCount64() - 1100; update_airhorn();
    horn_result = 2;
    assert(command(6, 1 | (4 << 8), 2001) == 2 && command(101, 6, 2001) == 5);
    horn_result = 1;
    assert(command(6, 1 | (4 << 8), 2001) == 1);
    assert(command(6, 1 | (5 << 8), 2002) == 2);
    puts("PASS: full/no-effect noise queue retries the same receipt; wrong mission cannot emit");

    horn_result = 3;
    assert(command(6, 1 | (4 << 8), 2003) == 3);
    int horn_before = horn_effects;
    assert(command(6, 1 | (4 << 8), 2003) == 3 && horn_effects == horn_before);
    assert(command(101, 6, 2003) == 3);
    puts("PASS: ambiguous noise enqueue is held and never blindly repeated");
    test_death.player = (void *)9; update_airhorn(); assert(!shared->airhorn_ready);
    horn_clock.since = GetTickCount64() - 1100; update_airhorn();
    assert(shared->airhorn_ready);
    old_clock = shared->airhorn_clock_ms;
    horn_clock.last = GetTickCount64() - 5000; update_airhorn();
    assert(shared->airhorn_clock_ms == old_clock);
    puts("PASS: character changes require settling; stalled frames do not consume five seconds");
    prepare_prologue_failure();
    test_mission = 13; test_task = PITTSBURGH_QTE_TASK;
    shared->allowed = 1 << 13;
    effects_task_started(test_task, 13);
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    assert(death.armed);
    scripted_bite();
    assert(shared->death_local == 1 && death.script_failed);
    scripted_bite(); test_death.dead = true; update_death_link();
    assert(shared->death_local == 1);
    test_death.dead = false;
    effects_task_started(test_task, 13); /* Same actor survives checkpoint reset. */
    assert(!death.script_failed && shared->death_local == 1);
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    assert(death.armed);
    scripted_bite(); assert(shared->death_local == 2);
    puts("PASS: Pittsburgh fatal QTE sends once; same-actor checkpoint reload rearms without a false death");
    effects_task_started(test_task, 13);
    update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
    test_task = TEST_SID; scripted_bite(); assert(shared->death_local == 2);
    test_task = PITTSBURGH_QTE_TASK;
    death.remote = true; death.receipt = 4001;
    scripted_bite(); assert(shared->death_local == 2 && shared->death_remote == 1);
    scripted_bite(); assert(shared->death_remote == 1);
    puts("PASS: unknown Pittsburgh failures remain excluded; remote-death confirmation never echoes");

    for (unsigned scenario = 0; scenario < 6; ++scenario) {
        prepare_prologue_failure();
        test_mission = 14; test_task = HOTEL_DROWNING_TASK;
        shared->allowed = 1 << 14;
        effects_task_started(test_task, 14);
        update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
        assert(death.armed);
        uintptr_t caller = base + 0x235cb34;
        uint64_t fail = UINT64_C(0xef0166791679f92d);
        if (scenario == 1) caller = base + 0x235c9ae;
        if (scenario == 2) test_task = TEST_SID;
        if (scenario == 3) fail = TEST_SID;
        if (scenario == 4) engine_in_menu = true;
        if (scenario == 5) shared->allowed = 0;
        observe_script_failure(fail, caller);
        assert(shared->death_local == (scenario == 0));
        if (scenario) continue;
        assert(death.script_failed);
        observe_script_failure(fail, caller);
        test_death.dead = true; update_death_link();
        assert(shared->death_local == 1);
        test_death.dead = false;
        effects_task_started(test_task, 14);
        assert(!death.script_failed && shared->death_local == 1);
        update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
        observe_script_failure(fail, caller);
        assert(shared->death_local == 2);
        effects_task_started(test_task, 14);
        update_death_link(); death.since = GetTickCount64() - 1100; update_death_link();
        death.remote = true; death.receipt = 4101;
        observe_script_failure(fail, caller); observe_script_failure(fail, caller);
        assert(shared->death_local == 2 && shared->death_remote == 1);
    }
    puts("PASS: hotel drowning sends once, rearms on reload and excludes wrong calls/tasks, menus, locks and echoes");

    for (unsigned scenario=0; scenario<9; ++scenario) {
        prepare_prologue_failure();test_mission=18;test_task=SUBURBS_SNIPER_TASK;
        shared->allowed=1<<18;effects_task_started(test_task,18);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed);test_death.playable=false;update_death_link();
        assert(death.armed && shared->death_state==0); /* Not eligible for incoming death. */
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1){death.last_playable=GetTickCount64()-2100;update_death_link();}
        if(scenario==2){engine_in_menu=true;update_death_link();}
        if(scenario==3){shared->allowed=0;update_death_link();}
        if(scenario==4){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==5)caller=base+0x235cb34;
        if(scenario==6)test_task=TEST_SID;
        if(scenario==7){effects_task_started(test_task,18);} /* Manual restart is not a death. */
        if(scenario==8){death.remote=true;death.receipt=4201;}
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==8));
        if(scenario==0){
            test_death.dead=true;update_death_link();assert(shared->death_local==1);
            test_death.dead=false;test_death.playable=true;effects_task_started(test_task,18);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            assert(death.armed && !death.script_failed);assert(shared->death_local==1);
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    puts("PASS: Suburbs sniper brief control loss, exact failure, expiry, menu/lock/disconnect exclusion, no echo and checkpoint rearming");

    for (unsigned scenario=0; scenario<8; ++scenario) {
        prepare_prologue_failure();test_mission=18;test_task=SUBURBS_TEAM_TASK;
        shared->allowed=1<<18;effects_task_started(test_task,18);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed && !test_death.dead);
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1)caller=base+0x235cb34;
        if(scenario==2)test_task=TEST_SID;
        if(scenario==3){engine_in_menu=true;update_death_link();}
        if(scenario==4){shared->allowed=0;update_death_link();}
        if(scenario==5){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==6){effects_task_started(test_task,18);} /* Restart alone emits nothing. */
        if(scenario==7){death.remote=true;death.receipt=4301;}
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==7));
        if(scenario==0){
            update_death_link();assert(shared->death_local==1 && death.script_failed);
            effects_task_started(test_task,18);assert(!death.script_failed && shared->death_local==1);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    puts("PASS: Suburbs team failure sends once with Joel alive, resets on checkpoint and excludes unrelated failures/restarts/echoes");

    for (unsigned scenario=0; scenario<8; ++scenario) {
        prepare_prologue_failure();test_mission=24;test_task=CABIN_HUNTER_TASK;
        shared->allowed=1<<24;effects_task_started(test_task,24);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed && !test_death.dead);
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1)caller=base+0x235cb34;
        if(scenario==2)test_task=TEST_SID;
        if(scenario==3){engine_in_menu=true;update_death_link();}
        if(scenario==4){shared->allowed=0;update_death_link();}
        if(scenario==5){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==6){effects_task_started(test_task,24);} /* Restart alone emits nothing. */
        if(scenario==7){death.remote=true;death.receipt=4401;}
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==7));
        if(scenario==0){
            update_death_link();assert(shared->death_local==1 && death.script_failed);
            effects_task_started(test_task,24);assert(!death.script_failed && shared->death_local==1);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    puts("PASS: Cabin Resort hunter grab sends once, resets on checkpoint and excludes unrelated failures/restarts/echoes");

    for (unsigned scenario=0; scenario<8; ++scenario) {
        prepare_prologue_failure();test_mission=24;test_task=CABIN_JOEL_TASK;
        shared->allowed=1<<24;effects_task_started(test_task,24);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed && !test_death.dead);
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1)caller=base+0x235cb34;
        if(scenario==2)test_task=TEST_SID;
        if(scenario==3){engine_in_menu=true;update_death_link();}
        if(scenario==4){shared->allowed=0;update_death_link();}
        if(scenario==5){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==6){effects_task_started(test_task,24);} /* Restart alone emits nothing. */
        if(scenario==7){death.remote=true;death.receipt=4501;}
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==7));
        if(scenario==0){
            update_death_link();assert(shared->death_local==1 && death.script_failed);
            effects_task_started(test_task,24);assert(!death.script_failed && shared->death_local==1);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    puts("PASS: Cabin Resort Joel two-hunter stabbing sends once, resets on checkpoint and excludes unrelated failures/restarts/echoes");

    for (unsigned scenario=0; scenario<8; ++scenario) {
        prepare_prologue_failure();test_mission=24;test_task=CABIN_DAVID_TASK;
        shared->allowed=1<<24;effects_task_started(test_task,24);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed && !test_death.dead);
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1)caller=base+0x235cb34;
        if(scenario==2)test_task=TEST_SID;
        if(scenario==3){engine_in_menu=true;update_death_link();}
        if(scenario==4){shared->allowed=0;update_death_link();}
        if(scenario==5){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==6){effects_task_started(test_task,24);} /* Restart alone emits nothing. */
        if(scenario==7){death.remote=true;death.receipt=4601;}
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==7));
        if(scenario==0){
            update_death_link();assert(shared->death_local==1 && death.script_failed);
            effects_task_started(test_task,24);assert(!death.script_failed && shared->death_local==1);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    puts("PASS: Cabin Resort David strangling QTE sends once, resets on checkpoint and excludes unrelated failures/restarts/echoes");

    for (unsigned scenario=0; scenario<8; ++scenario) {
        prepare_prologue_failure();test_mission=26;test_task=BUS_WATER_TASK;
        shared->allowed=1<<26;effects_task_started(test_task,26);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed && !test_death.dead);
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1)caller=base+0x235cb34;
        if(scenario==2)test_task=TEST_SID;
        if(scenario==3){engine_in_menu=true;update_death_link();}
        if(scenario==4){shared->allowed=0;update_death_link();}
        if(scenario==5){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==6){effects_task_started(test_task,26);} /* Restart alone emits nothing. */
        if(scenario==7){death.remote=true;death.receipt=4701;}
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==7));
        if(scenario==0){
            update_death_link();assert(shared->death_local==1 && death.script_failed);
            effects_task_started(test_task,26);assert(!death.script_failed && shared->death_local==1);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    puts("PASS: Bus Depot water fall sends once, resets on checkpoint and excludes unrelated failures/restarts/echoes");

    for (unsigned scenario=0; scenario<8; ++scenario) {
        prepare_prologue_failure();test_mission=13;test_task=PITTSBURGH_ELLIE_TASK;
        shared->allowed=1<<13;effects_task_started(test_task,13);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed && !test_death.dead);
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1)caller=base+0x235cb34;
        if(scenario==2)test_task=TEST_SID;
        if(scenario==3){engine_in_menu=true;update_death_link();}
        if(scenario==4){shared->allowed=0;update_death_link();}
        if(scenario==5){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==6){effects_task_started(test_task,13);} /* Restart alone emits nothing. */
        if(scenario==7){death.remote=true;death.receipt=4901;}
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==7));
        if(scenario==0){
            update_death_link();assert(shared->death_local==1 && death.script_failed);
            effects_task_started(test_task,13);assert(!death.script_failed && shared->death_local==1);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    puts("PASS: Pittsburgh Ellie death sends once, resets on checkpoint and excludes unrelated failures/restarts/echoes");

    const uint64_t firefly_tasks[] = {FIREFLY_ESCAPE_TASK, FIREFLY_CAPTURE_TASK};
    for (unsigned task_index=0; task_index<sizeof(firefly_tasks)/sizeof(firefly_tasks[0]); ++task_index) {
    for (unsigned scenario=0; scenario<10; ++scenario) {
        prepare_prologue_failure();test_mission=27;test_task=firefly_tasks[task_index];
        shared->allowed=1<<27;effects_task_started(test_task,27);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed && !test_death.dead);
        uintptr_t caller=base+0x235c9ae;uint64_t fail=UINT64_C(0xef0166791679f92d);
        if(scenario==1)caller=base+0x235cb34;
        if(scenario==2)test_task=TEST_SID;
        if(scenario==3){engine_in_menu=true;update_death_link();}
        if(scenario==4){shared->allowed=0;update_death_link();}
        if(scenario==5){shared->heartbeat=GetTickCount64()-6000;update_death_link();}
        if(scenario==6){effects_task_started(test_task,27);} /* Restart alone emits nothing. */
        if(scenario==7){death.remote=true;death.receipt=4801;}
        if(scenario==8){test_mission=26;shared->allowed=1<<26;} /* Same task in a different mission is excluded. */
        if(scenario==9)fail=TEST_SID; /* Success/unrelated events do not count. */
        observe_script_failure(fail,caller);observe_script_failure(fail,caller);
        assert(shared->death_local==(scenario==0));assert(shared->death_remote==(scenario==7));
        if(scenario==0){
            update_death_link();assert(shared->death_local==1 && death.script_failed);
            effects_task_started(test_task,27);assert(!death.script_failed && shared->death_local==1);
            update_death_link();death.since=GetTickCount64()-1100;update_death_link();
            observe_script_failure(fail,caller);assert(shared->death_local==2);
        }
    }
    }
    puts("PASS: Firefly Lab escape gunfire and capture variants sends once, resets on checkpoint and excludes unrelated failures/restarts/echoes");

    for (unsigned linked=0; linked<2; ++linked) {
        prepare_prologue_failure();test_mission=13;test_task=PITTSBURGH_ELLIE_TASK;
        shared->allowed=1<<13;effects_task_started(test_task,13);
        shared->death_enabled=linked ? 17 : 0;
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        assert(death.armed);
        LONG start=shared->write;
        scripted_bite();scripted_bite();
        unsigned cleared=0;
        for(LONG i=start;i<shared->write;i++)if(shared->events[i % AP_EVENTS].type==AP_EVENT_PLAYER_DEATH)++cleared;
        assert(cleared==1 && shared->death_local==linked);
        update_airhorn();assert(!shared->airhorn_ready);
        effects_task_started(test_task,13);
        update_death_link();death.since=GetTickCount64()-1100;update_death_link();
        start=shared->write;test_death.dead=true;
        update_death_link();update_death_link();
        cleared=0;for(LONG i=start;i<shared->write;i++)if(shared->events[i % AP_EVENTS].type==AP_EVENT_PLAYER_DEATH)++cleared;
        assert(cleared==1 && shared->death_local==2*linked);
    }
    puts("PASS: confirmed scripted and natural deaths clear traps once with DeathLink on or off; failed actor cannot emit horns");

    prepare_supplies();
    has_test_collectible=fake_has_collectible;give_test_collectible=fake_collectible;
    test_owned=test_grants=0;
    assert(command(8,(4<<8),5001)==1 && test_owned==1 && test_grants==1);
    assert(command(8,(4<<8),5002)==1 && test_grants==1);
    assert(command(8,255|(4<<8),5003)==4);
    test_inventory.shivs=1;test_inventory.kits=0;
    assert(command(9,3|(4<<8),5010)==1 && test_inventory.shivs==3);
    assert(command(10,3|(4<<8),5011)==1 && test_inventory.kits==3);
    int fills=supply_effects;
    assert(command(9,3|(4<<8),5012)==1 && supply_effects==fills);
    test_inventory.shiv_max=0;assert(command(9,3|(4<<8),5013)==2);
    assert(command(10,2|(4<<8),5014)==4);
    assert(command(10,3|(5<<8),5015)==2);
    test_inventory.ready=false;assert(command(8,(4<<8),5016)==2);
    test_inventory.ready=true;shared->mode=2;shared->allowed=0;
    assert(command(8,(4<<8),5017)==2);
    puts("PASS: test collectible grants, duplicate suppression, supply capacity, scene/character validation");
    prepare_supplies();
    for (int i = 0; i < 8; ++i) test_inventory.resource_max[i] = i < 6 ? 12 : 9999;
    test_inventory.resources[0] = 11; test_inventory.resources[1] = 12;
    test_inventory.ready = false;
    assert(command(11,1|(4<<8),6001)==2);
    test_inventory.ready = true;
    assert(command(11,1|(4<<8),6001)==1);
    assert(test_inventory.resources[0]==12 && test_inventory.resources[1]==12 && test_inventory.resources[2]==4);
    int resource_effects = supply_effects;
    assert(command(11,1|(4<<8),6001)==1 && supply_effects==resource_effects);
    assert(command(101,11,6001)==1 && command(101,12,6001)==4);
    for (int i = 0; i < 6; ++i) test_inventory.resources[i] = 12;
    assert(command(11,1|(4<<8),6002)==2);
    test_inventory.resources[0]=0;
    assert(command(11,1|(4<<8),6002)==1 && test_inventory.resources[0]==4);
    test_inventory.resources[6]=9990;
    assert(command(12,1|(4<<8),6003)==1 && test_inventory.resources[6]==9999);
    assert(command(13,1|(4<<8),6004)==1 && test_inventory.resources[7]==10);
    assert(command(13,2|(4<<8),6005)==4);
    for (int i = 0; i < 6; ++i) test_inventory.resources[i]=0;
    partial_ammo=true;
    assert(command(11,1|(4<<8),6006)==3);
    resource_effects=supply_effects;
    assert(command(11,1|(4<<8),6006)==3 && supply_effects==resource_effects);
    partial_ammo=false;
    puts("PASS: crafting quarters, resource caps/full queues, duplicate receipts and uncertain partial batches");

    prepare_supplies(); shared->mode=2; shared->airhorn_ready=1;
    shared->effect_supported=shared->effect_mask=3;
    shared->effect_lease=GetTickCount64(); shared->effect_until[0]=30000; shared->effect_until[1]=90000;
    update_timed_effects(50,true);
    assert(shared->effect_clock[0]==50 && shared->effect_clock[1]==50);
    engine_in_menu=true; update_timed_effects(50,true); assert(shared->effect_clock[0]==50);
    engine_in_menu=false; shared->airhorn_ready=0; update_timed_effects(50,true); assert(shared->effect_clock[1]==50);
    shared->airhorn_ready=1; shared->allowed=0; update_timed_effects(50,true); assert(shared->effect_clock[0]==50);
    shared->allowed=8; shared->effect_lease=GetTickCount64()-2000;
    update_timed_effects(50,true); assert(shared->effect_clock[0]==50);
    shared->effect_lease=GetTickCount64(); shared->effect_clock[0]=29990;
    update_timed_effects(50,true); assert(shared->effect_clock[0]==30000 && !effect_enabled(0));
    assert(effect_enabled(1)); shared->effect_mask=0; assert(!effect_enabled(1));
    for (unsigned i=0;i<30000;++i) assert(flashlight_factor(i)>=.079f && flashlight_factor(i)<=1.001f);
    puts("PASS: independent effect clocks, menu/cutscene/lock/disconnect suspension, exact expiry and bounded dimming");
    /* Exercise the actual VEX trampoline, not just the effect arithmetic. */
    unsigned char aim_code[] = {0xc5,0xfa,0x10,0x59,0x18, /* vmovss xmm3,[rcx+18] */
        0xc5,0xfa,0x11,0x1a, /* vmovss [rdx],xmm3 */
        0x48,0x89,0xd0,0xc3}; /* mov rax,rdx; ret */
    void *aim_page=VirtualAlloc(NULL,4096,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
    assert(aim_page); memcpy(aim_page,aim_code,sizeof(aim_code));
    assert(MH_Initialize()==MH_OK);
    assert(MH_CreateHook(aim_page,(void *)hook_aim_offset,(void **)&original_aim_offset)==MH_OK);
    assert(MH_EnableHook(aim_page)==MH_OK);
    float aim_input[16]={0},aim_output[2]={0}; aim_input[6]=17.25f;
    assert(((float *(*)(void *,float *))aim_page)(aim_input,aim_output)==aim_output);
    assert(aim_output[0]==17.25f);
    /* Reproduce game caller 0x199bb38: keep the output pointer in R8 across
     * the leaf call, then write through it. Standard-ABI tests miss this. */
    unsigned char leaf_caller[] = {0x48,0x83,0xec,0x28,0x49,0x89,0xd0,
        0x48,0xb8,0,0,0,0,0,0,0,0,0xff,0xd0,
        0x4c,0x89,0xc0,0x48,0x83,0xc4,0x28,0xc3};
    memcpy(leaf_caller+9,&aim_page,8);
    memcpy((char *)aim_page+128,leaf_caller,sizeof(leaf_caller));
    assert(((float *(*)(void *,float *))((char *)aim_page+128))(aim_input,aim_output)==aim_output);
    assert(MH_DisableHook(aim_page)==MH_OK);
    /* The scoped getter mutates RCX before returning. The wrapper must retain
     * the original controller, while preserving the native volatile results. */
    unsigned char scope_code[] = {0x48,0x83,0xec,0x28,0x48,0x81,0xc1,0xe8,0x06,0,0,
        0xf2,0x0f,0x10,0x01,0xf2,0x0f,0x11,0x02,0x48,0x89,0xd0,
        0x48,0x83,0xc4,0x28,0xc3};
    void *scope_page=VirtualAlloc(NULL,4096,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
    assert(scope_page); memcpy(scope_page,scope_code,sizeof(scope_code));
    assert(MH_CreateHook(scope_page,(void *)hook_scope_sway,(void **)&original_scope_sway)==MH_OK);
    assert(MH_EnableHook(scope_page)==MH_OK);
    unsigned char *scope_player=calloc(1,0x3400), *scope_aim=calloc(1,0x800);
    assert(scope_player && scope_aim);
    *(uintptr_t *)(scope_player+0x3098)=(uintptr_t)scope_aim;
    *(uintptr_t *)(scope_aim+8)=(uintptr_t)scope_player;
    *(float *)(scope_aim+0x6e8)=2.0f; *(float *)(scope_aim+0x6ec)=3.0f;
    test_death.player=scope_player;
    shared->effect_mask=1; shared->effect_clock[0]=1000; shared->effect_until[0]=60000;
    shared->effect_lease=shared->heartbeat=GetTickCount64();
    float scope_out[2];
    assert(((float *(*)(void *,float *,void *))scope_page)(scope_aim,scope_out,NULL)==scope_out);
    assert(scope_out[0]==2 && scope_out[1]==3); /* not zoomed */
    scope_aim[0x698]=1;
    ((float *(*)(void *,float *,void *))scope_page)(scope_aim,scope_out,NULL);
    assert(scope_out[0]!=2 && scope_out[1]!=3);
    float scoped_x=scope_out[0],scoped_y=scope_out[1];
    ((float *(*)(void *,float *,void *))scope_page)(scope_aim,scope_out,NULL);
    assert(scope_out[0]==scoped_x && scope_out[1]==scoped_y); /* no accumulation */
    *(uintptr_t *)aim_input=(uintptr_t)scope_player;
    *(uintptr_t *)(scope_player+0x3380)=(uintptr_t)aim_input;
    aim_output[0]=2;aim_output[1]=3;apply_aim_offset(aim_input,aim_output);
    assert(aim_output[0]==2 && aim_output[1]==3); /* no double reticle sway */
    engine_in_menu=true;
    ((float *(*)(void *,float *,void *))scope_page)(scope_aim,scope_out,NULL);
    assert(scope_out[0]==2 && scope_out[1]==3);
    engine_in_menu=false;shared->effect_mask=0;
    ((float *(*)(void *,float *,void *))scope_page)(scope_aim,scope_out,NULL);
    assert(scope_out[0]==2 && scope_out[1]==3);
    assert(*(float *)(scope_aim+0x6e8)==2 && *(float *)(scope_aim+0x6ec)==3);
    assert(MH_DisableHook(scope_page)==MH_OK); assert(MH_Uninitialize()==MH_OK);
    VirtualFree(scope_page,0,MEM_RELEASE);free(scope_player);free(scope_aim);
    puts("PASS: scoped camera detour, no double sway/accumulation, menu suspension and recovery");
    VirtualFree(aim_page,0,MEM_RELEASE);
    puts("PASS: real MinHook VEX entry detour preserves VMOVSS and return value while effects are disabled");
    prepare_supplies();
    *(uintptr_t *)(base + 0x48a6ee8) = (uintptr_t)tool_manager;
    original_pickup = fake_tool_pickup;
    assert(native_tool_level() == 0);
    assert(command(7, 1 | (4 << 8), 3000) == 1 && native_tool_level() == 1 && tool_grants == 1);
    assert(command(7, 1 | (4 << 8), 3000) == 1 && tool_grants == 1);
    assert(command(7, 5 | (4 << 8), 3001) == 1 && native_tool_level() == 5 && tool_grants == 5);
    assert(command(7, 5 | (4 << 8), 3002) == 1 && tool_grants == 5);
    assert(command(7, 6 | (4 << 8), 3003) == 4);
    memset(tool_manager, 0, sizeof(tool_manager));
    assert(command(7, 5 | (4 << 8), 3001) == 1 && native_tool_level() == 5 && tool_grants == 10);
    puts("PASS: tool floors use native pickup, cap at five, deduplicate repeats and restore after reload");
    memset(tool_manager, 0, sizeof(tool_manager));
    test_inventory.ready = false;
    assert(command(7, 1 | (4 << 8), 3004) == 2 && tool_grants == 10);
    test_inventory.ready = true; shared->allowed = 0;
    assert(command(7, 1 | (4 << 8), 3004) == 2 && tool_grants == 10);
    shared->allowed = 8;
    assert(command(7, 1 | (5 << 8), 3004) == 2 && tool_grants == 10);
    test_inventory.shiv_max = 0;
    assert(command(7, 1 | (4 << 8), 3004) == 2 && tool_grants == 10);
    test_inventory.shiv_max = 3;
    ((uint64_t *)tool_manager)[0] = tool_sids[2];
    *(uint32_t *)(tool_manager + 0xc50) = 1;
    assert(native_tool_level() == -1);
    assert(command(7, 1 | (4 << 8), 3004) == 2 && tool_grants == 10);
    puts("PASS: tool grants wait during nonplayable, locked, wrong mission, Ellie and invalid inventory states");
    free((void *)base);
    free(shared);
    return 0;
}
