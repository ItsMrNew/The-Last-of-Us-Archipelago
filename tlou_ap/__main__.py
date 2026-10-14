"""Launch the Archipelago client or inspect game progress locally."""
import argparse
import json
from pathlib import Path
import time

from .catalog import CHAPTERS, MISSIONS, COLLECTIBLES, Config
from .native.observer import Observer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('catalog', help='Show the development check catalog')
    sub.add_parser('launch', help='Open the playable Windows client')
    recovery = sub.add_parser('backup', help='Back up game saves and AP state without modifying either')
    recovery.add_argument('--state', type=Path, default=Path('.state'))
    recovery.add_argument('--savedata', type=Path)
    recovery.add_argument('--output', type=Path, default=Path('.state/backups'))
    for command in ('inspect', 'watch'):
        entry = sub.add_parser(command, help='Read live progress without changing the game')
        entry.add_argument('--pid', required=True, type=int)
        entry.add_argument('--output', type=Path, help='Save JSON (inspect) or JSONL (watch) locally')
        if command == 'watch':
            entry.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if args.command == 'backup':
        from .recovery import backup, default_savedata
        print(backup(args.state, args.savedata or default_savedata(), args.output))
        return
    if args.command == 'launch':
        from .launcher import main as launch
        launch()
        return
    if args.command == 'catalog':
        print(json.dumps({'chapters': len(CHAPTERS), 'missions': len(MISSIONS),
                          'collectible_candidates': len(COLLECTIBLES),
                          'total_checks': len(Config().active_checks),
                          'status': 'experimental native integration'}, indent=2))
        return
    try:
        with Observer(args.pid) as observer:
            if args.command == 'inspect':
                data = json.dumps(observer.snapshot(), indent=2)
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(data + '\n', encoding='utf-8')
                print(data)
                return
            if not 1 <= args.seconds <= 86400:
                parser.error('--seconds must be between 1 and 86400')
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
            previous = None
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                try:
                    snapshot = observer.snapshot()
                    if snapshot != previous:
                        additions = (set(snapshot['profile_collectibles']) - set(previous['profile_collectibles'])
                                     if previous is not None else set())
                        removals = (set(previous['profile_collectibles']) - set(snapshot['profile_collectibles'])
                                    if previous is not None else set())
                        inventory_added = (set(snapshot['inventory_collectibles']) - set(previous['inventory_collectibles'])
                                           if previous is not None else set())
                        completed = set(snapshot['mission_telemetry'].get('completed_mission_candidates', []))
                        prior_completed = (set(previous['mission_telemetry'].get('completed_mission_candidates', []))
                                           if previous is not None else completed)
                        data = {'time': time.time(), 'event': 'baseline' if previous is None else 'state_change',
                                'added': sorted(additions), 'removed': sorted(removals),
                                'inventory_added': sorted(inventory_added),
                                'mission_candidates_added': sorted(completed - prior_completed),
                                'added_names': [COLLECTIBLES[i]['name'] if i < len(COLLECTIBLES)
                                                else f'non-check treasure {i}' for i in sorted(additions)],
                                'snapshot': snapshot}
                        line = json.dumps(data)
                        if args.output:
                            with args.output.open('a', encoding='utf-8') as stream:
                                stream.write(line + '\n')
                        print(line, flush=True)
                        previous = snapshot
                except ValueError as error:
                    print(f'Waiting: {error}', flush=True)
                time.sleep(1)
    except KeyboardInterrupt:
        return
    except (OSError, ValueError) as error:
        parser.exit(1, f'Inspection unavailable: {error}\n')


if __name__ == '__main__':
    main()
