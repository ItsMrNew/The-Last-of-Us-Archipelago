"""Supplement completion hooks with observed, live task difficulty changes."""


class LiveTaskProgress:
    def __init__(self):
        self.previous = None
        self.started = {}
        self.pending = {}
        self.after_restore = {}

    def observe(self, nodes, events, session, can_track=None):
        current = {node['sid']: node['difficulty'] for node in nodes}
        # Play/Begin can restore arbitrary task flags. Never infer completion
        # across one, including when its automatic starts share this batch.
        restore = any(e['type'] == 1 and e['flags'] != 0x40000000 for e in events)
        if restore or self.previous is None:
            self.started.clear()
            self.pending.clear()
            # A checkpoint restarts automatic tasks in the same batch as Play.
            # Do not infer across the restore. Wait for a later unfinished
            # snapshot before tracking their subsequent live completion.
            self.after_restore = {e['sid']: dict(e) for e in events
                                  if e['type'] == 1 and e['flags'] == 0x40000000}
        else:
            def allowed(mission):
                return (session.can_start(mission) if can_track is None else
                        can_track(mission, tuple(self.pending.values())))

            def finish(task, event):
                if not allowed(event['mission'] - 1):
                    del self.started[task]
                elif self.previous.get(task) == -1 and current.get(task, -1) >= 0:
                    self.pending[task] = {**event, 'type': 6, 'extra': current[task],
                                          'source': 'live_task_difficulty'}
                    del self.started[task]

            for task, event in self.after_restore.items():
                if (allowed(event['mission'] - 1) and self.previous.get(task) == -1
                        and current.get(task) == -1):
                    self.started[task] = event
            self.after_restore.clear()

            # Finish observed predecessors before considering new mission starts.
            # Their inferred evidence may authorize a transition in this batch.
            for task, event in sorted(self.started.items(), key=lambda pair: pair[1]['mission']):
                finish(task, event)
            starts = (e for e in events if e['type'] == 1 and e['flags'] == 0x40000000)
            for event in sorted(starts, key=lambda e: e['mission']):
                task = event['sid']
                if allowed(event['mission'] - 1) and self.previous.get(task) == -1:
                    self.started[task] = dict(event)
                    finish(task, event)
        self.previous = current
        hooked = {e['sid'] for e in events if e['type'] == 6}
        return [event for task, event in self.pending.items() if task not in hooked]

    def accepted(self):
        self.pending.clear()
