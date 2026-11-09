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

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
PORT = 5021


def lab_config(port: int) -> dict:
    """Point Map môi trường lab, mọi địa chỉ chuyển sang `port`."""
    c = load()
    for d in c["devices"]:
        d["port"] = port
    return c


def device(cfg: dict, name: str) -> dict:
    return next(d for d in cfg["devices"] if d["name"] == name)


@pytest.fixture(scope="session")
def cfg():
    c = lab_config(PORT)
    start(c)
    return c


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
