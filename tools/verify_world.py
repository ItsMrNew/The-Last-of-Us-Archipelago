"""Validate the packaged world in an isolated official Archipelago checkout.

Usage: python tools/verify_world.py .deps/ArchipelagoTest
Copies only our .apworld into that checkout's custom_worlds folder.
"""
import itertools
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest  # Enables AP's limited test-world loader before AP is imported.

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) != 2:
    raise SystemExit(__doc__)
ap = Path(sys.argv[1]).resolve()
if not (ap / 'BaseClasses.py').is_file():
    raise SystemExit('Expected an official Archipelago source checkout')
os.environ['SKIP_REQUIREMENTS_UPDATE'] = '1'
os.environ['AP_TEST_WORLDS'] = 'tlou_part1'
target = ap / 'custom_worlds'
target.mkdir(exist_ok=True)
shutil.copyfile(ROOT / 'dist/tlou_part1.apworld', target / 'tlou_part1.apworld')
sys.path.insert(0, str(ap))
sys.path.insert(0, str(ROOT))

from BaseClasses import CollectionState
from Fill import distribute_items_restrictive
from test.general import setup_multiworld
from worlds import failed_world_loads
from worlds.tlou_part1.world import TLOUWorld
from worlds.tlou_part1.catalog import Config, MISSIONS, PROGRESSIVE_CHAPTER
from Generate import roll_settings
from Utils import parse_yaml, __version__
from tlou_ap.catalog import AIRHORN, ITEM_IDS, PROGRESSIVE_TOOLS
from tlou_ap.session import Session, ReceivedItem
from tlou_ap.tracker import snapshot

assert not failed_world_loads, failed_world_loads
rolled = roll_settings(parse_yaml((ROOT / 'templates/The Last of Us Part I.yaml').read_text(encoding='utf-8')))
assert rolled.game == TLOUWorld.game
assert rolled.starting_chapters.value == 2


def validate(options, seed):
    mw = setup_multiworld(TLOUWorld, seed=seed, options=options)
    world = mw.worlds[1]
    network_locations = [loc for loc in mw.get_locations() if loc.address is not None]
    assert len(network_locations) == len(mw.itempool) == len(world.config.active_checks)
    assert {loc.address for loc in network_locations} == {c.id for c in world.config.active_checks}
    assert sum(i.name == PROGRESSIVE_CHAPTER for i in mw.itempool) == 12 - world.config.starting_chapters
    tool_count = min(world.config.progressive_tools, len(mw.itempool) - (12 - world.config.starting_chapters))
    assert sum(i.name == PROGRESSIVE_TOOLS for i in mw.itempool) == tool_count
    assert all(i.useful and not i.trap for i in mw.itempool if i.name == PROGRESSIVE_TOOLS)
    filler_count = len(mw.itempool) - (12 - world.config.starting_chapters) - tool_count
    assert sum(i.name == AIRHORN for i in mw.itempool) == filler_count * world.config.airhorn_trap_percentage // 100
    assert all(i.trap and not i.advancement for i in mw.itempool if i.name == AIRHORN)
    state = CollectionState(mw)
    with tempfile.TemporaryDirectory(prefix='tlou-logic-test-') as folder:
        session = Session(folder, str(seed), 0, 1, 'logic-test', world.config)
        for permitted in range(world.config.starting_chapters, 13):
            state.sweep_for_advancements()
            for mission in MISSIONS:
                reachable = state.can_reach(f"Mission {mission['index'] + 1}: {mission['name']}", 'Region', 1)
                assert reachable == (mission['chapter'] < permitted), (options, permitted, mission)
            received = permitted - world.config.starting_chapters
            session.record_inventory([ReceivedItem(ITEM_IDS[PROGRESSIVE_CHAPTER], i, 1, 1) for i in range(received)])
            view = snapshot(session, (), connected=True, synchronized=True)
            actual = {loc.address for loc in network_locations if loc.can_reach(state)}
            assert {r.id for r in view.checks if r.in_logic} == actual, ('Tracker differs from AP logic', options, permitted)
            if permitted < 12:
                state.collect(world.create_item(PROGRESSIVE_CHAPTER), prevent_sweep=True)
    distribute_items_restrictive(mw)
    assert not mw.get_unfilled_locations()
    assert mw.can_beat_game(), (options, seed)
    assert mw.fulfills_accessibility(), (options, seed)


