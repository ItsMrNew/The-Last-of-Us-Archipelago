"""Generate/host the local validation seed using the isolated official AP checkout."""
import argparse
import asyncio
import os
from pathlib import Path
import shutil
import sys
import unittest  # Archipelago's supported restricted test-world loader.
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
AP = ROOT / '.deps/ArchipelagoTest'
OUTPUT = ROOT / '.state/local-game'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode', choices=('generate', 'host'))
args = parser.parse_args()
if not (AP / 'MultiServer.py').is_file():
    raise SystemExit('The local validation checkout is missing. Use your normal Archipelago server.')
os.environ['SKIP_REQUIREMENTS_UPDATE'] = '1'
os.environ['AP_TEST_WORLDS'] = 'tlou_part1'
sys.path.insert(0, str(AP))
OUTPUT.mkdir(parents=True, exist_ok=True)
os.chdir(AP)

if args.mode == 'generate':
    destination = AP / 'custom_worlds/tlou_part1.apworld'
    destination.parent.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'dist/tlou_part1.apworld', destination)
    import Generate
    from Main import main
    rolled, seed = Generate.main(Generate.mystery_argparse([
        '--player_files_path', str(ROOT / 'templates'),
        '--weights_file_path', 'The Last of Us Part I.yaml', '--multi', '1',
        '--seed', '20261012', '--spoiler', '1', '--outputpath', str(OUTPUT)]))
    main(rolled, seed)
    for archive in OUTPUT.glob('*.zip'):
        with ZipFile(archive) as packed:
            for name in packed.namelist():
                if name.endswith('.archipelago'):
                    (OUTPUT / Path(name).name).write_bytes(packed.read(name))
    print('Generated local seed:', OUTPUT)
else:
    seeds = list(OUTPUT.glob('*.archipelago'))
    if len(seeds) != 1:
        raise SystemExit('Generate one local seed first.')
    import MultiServer
    sys.argv = ['MultiServer.py', str(seeds[0]), '--host', '127.0.0.1', '--port', '38282',
                '--savefile', str(OUTPUT / 'local.apsave')]
    asyncio.run(MultiServer.main(MultiServer.parse_args()))
