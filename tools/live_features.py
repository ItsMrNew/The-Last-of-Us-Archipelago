"""Isolated native/AP feature lab. Requires the imported TEST SAVE PACK.

Runs an official AP server on an ephemeral localhost port and a test peer.
The story prefix is a fixture, NOT earned campaign progress. LocationChecks
and goals are suppressed. Never opens the real run/session directory.
Commands in control.json: unlock, death, duplicate, hold, release, stop.
"""
import asyncio
from dataclasses import asdict
from datetime import datetime
import functools
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
AP = ROOT / '.deps/ArchipelagoTest'
OUT = ROOT / '.research' / ('features-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
OUT.mkdir(parents=True)
assert (ROOT / '.state/save-pack-active.json').exists(), 'Only use isolated test saves'
os.environ.update(SKIP_REQUIREMENTS_UPDATE='1', AP_TEST_WORLDS='tlou_part1')
sys.path[:0] = [str(AP), str(ROOT)]
shutil.copyfile(ROOT / 'dist/tlou_part1.apworld', AP / 'custom_worlds/tlou_part1.apworld')
os.chdir(AP)
import Generate
from Main import main
import MultiServer
from websockets.legacy.server import serve
from tlou_ap.catalog import Config, GAME, MISSIONS
from tlou_ap.client import Client, REQUIRED_CAPABILITIES
from tlou_ap.launcher import game_pid
from tlou_ap.native.bridge import Bridge, validate_gate_build
from tlou_ap.native.deathlink import NativeDeathLink
from tlou_ap.notifications import mission_lock_toast
from tlou_ap.overlay import NotificationOverlay
from tlou_ap.session import atomic_json
from tools.offline_lab import LAB_OWNER, ALL

logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler(OUT/'client.log', encoding='utf-8')])
players = OUT/'players'; players.mkdir()
yaml = (ROOT/'templates/The Last of Us Part I.yaml').read_text(encoding='utf-8')
yaml = yaml.replace('starting_chapters: 2', 'starting_chapters: 1').replace('death_link: false','death_link: true')
for name in ('NativeTest', 'PeerTest'):
    (players/(name+'.yaml')).write_text(yaml.replace('name: Survivor','name: '+name),encoding='utf-8')
rolled, seed = Generate.main(Generate.mystery_argparse(['--player_files_path',str(players),
    '--multi','2','--seed','2026101218','--spoiler','0','--outputpath',str(OUT)]))
main(rolled,seed)


class LabClient(Client):
    async def send(self, socket, *packets):
        # These ledgers contain fixture prerequisites, never earned checks.
        packets = [p for p in packets if p['cmd'] not in ('LocationChecks','StatusUpdate')]
        if packets:
            await super().send(socket, *packets)


class LabAdapter:
    capabilities = REQUIRED_CAPABILITIES | {'death_link'}
    run_id = 'isolated-native-features'

    def __init__(self, bridge):
        self.bridge = bridge
        self.deathlink = NativeDeathLink(bridge)
        self.hold = None
        self.release_all = False
        self.local_override = False

    def bind(self, identity, resume): pass
    def can_deliver(self, item): return False
    def set_gate(self, session):
        b = self.bridge
        b.heartbeat()
        allowed = sum(1 << i for i in range(29) if session.can_start(i)) if session else 0
        if self.release_all: allowed = ALL
        if self.hold is not None: allowed &= ~(1 << self.hold)
        b.shared.allowed = allowed
        b.shared.mode = 2

    def observe(self, session):
        b = self.bridge
        if not b.is_alive(): raise RuntimeError('Test game closed')
        if b.shared.error: raise RuntimeError(str(b.status()))
        # Clearly isolated prerequisites let a test save reach its current mission.
        current = b.shared.current - 1
        session.data['missions'] = list(range(max(0, current)))
        for event in b.events():
            with (OUT/'events.jsonl').open('a') as stream:
                stream.write(json.dumps(event)+'\n')
            b.acknowledge(event['sequence'])

    def configure_death_link(self, enabled): self.deathlink.configure(enabled)
    def death_link_dead(self): return self.bridge.shared.death_state in (1, 3)
    def poll_death_link(self): return self.deathlink.poll()
    def deliver_death_link(self, receipt, *, before_submit):
        return self.deathlink.deliver(receipt, before_submit=before_submit)
    def clear_death_link_command(self): self.deathlink.clear_finished()
    def after_poll(self):
        if not self.bridge.command_busy and not self.deathlink.command:
            self.bridge.begin_command(100)


