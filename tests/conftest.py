"""Fixture dùng chung cho mọi bài kiểm thử.

Point Map đọc theo môi trường lab (IP loopback 127.0.1.x), nhưng đổi sang cổng riêng của
bài kiểm thử để không đụng simulator đang chạy (cổng 5020). Không bao giờ kết nối thiết bị thật.
"""
import logging
import pytest
from pymodbus.client import ModbusTcpClient
from modbus_io import Connections
from point_map import load
from sim import start
from simctl import SimControl

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
PORT = 5021
BACNET_CLIENT = "127.0.0.1/8:47819"                # client BACnet của bộ kiểm thử: khác cổng thiết bị và cổng lab


def lab_config(port: int) -> dict:
    """Point Map môi trường lab, mọi địa chỉ chuyển sang `port`; cổng serial ảo riêng theo `port`."""
    c = load()
    c["bacnet"] = dict(c.get("bacnet", {}), client=BACNET_CLIENT)
    for d in c["devices"]:
        if d.get("transport") == "rtu":
            name = d["serial"]["port"].rsplit("/", 1)[-1]
            d["serial"] = dict(d["serial"], port=f"var/serial/test-{port}/{name}")
        else:
            d["port"] = port
        if d.get("protocol") == "bacnet":
            d["bacnet_client"] = BACNET_CLIENT
    return c


def device(cfg: dict, name: str) -> dict:
    return next(d for d in cfg["devices"] if d["name"] == name)


@pytest.fixture(scope="session")
def _sim():
    c = lab_config(PORT)
    return c, start(c, control_port=0)


@pytest.fixture(scope="session")
def cfg(_sim):
    return _sim[0]


@pytest.fixture
def sim_ctl(_sim):
    """Kênh điều khiển của simulator chung; đặt lại giá trị khởi đầu sau bài kiểm thử."""
    ctl = SimControl(_sim[1].control_url)
    yield ctl
    ctl.reset()


@pytest.fixture
def conns(cfg):
    c = Connections()
    yield c
    c.close()


@pytest.fixture
def client(cfg):
    """Kết nối thô tới gateway điện (dong-ho-dien-01, dong-ho-dien-02), cho các bài gửi lệnh Modbus trực tiếp."""
    d = device(cfg, "dong-ho-dien-01")
    c = ModbusTcpClient(d["host"], port=d["port"], timeout=1, retries=0)
    c.connect()
    yield c
    c.close()
