"""Nonblocking native mailbox; the client journals before the command is sent."""
import hashlib
import secrets


class NativeDeathLink:
    def __init__(self, bridge):
        self.bridge = bridge
        self.enabled = False
        self.epoch = 0
        self.command = None
        self.unconfirmed = False
        self.local = bridge.shared.death_local
        self.remote = bridge.shared.death_remote
        bridge.shared.death_enabled = 0

    def configure(self, enabled):
        if enabled != self.enabled:
            self.local = self.bridge.shared.death_local
            self.remote = self.bridge.shared.death_remote
            self.epoch = secrets.randbelow(0x7ffffffe) + 1 if enabled else 0
        self.enabled = bool(enabled)
        self.bridge.shared.death_enabled = self.epoch

    def poll(self):
        s = self.bridge.shared
        local, remote = s.death_local - self.local, s.death_remote - self.remote
        self.local, self.remote = s.death_local, s.death_remote
        unconfirmed, self.unconfirmed = self.unconfirmed, False
        return {'local': self.enabled and local > 0, 'remote': self.enabled and remote > 0,
                'dead': s.death_state == 1, 'unconfirmed': unconfirmed}

    def deliver(self, receipt, *, before_submit):
        if self.command:
            previous, sequence = self.command
            result = self.bridge.command_result(sequence)
            if result is None:
                return 'pending'
            self.command = None
            # A previous request from another session is consumed, never resubmitted.
            if previous != receipt:
                return 'not_applied'
            return {1: 'submitted', 2: 'not_applied'}.get(result, 'uncertain')
        if not self.enabled or self.bridge.shared.death_state != 2 or self.bridge.command_busy:
            return 'not_applied'
        key = (self.epoch << 32) | int.from_bytes(hashlib.sha256(receipt.encode()).digest()[:4], 'little')
        before_submit(receipt)
        sequence = self.bridge.begin_command(3, self.bridge.shared.current << 8, key)
        self.command = receipt, sequence
        return 'pending'

    def clear_finished(self):
        if self.command and self.bridge.command_result(self.command[1]) is not None:
            self.command = None
