"""方向、路段与公告时段共同决定线路状态；每条报价说明列出采用的来源。

按本地材料顺序检查：公告到达、解除通知（先到目录后到正文）、方向修订，
以及解除通知与公告的接收顺序，对线路说明和历史发布的影响。
"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from capture_service.ledger import connect, receive
from capture_service.collection import collect, register_sources
from capture_service.view import overview
from capture_service.archive import release, get

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = '111803-007'
STARTS = '2026-11-13T06:00+08:00'
RELEASED = '2026-11-13T14:00+08:00'

def receive_bin(connection, name):
    raw = (ROOT / 'data' / name).read_bytes()
    receipt = {'url': 'https://local-source-007.example.test/records/' + name,
               'status': 200, 'body_sha256': hashlib.sha256(raw).hexdigest()}
    receive(connection, COLLECTION, raw, receipt)

def route_entry(view, direction, segment='G-1'):
    for entry in view['route_status']:
        if entry['segment'] == segment and entry['direction'] == direction:
            return entry
    return None

def source_ids(target):
    return {(s['type'], s['id'], s['version']) for s in target['sources']}

class RouteStatus(unittest.TestCase):
    def test_notice_arrival_sets_direction_period(self):
        with tempfile.TemporaryDirectory() as directory:
            c = connect(Path(directory) / 'state.sqlite3')
            collect(c, COLLECTION, ROOT / 'data' / 'partial.json')
            view = overview(c, COLLECTION)
            north = route_entry(view, 'northbound')
            self.assertEqual(north['state'], 'controlled')
            self.assertEqual(north['starts_at'], STARTS)
            self.assertIsNone(north['released_at'])
            self.assertTrue(north['verified'])
            self.assertEqual(source_ids(north), {('road_notice', 'road_notice-A', 'v1')})
            # 北行限制不套到南行；报价尚未到达时不产生报价说明。
            self.assertIsNone(route_entry(view, 'southbound'))
            self.assertEqual(view['quote_explanations'], [])
            collect(c, COLLECTION, ROOT / 'data' / 'normal.json')
            view = overview(c, COLLECTION)
            (explanation,) = view['quote_explanations']
            self.assertEqual(explanation['status'], 'explained')
            self.assertEqual(explanation['price_cny_kg'], 8.67)
            self.assertEqual(explanation['farm_region'], '河北北部')
            self.assertEqual([d['direction'] for d in explanation['directions']], ['northbound'])
            self.assertEqual(source_ids(explanation),
                             {('road_notice', 'road_notice-A', 'v1'),
                              ('farm_quote', 'farm_quote-A', 'v1')})
            c.close()

    def test_release_hits_only_matching_direction_and_period(self):
        with tempfile.TemporaryDirectory() as directory:
            c = connect(Path(directory) / 'state.sqlite3')
            collect(c, COLLECTION, ROOT / 'data' / 'normal.json')
            published = release(c, COLLECTION)
            collect(c, COLLECTION, ROOT / 'data' / 'event-pending.json')
            view = overview(c, COLLECTION)
            # 解除通知只进目录、正文未到时，当前方向判断不能视为已核实。
            self.assertEqual([p['kind'] for p in view['pending_sources']], ['road_release'])
            north = route_entry(view, 'northbound')
            self.assertEqual(north['state'], 'controlled')
            self.assertFalse(north['verified'])
            self.assertEqual(view['quote_explanations'][0]['status'], 'pending')
            collect(c, COLLECTION, ROOT / 'data' / 'event-complete.json')
            view = overview(c, COLLECTION)
            self.assertEqual(view['pending_sources'], [])
            north = route_entry(view, 'northbound')
            self.assertEqual(north['state'], 'released')
            self.assertEqual(north['starts_at'], STARTS)
            self.assertEqual(north['released_at'], RELEASED)
            self.assertTrue(north['verified'])
            self.assertEqual(source_ids(north), {('road_notice', 'road_notice-A', 'v1'),
                                                 ('road_release', 'road_release-A', 'v1')})
            release_events = [e for e in north['events'] if e['kind'] == 'road_release']
            self.assertEqual(release_events[0]['notice_no'], 'ROAD-2')
            # 解除只命中 northbound 与 06:00-14:00 时段，不影响南行。
            self.assertIsNone(route_entry(view, 'southbound'))
            explanation = view['quote_explanations'][0]
            self.assertEqual(explanation['status'], 'explained')
            self.assertEqual(source_ids(explanation),
                             {('road_notice', 'road_notice-A', 'v1'),
                              ('road_release', 'road_release-A', 'v1'),
                              ('farm_quote', 'farm_quote-A', 'v1')})
            # 解除前发布的视图保持原状。
            frozen = get(c, COLLECTION, published)
            self.assertEqual(route_entry(frozen, 'northbound')['state'], 'controlled')
            c.close()

    def test_direction_revision_pending_then_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            c = connect(Path(directory) / 'state.sqlite3')
            collect(c, COLLECTION, ROOT / 'data' / 'normal.json')
            collect(c, COLLECTION, ROOT / 'data' / 'event-pending.json')
            collect(c, COLLECTION, ROOT / 'data' / 'event-complete.json')
            published = release(c, COLLECTION)
            # 目录改指 v2 但正文未取得：先前收据不能证明当前方向判断已核实。
            register_sources(c, COLLECTION, ROOT / 'data' / 'revised.json')
            view = overview(c, COLLECTION)
            self.assertFalse(route_entry(view, 'northbound')['verified'])
            self.assertEqual(view['quote_explanations'][0]['status'], 'pending')
            # 取得修订正文后：南行按 v2 管制，北行维持已解除。
            collect(c, COLLECTION, ROOT / 'data' / 'revised.json')
            view = overview(c, COLLECTION)
            south = route_entry(view, 'southbound')
            self.assertEqual(south['state'], 'controlled')
            self.assertEqual(south['starts_at'], STARTS)
            self.assertTrue(south['verified'])
            self.assertEqual(source_ids(south), {('road_notice', 'road_notice-A', 'v2')})
            north = route_entry(view, 'northbound')
            self.assertEqual(north['state'], 'released')
            self.assertEqual(north['released_at'], RELEASED)
            self.assertTrue(north['verified'])
            # v1 已被 v2 取代，不再参与当前判断，但保留在事件时间线。
            self.assertNotIn(('road_notice', 'road_notice-A', 'v1'), source_ids(north))
            superseded = [e for e in north['events']
                          if e['kind'] == 'road_notice' and e['version'] == 'v1']
            self.assertTrue(superseded[0]['superseded'])
            explanation = view['quote_explanations'][0]
            self.assertEqual(explanation['status'], 'explained')
            self.assertEqual([d['direction'] for d in explanation['directions']],
                             ['northbound', 'southbound'])
            # 新判断不改写先前发布所依据的 northbound 公告。
            frozen = get(c, COLLECTION, published)
            frozen_north = route_entry(frozen, 'northbound')
            self.assertEqual(frozen_north['state'], 'released')
            self.assertEqual(frozen_north['starts_at'], STARTS)
            self.assertIn(('road_notice', 'road_notice-A', 'v1'), source_ids(frozen_north))
            self.assertIsNone(route_entry(frozen, 'southbound'))
            c.close()

    def test_arrival_order_does_not_change_business_period(self):
        # 解除通知先于公告到达：业务时段仍按公告起始与解除时刻决定。
        c = connect(':memory:')
        receive_bin(c, 'source-event.bin')
        receive_bin(c, 'source-1.bin')
        receive_bin(c, 'source-2.bin')
        view = overview(c, COLLECTION)
        north = route_entry(view, 'northbound')
        self.assertEqual(north['state'], 'released')
        self.assertEqual(north['starts_at'], STARTS)
        self.assertEqual(north['released_at'], RELEASED)
        self.assertEqual(view['quote_explanations'][0]['status'], 'explained')
        c.close()

    def test_quote_alone_stays_pending(self):
        # 报价资料不包含足够信息时保持待核，不能仅由报价推断封路。
        c = connect(':memory:')
        receive_bin(c, 'source-2.bin')
        view = overview(c, COLLECTION)
        self.assertEqual(view['route_status'], [])
        (explanation,) = view['quote_explanations']
        self.assertEqual(explanation['status'], 'pending')
        self.assertEqual(explanation['directions'], [])
        self.assertEqual(source_ids(explanation), {('farm_quote', 'farm_quote-A', 'v1')})
        c.close()
