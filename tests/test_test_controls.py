import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from tlou_ap.catalog import Config, COLLECTIBLES, MISSIONS, collectible_check, mission_check
from tlou_ap.session import Session
from tlou_ap.native.run import RunLedger
from tlou_ap.test_controls import TestControls, REQUEST, SIZE, HEADER


class Bridge:
    def __init__(self):
        self.pid = 1234
        self.shared = NS(current=3, pending=0, blocked=0, allowed=(1<<29)-1)
        self.command_busy = False
        self.result = None
        self.commands = []
        self.supply = {'ready':True,'shivs':1,'health_kits':0}

    def supplies(self): return dict(self.supply)
    def begin_command(self,*args):
        self.commands.append(args);self.command_busy=True;return len(self.commands)
    def command_result(self,sequence):
        if self.result is not None:self.command_busy=False
        return self.result


class TestLocalControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        path=Path(self.tmp.name)
        self.session=Session(path/'sessions','test-seed',0,1,'test-run',Config(starting_chapters=12))
        self.ledger=RunLedger(path/'run.json',[{100+i} for i in range(29)])
        self.ledger.data['started']=True;self.ledger.bind(self.session.identity)
        self.bridge=Bridge()
        self.adapter=NS(bridge=self.bridge, ledger=self.ledger, bound=True,compatibility_error='',
            receipt_query=None,deathlink=NS(command=None),airhorn=NS(command=None),native_instance='test-instance')
        self.client=NS(adapter=self.adapter,session=self.session,checked=set(),connected=True,
                       inventory=NS(synchronized=True),name='Local test')
        self.controls=TestControls(self.client,bytearray(SIZE))
        self.seq=0

    def tearDown(self):self.tmp.cleanup()

    def request(self,action,index=0,token=None,nonce=None):
        self.seq+=1
        raw=REQUEST.pack(self.seq,action,index,0,(token or self.controls.token).encode(),
                         (nonce or f'{self.seq:032x}').encode())
        self.controls.mapping[:REQUEST.size]=raw
        return self.controls.step()

    def test_mission_is_explicit_durable_override_without_native_commands(self):
        self.request(2)
        self.assertEqual(self.session.data['missions'],[0])
        self.assertEqual(self.bridge.commands,[])
        self.assertEqual(self.ledger.data['completed_tasks'],[])
        self.assertEqual(self.ledger.data['native_confirmed'],[])
        self.assertEqual(self.ledger.data['test_missions'],[0])
        self.assertEqual(self.controls.outcome,2)
        check=mission_check(MISSIONS[0]).id
        self.assertIn(check,self.session.earned_checks)
        self.client.checked.update(self.session.earned_checks)
        self.controls.step();self.assertEqual(self.controls.outcome,3)
        reopened=RunLedger(self.ledger.path,self.ledger.required)
        self.assertEqual(reopened.data['test_missions'],[0])
        self.assertEqual(reopened.incompatible_progress([0]+[-1]*28),'')

    def test_override_reconciles_after_session_write_interruption(self):
        self.ledger.data['test_missions']=[0];self.ledger.save()
        self.ledger.reconcile_checks(self.session)
        self.assertEqual(self.session.data['missions'],[0])

    def test_no_out_of_order_or_locked_mission(self):
        self.request(2,5)
        self.assertEqual(self.controls.outcome,4)
        self.assertEqual(self.session.data['missions'],[])

    def test_collectible_waits_for_real_game_confirmation(self):
        self.session.complete_mission(0)
        self.request(1,0)
        self.assertEqual(self.bridge.commands[0][0],8)
        self.assertNotIn(0,self.session.data['collectibles'])
        self.assertTrue(self.controls.step())
        self.bridge.result=1
        self.controls.step()
        self.assertIn(0,self.session.data['collectibles'])
        self.assertIn(0,self.ledger.data['collectibles'])
        self.assertEqual(self.controls.outcome,2)
        self.client.checked.add(collectible_check(COLLECTIBLES[0]).id)
        self.controls.step();self.assertEqual(self.controls.outcome,3)

    def test_failed_or_uncertain_game_grant_never_creates_check(self):
        self.session.complete_mission(0)
        self.request(1)
        self.bridge.result=3
        self.controls.step()
        self.assertEqual(self.controls.outcome,5)
        self.assertEqual(self.session.data['collectibles'],[])
        self.controls.step();self.assertEqual(len(self.bridge.commands),1)

    def test_duplicate_nonce_and_stale_run_rejected(self):
        self.request(2,nonce='a'*32)
        self.request(2,1,nonce='a'*32)
        self.assertEqual(self.controls.outcome,4)
        self.request(2,1,token='stale')
        self.assertEqual(self.session.data['missions'],[0])

    def test_disconnect_and_mismatch_rejected(self):
        self.client.connected=False;self.request(2)
        self.client.connected=True;self.adapter.compatibility_error='foreign save';self.request(2)
        self.assertEqual(self.controls.outcome,4)
        self.assertEqual(self.session.data['missions'],[])

    def test_native_command_serialization_and_supply_actions(self):
        self.bridge.command_busy=True
        self.request(3)
        self.assertEqual(self.bridge.commands,[])
        self.bridge.command_busy=False;self.controls.step()
        self.assertEqual(self.bridge.commands[0][:2],(9,3|(3<<8)))
        self.bridge.result=1;self.controls.step()
        self.assertEqual(self.session.data['received'],[])
        self.assertEqual(self.session.data['receipts'],{})
        self.request(4)
        self.assertEqual(self.bridge.commands[1][0],10)

    def test_pause_wait_and_timeout_do_not_deliver_later(self):
        self.bridge.supply['ready']=False
        self.request(3)
        self.assertEqual(self.bridge.commands,[])
        self.controls.pending['since']-=61
        self.controls.step()
        self.bridge.supply['ready']=True;self.controls.step()
        self.assertEqual(self.controls.outcome,4)
        self.assertEqual(self.bridge.commands,[])

    def test_protocol_catalog_and_schema(self):
        fields=HEADER.unpack(self.controls.mapping[128:640])
        self.assertEqual(fields[2],1)
        self.assertEqual(fields[3],SIZE)
        self.assertEqual(fields[8],len(COLLECTIBLES)+len(MISSIONS))
        self.assertEqual(fields[0]&1,0)

    def test_disabled_collectible_cannot_pretend_to_send(self):
        self.session.config=Config(starting_chapters=12,collectible_checks=False)
        self.request(1)
        self.assertEqual(self.controls.outcome,4)
        self.assertEqual(self.bridge.commands,[])

    def test_production_client_sends_checks_and_accepts_websocket_ack(self):
        from websockets.legacy.server import serve
        from websockets.legacy.client import connect
        from tlou_ap.client import Client, REQUIRED_CAPABILITIES
        self.adapter.capabilities=REQUIRED_CAPABILITIES
        self.adapter.run_id='test-run'
        self.adapter.set_gate=lambda session: None
        self.adapter.observe=lambda session: self.ledger.reconcile_checks(session)
        self.adapter.can_deliver=lambda item:False
        client=Client('Local test',Path(self.tmp.name)/'sessions',self.adapter)
        client.session=self.session;client.connected=True;client.inventory.synchronized=True
        client.test_controls=self.controls;self.controls.client=client
        received=[]
        async def handler(ws):
            async for raw in ws:
                for packet in json.loads(raw):
                    if packet['cmd']=='LocationChecks':
                        received.extend(packet['locations'])
                        await ws.send(json.dumps([{'cmd':'RoomUpdate','checked_locations':packet['locations']}]))
        async def exercise():
            async with serve(handler,'127.0.0.1',0) as server:
                async with connect('ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])) as socket:
                    self.request(2,0)
                    await client.poll(socket)
                    for packet in json.loads(await asyncio.wait_for(socket.recv(),3)):
                        await client.handle(socket,packet)
                    self.controls.step();self.assertEqual(self.controls.outcome,3)
                    self.request(1,0);self.bridge.result=1
                    await client.poll(socket)
                    for packet in json.loads(await asyncio.wait_for(socket.recv(),3)):
                        await client.handle(socket,packet)
                    self.controls.step();self.assertEqual(self.controls.outcome,3)
                    self.assertIn(19711000,received)
                    self.assertIn(19712000,received)
                    self.assertIn(19713000,received)
                    self.assertEqual(len(received),len(set(received)))
        asyncio.run(exercise())


if __name__=='__main__':unittest.main()
