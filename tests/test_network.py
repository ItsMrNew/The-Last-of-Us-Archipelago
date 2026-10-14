import asyncio
import ssl
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from websockets.exceptions import InvalidHandshake, InvalidMessage

from tlou_ap.client import Client, open_server
from test_client import Adapter


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_tls_upgrade_before_session_and_reconnect_reuses_secure_address(self):
        socket = AsyncMock()
        attempts = AsyncMock(side_effect=[InvalidMessage('TLS endpoint'), socket, socket])
        with tempfile.TemporaryDirectory() as folder, patch('tlou_ap.client.connect', attempts):
            client = Client('Tester',folder,Adapter())
            client.run_connection = AsyncMock()
            await client.connect('room.example:63548')
            await client.connect('room.example:63548')
            self.assertEqual([call.args[0] for call in attempts.call_args_list],
                ['ws://room.example:63548','wss://room.example:63548','wss://room.example:63548'])
            self.assertEqual(client.run_connection.await_count,2)
            self.assertEqual(socket.close.await_count,2)
            for call in attempts.call_args_list:
                self.assertNotIn('ssl',call.kwargs)  # wss uses the library's verified default TLS context.

    async def test_local_plain_server_and_different_address_are_not_forced_to_tls(self):
        socket = AsyncMock()
        attempts = AsyncMock(side_effect=[InvalidMessage('TLS endpoint'),socket,socket])
        with tempfile.TemporaryDirectory() as folder, patch('tlou_ap.client.connect',attempts):
            client = Client('Tester',folder,Adapter())
            client.run_connection = AsyncMock()
            await client.connect('remote.example:1234')
            await client.connect('127.0.0.1:38281')
            self.assertEqual(attempts.call_args.args[0],'ws://127.0.0.1:38281')

    async def test_explicit_tls_failure_never_downgrades(self):
        for error in (InvalidMessage('No response'),ssl.SSLCertVerificationError('Untrusted certificate')):
            with self.subTest(error=type(error).__name__), patch('tlou_ap.client.connect',AsyncMock(side_effect=error)) as attempt:
                with self.assertRaises(type(error)):
                    async with open_server('wss://room.example:1234'): self.fail('Unexpected connection')
                self.assertEqual(attempt.await_count,1)
                self.assertEqual(attempt.call_args.args[0],'wss://room.example:1234')

    async def test_upgrade_fails_once_and_propagates_handshake_failure(self):
        attempts=AsyncMock(side_effect=[InvalidMessage('Plain rejected'),InvalidMessage('Secure rejected')])
        with patch('tlou_ap.client.connect',attempts):
            with self.assertRaises(InvalidHandshake):
                async with open_server('room.example:1234'): self.fail('Unexpected connection')
        self.assertEqual(attempts.await_count,2)

    async def test_established_session_error_does_not_retry_or_upgrade(self):
        socket=AsyncMock()
        with patch('tlou_ap.client.connect',AsyncMock(return_value=socket)) as attempt:
            with self.assertRaises(InvalidMessage):
                async with open_server('room.example:1234'):
                    raise InvalidMessage('Session failure')
            self.assertEqual(attempt.await_count,1)
            socket.close.assert_awaited_once()

    async def test_cancellation_closes_established_socket(self):
        socket=AsyncMock()
        with patch('tlou_ap.client.connect',AsyncMock(return_value=socket)):
            with self.assertRaises(asyncio.CancelledError):
                async with open_server('room.example:1234'):
                    raise asyncio.CancelledError()
            socket.close.assert_awaited_once()

    async def test_auth_refusal_is_not_retried_by_transport(self):
        socket=AsyncMock()
        with tempfile.TemporaryDirectory() as folder, patch('tlou_ap.client.connect',AsyncMock(return_value=socket)) as attempt:
            client=Client('Tester',folder,Adapter())
            client.run_connection=AsyncMock(side_effect=ValueError('Connection refused: InvalidPassword'))
            with self.assertRaisesRegex(ValueError,'InvalidPassword'):
                await client.connect('room.example:1234')
            self.assertEqual(attempt.await_count,1)
            socket.close.assert_awaited_once()


if __name__ == '__main__': unittest.main()
