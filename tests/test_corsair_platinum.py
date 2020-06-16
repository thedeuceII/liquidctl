import itertools
import unittest
from collections import deque, namedtuple

from liquidctl.driver.coolit_platinum import CoolitPlatinumDriver

_Report = namedtuple('_Report', ['number', 'data'])


def _noop(*args, **kwargs):
    return None


class _MockPlatinumDevice:
    def __init__(self, vid, pid):
        self.fw_version = (1, 1, 15)
        self.temperature = 30.9
        self.fan1_speed = 1499
        self.fan2_speed = 1512
        self.pump_speed = 2702
        self.sent = deque()

        self.vendor_id = vid
        self.product_id = pid
        self.open = _noop
        self.claim = _noop
        self.release = _noop
        self.close = _noop
        self.clear_enqueued_reports = _noop

    def read(self, length):
        buf = bytearray(64)
        buf[2] = self.fw_version[0] << 4 | self.fw_version[1]
        buf[3] = self.fw_version[2]
        buf[7] = int((self.temperature - int(self.temperature)) * 255)
        buf[8] = int(self.temperature)
        buf[15:17] = self.fan1_speed.to_bytes(length=2, byteorder='little')
        buf[22:24] = self.fan2_speed.to_bytes(length=2, byteorder='little')
        buf[29:31] = self.pump_speed.to_bytes(length=2, byteorder='little')
        return buf[:length]

    def write(self, data):
        self.sent.appendleft(_Report(data[0], list(data[1:])))
        return len(data) - 1


class CorsairPlatinumTestCase(unittest.TestCase):
    def setUp(self):
        vid, pid, desc, kwargs = (
            0xffff, 0x0c17, 'Mock H115i Platinum', {'fan_count': 2, 'rgb_fans': True}
        )
        self.mock_hid = _MockPlatinumDevice(vid, pid)
        self.device = CoolitPlatinumDriver(self.mock_hid, desc, **kwargs)
        self.device.connect()

    def tearDown(self):
        self.device.disconnect()

    def test_get_status(self):
        temp, fan1, fan2, pump = self.device.get_status()
        self.assertAlmostEqual(temp[1], self.mock_hid.temperature, delta=1 / 255)
        self.assertEqual(fan1[1], self.mock_hid.fan1_speed)
        self.assertEqual(fan2[1], self.mock_hid.fan2_speed)
        self.assertEqual(pump[1], self.mock_hid.pump_speed)
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0)
        self.assertEqual(self.mock_hid.sent[0].data[2], 0xff)

    def test_initialize_status(self):
        (fw_version, ) = self.device.initialize()
        self.assertEqual(fw_version[1], '%d.%d.%d' % self.mock_hid.fw_version)

    def test_set_pump_mode(self):
        self.device.initialize(pump_mode='extreme')
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0)
        self.assertEqual(self.mock_hid.sent[0].data[2], 0x14)
        self.assertEqual(self.mock_hid.sent[0].data[0x17], 0x2)

    def test_fixed_fan_speeds(self):
        self.device.set_fixed_speed(channel='fan', duty=42)
        self.device.set_fixed_speed(channel='fan2', duty=84)
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0)
        self.assertEqual(self.mock_hid.sent[0].data[2], 0x14)
        self.assertEqual(self.mock_hid.sent[0].data[0x0b], 0x2)
        self.assertAlmostEqual(self.mock_hid.sent[0].data[0x10] / 2.55, 42, delta=1 / 2.55)
        self.assertEqual(self.mock_hid.sent[0].data[0x11], 0x2)
        self.assertAlmostEqual(self.mock_hid.sent[0].data[0x16] / 2.55, 84, delta=1 / 2.55)

    def test_custom_fan_profiles(self):
        self.device.set_speed_profile(channel='fan', profile=[(20, 0), (55, 100)])
        self.device.set_speed_profile(channel='fan2', profile=[(30, 20), (50, 80)])
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0)
        self.assertEqual(self.mock_hid.sent[0].data[2], 0x14)
        self.assertEqual(self.mock_hid.sent[0].data[0x0b], 0x0)
        self.assertEqual(self.mock_hid.sent[0].data[0x1e:0x2c],
                         [20, 0, 55, 255] + 5 * [60, 255])
        self.assertEqual(self.mock_hid.sent[0].data[0x11], 0x0)
        self.assertEqual(self.mock_hid.sent[0].data[0x2c:0x3a],
                         [30, 51, 50, 204, 60, 255] + 4 * [60, 255])

    def test_address_leds(self):
        colors = [[i + 1, i + 2, i + 3] for i in range(0, 24 * 3, 3)]
        self.device.set_color(channel='led', mode='super-fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[1].data[2:62],
                          list(itertools.chain(*((b, g, r) for r, g, b in colors[:20]))))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[0].data[2:14],
                          list(itertools.chain(*((b, g, r) for r, g, b in colors[20:]))))

    def test_address_components(self):
        colors = [[i + 1, i + 2, i + 3] for i in range(0, 3 * 3, 3)]
        eqcolors = [colors[0]] * 8 + [colors[1]] * 8 + [colors[2]] * 8
        self.device.set_color(channel='sync', mode='fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[1].data[2:62],
                          list(itertools.chain(*((b, g, r) for r, g, b in eqcolors[:20]))))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[0].data[2:14],
                          list(itertools.chain(*((b, g, r) for r, g, b in eqcolors[20:]))))

    def test_address_component_leds(self):
        colors = [[i + 1, i + 2, i + 3] for i in range(0, 8 * 3, 3)]
        eqcolors = colors + colors + colors
        self.device.set_color(channel='sync', mode='super-fixed', colors=iter(colors))
        self.assertEqual(self.mock_hid.sent[1].data[1] & 0b111, 0b100)
        self.assertEqual(self.mock_hid.sent[1].data[2:62],
                          list(itertools.chain(*((b, g, r) for r, g, b in eqcolors[:20]))))
        self.assertEqual(self.mock_hid.sent[0].data[1] & 0b111, 0b101)
        self.assertEqual(self.mock_hid.sent[0].data[2:14],
                          list(itertools.chain(*((b, g, r) for r, g, b in eqcolors[20:]))))
