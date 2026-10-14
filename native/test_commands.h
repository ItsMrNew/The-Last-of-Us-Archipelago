/* Explicit developer actions, dispatched on the same game thread as supplies. */
#include "test_collectibles.h"
static int native_has_test_collectible(uint64_t sid) {
    uintptr_t manager=0;uint32_t count=0;uint64_t items[350];
    if(!read_local(base+0x48a6ee8,&manager,8)||!manager||
       !read_local(manager+0xc50,&count,4)||count>350||
       (count&&!read_local(manager,items,count*8)))return -1;
    for(uint32_t i=0;i<count;++i)if(items[i]==sid)return 1;
    return count<350?0:-1;
}
static void native_test_collect(uint64_t sid) {
    uintptr_t manager=0;
    if(read_local(base+0x48a6ee8,&manager,8)&&manager)
        original_pickup((void*)manager,sid,true,true);
}
static int (*has_test_collectible)(uint64_t)=native_has_test_collectible;
static void (*give_test_collectible)(uint64_t)=native_test_collect;
static int execute_test_command(int type,int argument,int expected_mission,uint64_t receipt) {
    if(!receipt || (type==8 ? (unsigned)argument>=sizeof(test_collectibles)/sizeof(test_collectibles[0]) : argument!=3))return 4;
    int mission=read_active_mission();Supplies before,after;
    if(mission<2||mission!=expected_mission||!permitted(mission)||shared->pending||
       !read_supplies(&before)||!before.ready||
       !supply_stage_ready(mission,read_active_task(),&before,GetTickCount64()))return 2;
    if(type==8){
        uint64_t sid=test_collectibles[argument];
        int owned=has_test_collectible(sid);
        if(owned<0)return 2;
        if(!owned)give_test_collectible(sid);
        /* Inventory presence, not merely a hook, confirms the actual grant. */
        return has_test_collectible(sid)==1?1:3;
    }
    int count=type==9?before.shivs:before.kits;
    int maximum=type==9?before.shiv_max:before.kit_max;
    if(maximum!=3||count<0||count>3)return 2;
    if(count==3)return 1;
    apply_supply(type==9?5:2,3-count,&before);
    if(!read_supplies(&after)||after.player!=before.player||after.inventory!=before.inventory)return 3;
    publish_supplies(&after);
    return (type==9?after.shivs:after.kits)==3?1:3;
}
