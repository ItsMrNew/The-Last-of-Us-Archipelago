"""Show clearly labelled sample progress without a server/game connection."""
from pathlib import Path
import tempfile
import tkinter as tk
import sys
import logging

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tlou_ap.catalog import Config
from tlou_ap.session import Session
from tlou_ap.tracker import snapshot
import tlou_ap.launcher as launcher

with tempfile.TemporaryDirectory(prefix='tlou-tracker-preview-') as folder:
    launcher.STATE = Path(folder)
    session = Session(Path(folder) / 'sessions', 'PREVIEW — SAMPLE DATA', 0, 1, 'preview', Config(death_link=True))
    for mission in range(3): session.complete_mission(mission)
    session.collect(1)
    checked = session.earned_checks - {19711002}
    root = tk.Tk(); app = launcher.Launcher(root)
    root.title('TEST PREVIEW • Archipelago launcher')
    app.appearance.choice.set('Dark'); app.appearance.change()
    app.connect_button.configure(state='disabled')
    app.server.set('archipelago.gg:12345'); app.slot.set('Survivor')
    app.tracker_view = snapshot(session, checked, connected=True, synchronized=True,
                                 current=3, death_enabled=True, death_state='queued')
    app.metrics.update(app.tracker_view)
    app.campaign.update(app.tracker_view)
    app.connection_label.configure(text='PREVIEW — sample campaign progress; no game or server connection.')
    app.run_label.configure(text='Run: preview  •  Slot: Survivor  •  Seed: SAMPLE DATA')
    app.progress_label.configure(text='3/29 missions complete  •  0 supplies queued  •  0 receipts held  •  DeathLink: enabled')
    app.next_label.configure(text=app.tracker_view.next_unlock)
    app.campaign.table.item('m:0', open=True)
    logging.getLogger('tlou-ap').info('PREVIEW — sample data only. No items or checks are sent.')
    logging.getLogger('tlou-ap').info('Chapter unlocked: The Quarantine Zone')
    logging.getLogger('tlou-ap').info('Confirmed collectible: Drafting Notice')
    root.after(600000, root.destroy)
    root.mainloop()
    for handler in list(logging.getLogger('tlou-ap').handlers):
        handler.close()
        logging.getLogger('tlou-ap').removeHandler(handler)