async def run():
    from websockets.legacy.client import connect
    bridge = Bridge(game_pid(), ROOT/'dist/native')
    validate_gate_build(bridge.manifest['build_id'], experimental=True)
    bridge.attach()
    if bridge.shared.reserved not in (0, LAB_OWNER): raise RuntimeError('Real run owns this process')
    bridge.shared.reserved = LAB_OWNER
    adapter = LabAdapter(bridge)
    ctx = MultiServer.Context('127.0.0.1',0,None,None,1,10,False)
    ctx.load(str(next(OUT.glob('*.zip'))));ctx.init_save(False)
    root = tk.Tk(); root.withdraw()
    overlay = NotificationOverlay(root); overlay.pid = bridge.pid
    notices=[]
    def notify(toast):
        notices.append(asdict(toast)); overlay.add(toast)
        atomic_json(OUT/'notices.json', notices)
    client = LabClient('NativeTest', OUT/'sessions', adapter, notify=notify)
    tasks=[]; last_id=None; last_death=None; peer_packets=[]; s=None
    atomic_json(ROOT/'.research/active-features.json', {'folder':str(OUT),'pid':bridge.pid})
    try:
        async with serve(functools.partial(MultiServer.server,ctx=ctx),'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            tasks.append(asyncio.create_task(client.connect(f'127.0.0.1:{port}')))
            async with connect(f'ws://127.0.0.1:{port}') as peer:
                await peer.recv()
                await peer.send(json.dumps([{'cmd':'Connect','game':GAME,'name':'PeerTest','password':None,
                    'uuid':'isolated-peer','version':{'major':0,'minor':6,'build':9,'class':'Version'},
                    'items_handling':7,'tags':['AP','DeathLink'],'slot_data':True}]))
                async def peer_read():
                    async for raw in peer:
                        peer_packets.extend(json.loads(raw))
                        atomic_json(OUT/'peer-packets.json', peer_packets)
                tasks.append(asyncio.create_task(peer_read()))
                while True:
                    for task in tasks:
                        if task.done(): await task
                    bridge.heartbeat()
                    path=OUT/'control.json'
                    if path.exists():
                        # Shell writers may briefly expose an empty/partial file.
                        try:
                            command=json.loads(path.read_text())
                        except (OSError, ValueError):
                            command={}
                        if isinstance(command, dict) and command.get('id') is not None and command['id'] != last_id:
                            last_id=command['id']; kind=command['command']
                            if kind=='stop': break
                            if kind=='unlock':
                                assert MultiServer.ServerCommandProcessor(ctx)('/send NativeTest Progressive Chapter Unlock')
                            elif kind=='death':
                                last_death={'cmd':'Bounce','tags':['DeathLink'],'data':{'time':time.time(),
                                    'source':'PeerTest','cause':'PeerTest died in the isolated DeathLink test.'}}
                                await peer.send(json.dumps([last_death]))
                            elif kind=='duplicate': await peer.send(json.dumps([last_death]))
                            elif kind=='hold': adapter.hold=command['mission'];adapter.release_all=True
                            elif kind=='release': adapter.hold=None;adapter.release_all=True
                            with (OUT/'actions.jsonl').open('a') as stream:
                                stream.write(json.dumps({'time':time.time(),**command})+'\n')
                    s=bridge.shared
                    card = None
                    if s.blocked:
                        mission=MISSIONS[s.blocked-1]
                        card=mission_lock_toast(mission['name'])
                    overlay.state(bridge.pid, status_card=card);overlay.refresh();root.update()
                    atomic_json(OUT/'status.json',{'time':time.time(),'pid':bridge.pid,'bridge':bridge.status(),
                        'build_id':f'{s.build_id:016x}','pending_gate':s.pending,'supplies':bridge.supplies(),
                        'death_state':s.death_state,'death_enabled':bool(s.death_enabled),
                        'local_deaths':s.death_local,'remote_deaths':s.death_remote,
                        'pending_death':client.deathlink.pending,'death_sent':client.deathlink.sent,
                        'connected':client.connected,'unlocked':len(client.session.unlocked) if client.session else 0,
                        'isolation':'Test saves, fixture story prerequisites, no checks/goals, private AP server'})
                    await asyncio.sleep(.1)
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        bridge.shared.death_enabled=0;bridge.shared.mode=0
        s=None  # Release the exported ctypes view before closing its mmap.
        try:
            bridge.close()
        finally:
            overlay.close();root.destroy()


asyncio.run(run())
