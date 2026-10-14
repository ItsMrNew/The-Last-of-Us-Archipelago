"""Distribution smoke test; optional read-only room greeting, never a game/run."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import traceback

from websockets.legacy.server import serve
from .client import open_server

from .catalog import Config, COLLECTIBLES, MISSIONS
from .deathlink import DeathLink
from .airhorn import Airhorn
from .native.adapter import TASK_PROFILE
from .native.bridge import validate_gate_build
from .session import Session, atomic_json
from .tracker import snapshot
from .tracker_ui import TrackerWindow
from .version import CLIENT_VERSION


async def network_test():
    async def echo(socket):
        async for message in socket:
            await socket.send(message)
    async with serve(echo, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with open_server(f'ws://127.0.0.1:{port}') as (socket, _):
            await socket.send('[{"cmd":"Sync"}]')
            assert json.loads(await socket.recv()) == [{'cmd': 'Sync'}]


async def room_test(address):
    async with open_server(address) as (socket, resolved):
        packets = json.loads(await asyncio.wait_for(socket.recv(), 10))
        assert any(packet.get('cmd') == 'RoomInfo' for packet in packets)
        return {'room_info_received': True, 'encrypted': resolved.startswith('wss://'),
                'tls_verified': bool(socket.transport.get_extra_info('ssl_object')),
                'authenticated': False, 'ap_packets_sent': 0}


def run(output, root, server_address=None, *, experimental=False):
    report = {'passed': False, 'frozen': bool(getattr(sys, 'frozen', False)),
              'python': sys.version.split()[0], 'client_version': CLIENT_VERSION,
              'game_attached': False, 'checks': []}
    try:
        manifest = json.loads((root / 'dist/native/manifest.json').read_text())
        dll = root / 'dist/native' / manifest['dll']
        assert hashlib.sha256(dll.read_bytes()).hexdigest() == manifest['dll_sha256']
        validate_gate_build(manifest['build_id'], experimental=experimental)
        report['experimental_package'] = experimental
        report['native_live_validation'] = 'pending' if experimental else 'admitted'
        from tools.offline_lab import Lab, ROOT as lab_root
        assert Lab and lab_root == root
        report['checks'].append('Offline Test Lab module bundled with correct resource root (not started)')
        assert TASK_PROFILE and len(COLLECTIBLES) == 140 and len(MISSIONS) == 29
        report['checks'].append('Catalog, native profile and DLL hash; experimental admission bypass for package inspection only'
                                if experimental else 'Catalog, native profile, DLL hash and admitted build')
        from .save_progress import NODES, REQUIRED, compatibility_error
        assert len(NODES) == 602 and len(REQUIRED) == 29
        assert not compatibility_error({'completed_tasks': [], 'native_confirmed': []}, (-1,) * 29)
        report['checks'].append('Bundled 602-task save profile and shared progress guard')
        import wave
        with wave.open(str(Path(__file__).parent / 'data/airhorn.wav')) as horn_sound:
            assert horn_sound.getnchannels() == 1 and horn_sound.getnframes() > 1000
        report['checks'].append('Bundled original Airhorn WAV resource')
        from .sound import HornPlayer
        bank = json.loads((Path(__file__).parent / 'data/airhorns/manifest.json').read_text())
        assert len(bank['recordings']) == 5
        recordings = HornPlayer().recordings()
        report['horn_recordings_installed'] = len(recordings)
        assert len(recordings) == 5, 'Selected horn recordings missing from the distribution'
        with tempfile.TemporaryDirectory(prefix='tlou-horn-selftest-') as sound_folder:
            from .sound import scaled_wav
            for i, recording in enumerate(recordings):
                entry = bank['recordings'][i]
                assert hashlib.sha256(recording.read_bytes()).hexdigest() == entry['sha256']
                scaled_wav(recording, Path(sound_folder) / f'{i}.wav', 50)
        report['checks'].append('Horn rotation manifest and installed PCM recordings (no audio playback)')
        asyncio.run(network_test())
        report['checks'].append('Loopback WebSocket connection and packet round trip')
        if server_address:
            report['room_probe'] = asyncio.run(room_test(server_address))
            report['checks'].append('Read-only remote RoomInfo via production connection negotiation; no slot authentication')
        with tempfile.TemporaryDirectory(prefix='tlou-selftest-') as folder:
            session = Session(folder, 'OFFLINE-TEST', 0, 1, 'fixture', Config(death_link=True))
            session.complete_mission(0)
            death = DeathLink(); death.bind(session); death.configure(True)
            death.receive({'tags': ['DeathLink'], 'data': {'source': 'TestPeer', 'time': 123}}, 'Tester')
            resumed = DeathLink(); resumed.bind(session)
            assert resumed.pending == death.pending
            report['checks'].append('DeathLink journal restored in isolated state directory')
            horn = Airhorn(); horn.bind(session); horn.synchronize(); horn.save()
            restored_horn = Airhorn(); restored_horn.bind(session)
            assert restored_horn.data == horn.data
            report['checks'].append('Airhorn journal restored in isolated state directory')
            root_window = tk.Tk(); root_window.withdraw()
            try:
                tracker = TrackerWindow(root_window); tracker.window.withdraw()
                view = snapshot(session, {19711000}, connected=True, synchronized=True)
                tracker.update(view); root_window.update()
                campaign = tracker.campaign
                assert len(campaign.table.get_children()) == 29
                assert sum(len(campaign.table.get_children(iid)) for iid in campaign.table.get_children()) == 181
                assert view.logic_total == 17 and view.available == 1
                campaign.search.set('Drafting Notice'); root_window.update()
                assert campaign.table.get_children() == ('m:3',)
                assert campaign.table.get_children('m:3') == ('c:19713001',)
                assert campaign.table.item('m:3', 'values')[1] == '0/5'
                for mode in ('Dark', 'Light'):
                    tracker.appearance.choice.set(mode); tracker.appearance.change(); root_window.update()
                    assert tracker.appearance.name == mode.lower()
                campaign.reset_filters(); campaign.hide_completed.set(True); campaign.render()
                assert campaign.table.get_children('m:0') == ('c:19712000',)
                assert campaign.table.item('m:0', 'values') == ('Pending sync', '1/2')
                tracker.update(None)
                assert not campaign.table.get_children()
                report['checks'].append('Campaign tree, all 181 checks, mission totals, search, hide completed, pending sync, Light/Dark themes and reset')
                from . import launcher
                import logging
                old_state = launcher.STATE
                handlers = list(logging.getLogger('tlou-ap').handlers)
                try:
                    launcher.STATE = Path(folder) / 'launcher'; launcher.STATE.mkdir()
                    app = launcher.Launcher(root_window)
                    from .notifications import TransferFeed, item_colour
                    from .theme import LIGHT_ITEMS, PALETTES
                    feed = TransferFeed(Path(folder) / 'notifications')
                    feed.connected('OFFLINE-COLOURS', {'team': 0, 'slot': 1,
                        'slot_info': {'2': {'game': 'Unfamiliar Game', 'name': 'Peer'}}})
                    feed.data_package({'data': {'games': {'Unfamiliar Game': {
                        'item_name_to_id': {f'Foreign item {i}': i for i in range(5)}}}}})
                    for i, flag in enumerate((0, 1, 2, 4, None)):
                        feed.receive({'type': 'ItemSend', 'receiving': 2,
                            'item': {'player': 1, 'item': i, 'location': i, 'flags': flag}})
                    for toast in feed.drain():
                        launcher.LOG.info('%s', ''.join(t for t, _ in toast.parts),
                                          extra={'item_parts': toast.parts})
                    app.refresh()
                    for mode in ('Dark', 'Light'):
                        app.appearance.choice.set(mode); app.appearance.apply()
                        for i, flag in enumerate((0, 1, 2, 4, None)):
                            colour = item_colour(flag)
                            ranges = app.output.tag_ranges(colour)
                            assert len(ranges) == 2 and app.output.get(*ranges) == f'Foreign item {i}'
                            expected = (PALETTES[mode.lower()]['muted'] if flag is None else
                                        colour if mode == 'Dark' else LIGHT_ITEMS[flag])
                            assert app.output.tag_cget(colour, 'foreground') == expected
                    report['checks'].append('Server-classified foreign transfers and neutral unknown items render in both themes')
                    app.campaign.update(view); app.metrics.update(view)
                    assert len(app.campaign.table.get_children()) == 29
                    assert set(app.metrics.labels) == {'total', 'logic', 'chapters'}
                    app.show_tools(); app.tools_window.window.withdraw()
                    tools = app.tools_window
                    root_window.update()
                    assert [tools.tabs.tab(tab, 'text') for tab in tools.tabs.tabs()] == ['Deliveries', 'Live settings']
                    tools.volume.set(25); tools.position.set('Bottom Left'); tools.death.set('Disabled')
                    tools.apply_settings()
                    assert app.notification_settings['volume'] == 25
                    assert app.notification_settings['position'] == 'bottom_left'
                    assert app.runtime_settings['death_link'] == 'disabled'
                    report['checks'].append('Two client tools tabs and settings persistence')
                finally:
                    launcher.STATE = old_state
                    for handler in list(logging.getLogger('tlou-ap').handlers):
                        if handler not in handlers:
                            handler.close(); logging.getLogger('tlou-ap').removeHandler(handler)
            finally:
                root_window.destroy()
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
        raise
    finally:
        atomic_json(Path(output), report)
