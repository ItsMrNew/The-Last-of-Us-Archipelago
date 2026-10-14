"""One nonblocking, receipt-protected noise pulse at a time."""
import hashlib


class NativeAirhorn:
    def __init__(self, bridge, instance):
        self.bridge, self.instance = bridge, instance
        self.command = None
        self.discarding = False

    def cancel_pending(self):
        self.discarding = bool(self.command)
        self.reap_cancelled()

    def reap_cancelled(self):
        if self.discarding and self.command:
            if self.bridge.command_result(self.command[1]) is not None:
                self.command = None
                self.discarding = False

    def pulse(self, receipt, pending_instance, *, before_submit, can_submit):
        self.reap_cancelled()
        if self.discarding:
            return 'not_applied'
        if self.command:
            previous, sequence = self.command
            result = self.bridge.command_result(sequence)
            if result is None:
                return 'pending'
            self.command = None
            if previous != receipt:
                return 'uncertain'
            return {1: 'applied', 2: 'not_applied', 5: 'not_applied'}.get(result, 'uncertain')
        if pending_instance and pending_instance != self.instance:
            return 'uncertain'  # Native receipt evidence died with the process.
        if not can_submit or self.bridge.command_busy:
            return 'pending' if pending_instance else 'not_applied'
        key = int.from_bytes(hashlib.sha256(receipt.encode()).digest()[:8], 'little') or 1
        if pending_instance:
            sequence = self.bridge.begin_command(101, 6, key)
        else:
            if not self.bridge.shared.airhorn_ready:
                return 'not_applied'
            before_submit()
            sequence = self.bridge.begin_command(6, 1 | (self.bridge.shared.current << 8), key)
        self.command = receipt, sequence
        return 'pending'