tested = 0
for start in range(1, 13):
    for mission, chapter, collectible in itertools.product((False, True), repeat=3):
        options = dict(starting_chapters=start, mission_checks=mission, chapter_checks=chapter,
                       collectible_checks=collectible)
        try:
            Config(**options)
        except ValueError:
            try:
                setup_multiworld(TLOUWorld, options=options)
            except ValueError:
                continue
            raise AssertionError(f'Invalid configuration accepted: {options}')
        validate(options, 1000 + tested)
        tested += 1
print(f'Archipelago {__version__}: all {tested} valid option combinations filled, beatable and accessible; tracker logic matches every unlock stage')
for seed in range(5):
    validate({}, seed)
    validate({'death_link': True}, seed)
print('Default and DeathLink options: five additional seeds each pass')
for percent, mode, duration in itertools.product((0, 1, 10, 50, 100), (0, 1), (30, 60, 120)):
    validate({'airhorn_trap_percentage': percent, 'airhorn_mode': mode,
              'airhorn_duration': duration}, 12000 + percent + mode + duration)
print('Airhorn: 30 percentage/mode/duration combinations pass; trap flags and pool counts verified')
mw = setup_multiworld([TLOUWorld, TLOUWorld], seed=1130,
                     options=[{'starting_chapters': 1, 'collectible_checks': False},
                              {'starting_chapters': 3, 'mission_checks': False}])
distribute_items_restrictive(mw)
assert mw.can_beat_game() and mw.fulfills_accessibility()
print('Two-player mixed-options world passes; sample YAML rolls successfully')

from BaseClasses import ItemClassification
from tlou_ap.catalog import RESOURCE_SUPPLIES, TIMED_TRAPS
for options in (
    {'resource_supplies': True, 'airhorn_trap_percentage': 10, 'shaky_hands_percentage': 20, 'faulty_flashlight_percentage': 30},
    {'resource_supplies': False, 'airhorn_trap_percentage': 0, 'shaky_hands_percentage': 100},
    {'resource_supplies': True, 'airhorn_trap_percentage': 0, 'faulty_flashlight_percentage': 100},
    {'resource_supplies': False, 'airhorn_trap_percentage': 0},
):
    validate(options, 3900)
    mw = setup_multiworld(TLOUWorld, seed=3900, options=options)
    w = mw.worlds[1]
    count = len(w.config.active_checks) - (12 - w.config.starting_chapters)
    count -= min(w.config.progressive_tools, count)
    for name, key in zip(TIMED_TRAPS, ('shaky_hands_percentage', 'faulty_flashlight_percentage')):
        assert sum(i.name == name for i in mw.itempool) == count * getattr(w.config, key) // 100
        assert w.create_item(name).classification == ItemClassification.trap
    for name in RESOURCE_SUPPLIES:
        assert w.create_item(name).classification == ItemClassification.useful
    if not options['resource_supplies']:
        assert not any(i.name in RESOURCE_SUPPLIES for i in mw.itempool)
try:
    setup_multiworld(TLOUWorld, options={'airhorn_trap_percentage': 50, 'shaky_hands_percentage': 51})
except ValueError:
    pass
else:
    raise AssertionError('Accepted combined trap percentage over 100')
print('Resource supplies and both timed traps: generation, classification, exact counts, caps and reachability pass')

for count in (0, 1, 5):
    for percent in (0, 40, 100):
        validate({'progressive_tools': count, 'resource_supplies': True, 'airhorn_trap_percentage': 0, 'shaky_hands_percentage': percent}, 40000+count+percent)
print('PASS: combined resource/trap/tool pool generation')
