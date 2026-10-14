"""Exercise two clients against the official AP server in an isolated test room.

The adapters are fixtures; this script never opens the game or the live run.
"""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import functools
import json
import os
from pathlib import Path
import shutil
import sys
import unittest  # Official AP restricted world loader.

ROOT = Path(__file__).resolve().parents[1]
AP = ROOT / '.deps/ArchipelagoTest'
OUTPUT = ROOT / '.research' / ('notification-room-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
OUTPUT.mkdir(parents=True)
players = OUTPUT / 'players'
players.mkdir()
yaml = (ROOT / 'templates/The Last of Us Part I.yaml').read_text(encoding='utf-8')
yaml = yaml.replace('starting_chapters: 2', 'starting_chapters: 12').replace('collectible_checks: true', 'collectible_checks: false').replace('shaky_hands_percentage: 0', 'shaky_hands_percentage: 20').replace('faulty_flashlight_percentage: 0', 'faulty_flashlight_percentage: 20')
for name in ('SenderTest', 'ReceiverTest'):
    (players / (name + '.yaml')).write_text(yaml.replace('name: Survivor', 'name: ' + name), encoding='utf-8')
os.environ.update(SKIP_REQUIREMENTS_UPDATE='1', AP_TEST_WORLDS='tlou_part1')
sys.path[:0] = [str(AP), str(ROOT)]
shutil.copyfile(ROOT / 'dist/tlou_part1.apworld', AP / 'custom_worlds/tlou_part1.apworld')
os.chdir(AP)
import Generate
from Main import main
import MultiServer
from Utils import __version__
from websockets.legacy.server import serve
from tlou_ap.client import Client, REQUIRED_CAPABILITIES

rolled, seed = Generate.main(Generate.mystery_argparse([
    '--player_files_path', str(players), '--multi', '2', '--seed', '2026101202',
    '--spoiler', '0', '--outputpath', str(OUTPUT)]))
main(rolled, seed)


class FixtureAdapter:
    capabilities = REQUIRED_CAPABILITIES | {'airhorn', 'timed_effects', 'resources'}

    def __init__(self, name):
        self.run_id, self.armed = 'notification-fixture-' + name, False

    def set_gate(self, session): pass
    def bind(self, identity, resume): pass
    def can_deliver(self, item): return False

    def airhorn_status(self): return dict(instance=self.run_id, clock=0, ready=False)
    def airhorn_pulse(self, *args, **kwargs): return 'not_applied'
    def timed_effect_status(self): return dict(instance=self.run_id, clocks=[0,0], ready=False, supported=3)
    def set_timed_effects(self, remaining): pass

    def observe(self, session):
        if self.armed and len(session.data['missions']) < 29:
            session.complete_mission(len(session.data['missions']))


async def verify():
    ctx = MultiServer.Context('127.0.0.1', 0, None, None, 1, 10, False)
    ctx.load(str(next(OUTPUT.glob('*.zip'))))
    ctx.init_save(False)
    adapters = [FixtureAdapter(name) for name in ('SenderTest', 'ReceiverTest')]
    notifications = [[], []]
    clients = [Client(name, OUTPUT / ('client-' + str(i)), adapters[i], notify=notifications[i].append)
               for i, name in enumerate(('SenderTest', 'ReceiverTest'))]
    async with serve(functools.partial(MultiServer.server, ctx=ctx), '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        tasks = [asyncio.create_task(client.connect(f'127.0.0.1:{port}')) for client in clients]
        try:
            async with asyncio.timeout(25):
                while not all(client.connected and client.inventory.synchronized for client in clients):
                    if any(task.done() for task in tasks):
                        await asyncio.gather(*tasks)
                    await asyncio.sleep(.05)
                for adapter in adapters:
                    adapter.armed = True
                while not all(len(client.session.data['missions']) == 29 and len(client.checked) == 41 for client in clients):
                    if any(task.done() for task in tasks):
                        await asyncio.gather(*tasks)
                    await asyncio.sleep(.05)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    for toasts in notifications:
        assert all(not toast.item.startswith('Item #') for toast in toasts)
        from tlou_ap.catalog import RESOURCE_SUPPLIES, TIMED_TRAPS, PROGRESSIVE_TOOLS, AIRHORN
        from tlou_ap.notifications import item_colour
        for toast in toasts:
            flags = 4 if toast.item in (*TIMED_TRAPS, AIRHORN) else 2 if toast.item in (*RESOURCE_SUPPLIES, PROGRESSIVE_TOOLS) else 0
            assert toast.colour == item_colour(flags), (toast, flags)
        assert {'ITEM SENT','ITEM RECEIVED'} <= {t.heading for t in toasts}
    report = {'recorded_utc': datetime.now(timezone.utc).isoformat(), 'archipelago_version': __version__,
              'seed': ctx.seed_name, 'isolation': 'Local ephemeral port, fixture adapters; no native game access',
              'both_clients_sent_and_received': True,
              'notifications': [[asdict(toast) for toast in toasts] for toasts in notifications]}
    (OUTPUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('PASS: both clients displayed named incoming and outgoing items from official AP', __version__)
    print('Evidence:', OUTPUT / 'result.json')


asyncio.run(verify())
