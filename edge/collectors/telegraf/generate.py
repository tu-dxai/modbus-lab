"""SINH CẤU HÌNH TELEGRAF TỪ POINT MAP — không viết tay thông tin thiết bị ở nơi khác (nguyên tắc 1).

Chạy:  make telegraf                 (môi trường site: địa chỉ thật -> edge/collectors/telegraf/telegraf.site.conf)
       make telegraf ENV=lab         (trỏ vào simulator, để thử)
       python generate.py --env site --out telegraf.conf

Modbus (plugin inputs.modbus, configuration_type = "request"):
  - mỗi kết nối một [[inputs.modbus]]: một host:port (TCP) hoặc một cổng serial (RTU). Thiết bị sau cùng
    gateway / cùng bus dùng chung một kết nối, đúng giới hạn kết nối của gateway thật;
  - mỗi thiết bị và bảng thanh ghi một [[inputs.modbus.request]] (slave_id, byte_order, register, fields);
    Telegraf tự gộp các ô liền nhau trong một request thành ít lệnh đọc nhất.
SNMP (plugin inputs.snmp): mỗi thiết bị một [[inputs.snmp]], mỗi điểm một [[inputs.snmp.field]].
BACnet: Telegraf không đọc; collector Python đọc (theo CLAUDE.md), nên bỏ qua và ghi chú ở đầu file.

Cấu hình chỉ được kiểm cú pháp và đối chiếu Point Map trong bộ kiểm thử, CHƯA chạy thử với Telegraf thật.
"""
import argparse, json, sys
from pathlib import Path
from point_map import DEFAULT_PATH, SITE_ENV, load_or_exit

MODBUS_TYPES = {"int16": "INT16", "uint16": "UINT16", "int32": "INT32", "uint32": "UINT32", "float32": "FLOAT32"}
OUT_DIR = Path(__file__).parent


class TelegrafError(Exception):
    """Point Map có thứ Telegraf không biểu diễn được."""


def q(v) -> str:
    """Giá trị TOML: chuỗi theo kiểu JSON (TOML chấp nhận), số giữ nguyên."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(float(v)) if isinstance(v, float) else str(v)
    return json.dumps(str(v), ensure_ascii=False)


def _scale(v) -> float:
    return float(v)


def _connection(d: dict) -> tuple[str, dict]:
    """(controller, tham số kết nối) của thiết bị Modbus."""
    if d.get("transport") == "rtu":
        s = d["serial"]
        return f"file://{s['port']}", {"transmission_mode": "RTU", "baud_rate": s["baudrate"],
                                       "data_bits": s.get("bytesize", 8), "parity": s.get("parity", "N"),
                                       "stop_bits": s.get("stop_bits", 1)}
    return f"tcp://{d['host']}:{d['port']}", {}


def _modbus(cfg: dict, lines: list[str]) -> None:
    groups: dict[str, list[dict]] = {}
    for d in cfg["devices"]:
        if d.get("protocol", "modbus") == "modbus":
            groups.setdefault(_connection(d)[0], []).append(d)
    for controller, devices in groups.items():
        first = devices[0]
        _, extra = _connection(first)
        name = (first.get("site_address") or controller.split("://", 1)[1]).replace("/", "_")
        timeout = f"{first.get('timeout', 3):g}s"
        lines += ["", "[[inputs.modbus]]",
                  f"  name = {q('modbus ' + name)}",
                  f"  controller = {q(controller)}",
                  f"  timeout = {q(timeout)}",
                  "  busy_retries = 0",
                  '  configuration_type = "request"']
        lines += [f"  {k} = {q(v)}" for k, v in extra.items()]
        for d in devices:
            for table in ("holding", "input"):
                points = [p for p in d["points"] if p["table"] == table]
                if not points:
                    continue
                fields = []
                for p in points:
                    if p["type"] not in MODBUS_TYPES:
                        raise TelegrafError(f"{d['name']}.{p['name']}: Telegraf không đọc được kiểu {p['type']!r}")
                    fields.append(f"    {{ address = {p['address']}, name = {q(p['name'])}, "
                                  f"type = {q(MODBUS_TYPES[p['type']])}, scale = {q(_scale(p.get('scale', 1)))} }},")
                lines += ["", "  [[inputs.modbus.request]]",
                          f"    slave_id = {d['device_id']}",
                          f"    byte_order = {q(d['byte_order'])}",
                          f"    register = {q(table)}",
                          '    measurement = "modbus"',
                          "    fields = [", *fields, "    ]",
                          "    [inputs.modbus.request.tags]",
                          f"      site = {q(cfg.get('site', ''))}",
                          f"      device = {q(d['name'])}"]


def _snmp(cfg: dict, lines: list[str]) -> None:
    for d in cfg["devices"]:
        if d.get("protocol") != "snmp":
            continue
        s = d.get("snmp", {})
        version = {"1": 1, "2c": 2, "3": 3}[str(s.get("version", "2c"))]
        agent, timeout = f"udp://{d['host']}:{d['port']}", f"{d.get('timeout', 3):g}s"
        lines += ["", "[[inputs.snmp]]",
                  f"  agents = [{q(agent)}]",
                  f"  version = {version}",
                  f"  community = {q(s.get('community', 'public'))}",
                  f"  timeout = {q(timeout)}",
                  "  retries = 1",
                  '  name = "snmp"',
                  "  [inputs.snmp.tags]",
                  f"    site = {q(cfg.get('site', ''))}",
                  f"    device = {q(d['name'])}"]
        for p in d["points"]:
            lines += ["  [[inputs.snmp.field]]", f"    name = {q(p['name'])}", f"    oid = {q(p['oid'])}"]
            scale = p.get("scale", 1)
            if scale != 1:
                digits = {0.1: 1, 0.01: 2, 0.001: 3}.get(scale)
                if digits is None:
                    raise TelegrafError(f"{d['name']}.{p['name']}: Telegraf SNMP chỉ chia được 10, 100, 1000 "
                                        f"(scale 0.1/0.01/0.001), không làm được scale {scale}")
                lines.append(f"    conversion = {q(f'float({digits})')}")


def generate(cfg: dict, inputs_only: bool = False) -> str:
    """inputs_only: chỉ sinh các inputs, để ghép (telegraf --config ... --config <file này>) vào cấu hình
    edge đã có [agent] và output riêng (MQTT) — tránh [agent] ở đây ghi đè interval / hostname của edge."""
    skipped = [d["name"] for d in cfg["devices"] if d.get("protocol", "modbus") not in ("modbus", "snmp")]
    lines = ["# =============================================================",
             "#  CẤU HÌNH TELEGRAF — SINH TỰ ĐỘNG TỪ POINT MAP, ĐỪNG SỬA TAY",
             f"#  Site: {cfg.get('site', '?')} · môi trường: {cfg.get('env', '?')}",
             "#  Sinh lại: make telegraf (edge/collectors/telegraf/generate.py)",
             "#  Chưa chạy thử với Telegraf thật — kiểm bằng: telegraf --config <file> --test",
             f"#  Bỏ qua (collector Python đọc BACnet): {', '.join(skipped) or 'không có'}",
             "# ============================================================="]
    if not inputs_only:
        lines += ["", "[agent]", '  interval = "5s"', "  omit_hostname = true"]
    _modbus(cfg, lines)
    _snmp(cfg, lines)
    if not inputs_only:
        lines += ["", "[[outputs.file]]", '  files = ["stdout"]']
    return "\n".join(lines + [""])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Sinh cấu hình Telegraf từ Point Map")
    ap.add_argument("--config", default=DEFAULT_PATH)
    ap.add_argument("--env", default=SITE_ENV, help="site = địa chỉ thật (mặc định); lab = simulator")
    ap.add_argument("--out", help=f"file ra (mặc định {OUT_DIR}/telegraf.<env>.conf); '-' = in ra màn hình")
    args = ap.parse_args(argv)
    cfg = load_or_exit(args.config, args.env)
    try:
        text = generate(cfg)
    except TelegrafError as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    if args.out == "-":
        print(text)
        return 0
    out = Path(args.out or OUT_DIR / f"telegraf.{args.env}.conf")
    out.write_text(text, encoding="utf-8")
    print(f"Đã sinh {out} từ {args.config} (môi trường {args.env})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
