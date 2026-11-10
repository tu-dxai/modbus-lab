# Modbus Lab — bàn thử Modbus, SNMP, BACnet trên máy của bạn

Bàn thử để kiểm phần mềm edge **trước khi chạm vào thiết bị thật**: simulator đóng vai thiết bị, giá trị do người
kiểm thử đặt và đứng yên tới khi đổi; simulator ghi lại mọi lệnh ghi client gửi tới (kể cả lệnh bị từ chối) để kiểm
"với đầu vào X, client có ghi đúng Y vào đúng thiết bị không". Thiết bị giả nói đủ bốn kiểu kết nối của container:
**Modbus TCP** (đồng hồ điện sau gateway, pin BESS), **Modbus RTU** qua cổng serial ảo (đồng hồ RS-485), **SNMP**
(UPS) và **BACnet/IP** (điều hòa CRAH, ghi kèm mức ưu tiên và nhả lệnh). Kèm collector mẫu có trang web, công cụ ghi
có rào chắn và nhật ký kiểm toán, bộ sinh cấu hình Telegraf từ Point Map, bộ kiểm tra Point Map và 238 bài kiểm thử
tự động. Hai trang web hiển thị song ngữ **tiếng Việt / tiếng Nhật**.

## Có gì trong thư mục

| Đường dẫn | Vai trò |
|---|---|
| `edge/point-map/devices.yml` | **Point Map** của site — địa chỉ thật (host, port, device_id) từng thiết bị, ô nhớ, kiểu dữ liệu, byte order, hệ số, cảnh báo |
| `edge/point-map/environments/lab.yml` | Ánh xạ từng địa chỉ thật sang simulator trên máy này (môi trường mặc định) |
| `edge/point-map/point_map.py` | Đọc Point Map, áp môi trường, **kiểm tra**; mọi công cụ gọi khi khởi động, có lỗi thì báo hết rồi dừng |
| `edge/modbus/modbus_io.py` | Đọc điểm và quản lý kết nối: một kết nối cho mỗi `host:port` hoặc cổng serial, thiết bị cùng gateway/bus dùng chung; điểm SNMP/BACnet chuyển sang module tương ứng |
| `edge/modbus/async_bridge.py` | Vòng lặp asyncio chạy nền để code đồng bộ gọi thư viện async (pysnmp, bacpypes3) |
| `edge/snmp/snmp_io.py` | Đọc điểm SNMP (GET theo OID, v1/v2c) |
| `edge/collectors/bacnet/bacnet_io.py` | Collector Python cho BACnet/IP: đọc presentValue, ghi kèm priority, nhả lệnh (relinquish) |
| `edge/collectors/telegraf/generate.py` | `make telegraf`: **sinh cấu hình Telegraf** (`inputs.modbus` TCP/RTU, `inputs.snmp`) từ Point Map |
| `i18n/messages.yml` | **Từ điển song ngữ vi/ja**: mọi chữ trên hai trang web và mọi thông báo lỗi trang web hiển thị |
| `i18n/i18n.py`, `i18n.js` | Dịch phía server (lỗi mang mã) và phía trình duyệt (nút đổi ngôn ngữ, dịch chữ và lỗi) |
| `i18n/export.py` | `make i18n-export`: xuất mọi cặp vi/ja ra bảng TSV để người duyệt bản dịch |
| `edge/write-service/write.py` | Ghi một điểm **qua rào chắn**: chỉ điểm được phép, giá trị trong `allowed` hoặc `[min, max]`, đọc lại xác nhận; BACnet ghi kèm priority và nhả lệnh |
| `edge/write-service/audit.py` | **Nhật ký kiểm toán** lệnh ghi (JSON Lines, chỉ ghi thêm, `var/audit/writes.jsonl`); `make audit` |
| `tools/simulator/sim.py` | Simulator: mỗi địa chỉ một thiết bị giả — Modbus TCP, Modbus RTU (serial ảo), SNMP agent, BACnet device |
| `tools/simulator/vserial.py` | Cặp cổng serial ảo (pty) thay cho bus RS-485, không cần socat |
| `tools/simulator/snmp_agent.py`, `bacnet_device.py` | UPS giả (SNMP, UPS-MIB) và CRAH giả (BACnet/IP, mảng ưu tiên 16 mức) |
| `tools/simulator/sim_state.py` | Giá trị hiện tại của mọi điểm và **nhật ký lệnh ghi** (nhân chứng) |
| `tools/simulator/sim_control.py`, `control.html` | Kênh điều khiển HTTP và trang web đặt giá trị, xem lệnh ghi (cổng 5080) |
| `edge/modbus/frames.py` | **Khung tin Modbus thô**: bắt từng byte gửi và nhận, tách trường, giải nghĩa ra giá trị điểm đo |
| `tools/simulator/simctl.py` | Điều khiển simulator từ code kiểm thử (`SimControl`) hoặc dòng lệnh (`make set/get/writes/reset`) |
| `tools/codec/codec.py` | Mã hóa, giải mã số theo 4 kiểu byte order |
| `tools/dashboard/collector.py` | Đọc mọi điểm, giải mã, kiểm tra cảnh báo, phục vụ trang web và API JSON (đọc và ghi) |
| `tools/dashboard/collector.html` | Trang web của collector: số liệu theo thiết bị, xu hướng, cảnh báo, nút ghi qua rào chắn |
| `tools/web/ui.css`, `ui.js` | Giao diện dùng chung cho hai trang: bố cục một màn hình, cột thiết bị, bảng, màu trạng thái |
| `tests/acceptance/` | 20 bài kiểm thử nghiệm thu, mã MB-xx khớp tài liệu nghiên cứu |
| `tests/point_map/` | 53 bài kiểm thử bộ kiểm tra Point Map và môi trường, mỗi loại lỗi một bài |
| `tests/simulator/` | 104 bài kiểm thử simulator: đặt giá trị, tự thay đổi, nhật ký lệnh ghi, khung tin thô, RTU, SNMP, BACnet |
| `tests/tools/` | 34 bài kiểm thử collector: đọc khi bấm, tự đọc, ghi, nhả lệnh BACnet, khung tin phía client, song ngữ |
| `tests/telegraf/` | 8 bài kiểm thử cấu hình Telegraf sinh ra (chỉ kiểm cấu trúc, chưa chạy Telegraf thật) |
| `tests/write_service/` | 8 bài kiểm thử nhật ký kiểm toán: ghi được, bị chặn, bị từ chối, ghi từ web |
| `tests/translations/` | 11 bài kiểm thử từ điển: đủ vi và ja, khớp tham số, mọi khóa trang web và code dùng đều có |
| `tests/conftest.py` | Bật simulator kiểm thử (môi trường lab, cổng 5021), dùng chung cho mọi bài |

Các module import nhau theo tên ngắn (`codec`, `sim`, `sim_state`, `simctl`, `collector`, `write`, `audit`, `point_map`, `modbus_io`, `snmp_io`, `bacnet_io`, `generate`, `i18n`). Nơi tìm module khai báo trong
`Makefile` (`PYTHONPATH`) và `pytest.ini` (`pythonpath`), nên hãy chạy qua `make` thay vì gọi thẳng `python`.

## Cài đặt

**Yêu cầu:** Linux (hoặc WSL2 trên Windows), Python **3.10 trở lên** (pymodbus 3.16.2 cần), `git`, `make`,
`python3-venv`, và mạng để tải thư viện lần đầu. Đã thử trên Ubuntu 24.04 / Python 3.12.
Thư viện (ghim phiên bản trong `requirements.txt`): pymodbus 3.16.2, pyserial 3.5 (RTU), pysnmp 7.1.32 (SNMP),
bacpypes3 0.0.110 (BACnet), pyyaml, pytest.

```bash
git clone git@github.com:tu-dxai/modbus-lab.git
cd modbus-lab
make setup        # tạo .venv và cài thư viện trong requirements.txt
make test         # tự bật simulator riêng ở cổng 5021-5022, không cần chuẩn bị gì thêm
```

Ubuntu chưa có `venv` hay `make`: `sudo apt install -y python3-venv make`.

**Máy chỉ có Python cũ** (Ubuntu 20.04 có Python 3.8): dùng `uv`, tự tải Python 3.12 riêng cho dự án,
không đụng Python của hệ thống:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # cài uv, mở terminal mới sau đó
make setup-uv
```

**macOS:** chưa chạy thẳng được. Simulator và kiểm thử dùng IP loopback `127.0.1.21`, `.30`, `.40`, `.50`; Linux dùng
được cả dải `127.x.x.x`, còn macOS phải thêm alias trước (mất sau khi khởi động lại máy), ví dụ
`sudo ifconfig lo0 alias 127.0.1.21 up` cho từng IP. Cổng serial ảo dùng pty của Linux. Chưa thử trên macOS.

**Windows thuần** (không WSL) không chạy được vì Makefile dùng đường dẫn `.venv/bin`.

Các cổng cần trống: 5020 (Modbus TCP), UDP 1161 (SNMP), UDP 47808 (BACnet thiết bị) và 47809 (BACnet client),
5080 (điều khiển simulator), 8080 (trang collector); kiểm thử dùng 5021-5025, 5041 và UDP 47819.

## Chạy

> **Mới dùng lần đầu?** Cả hai trang có nút **?** (phím `?`) mở hướng dẫn nhanh: trang dùng để làm gì, các bước
> thao tác, thuật ngữ (HR, IR, FC, Unit ID, byte order, hệ số, gateway) và phím tắt. Lần đầu mở trang, hướng dẫn
> tự hiện. Rê chuột lên chữ **HR** / **IR** ở bất kỳ đâu để xem chú thích. Nút **☰** (phím `[`) thu gọn danh sách
> thiết bị; icon **✎** cạnh giá trị để sửa ngay tại chỗ (Enter lưu, Esc hủy); icon **⟳** đọc riêng một điểm.

**HR và IR** — hai vùng thanh ghi riêng của Modbus:

| | Tên đầy đủ | Đọc / ghi | Lệnh | Thường dùng cho |
|---|---|---|---|---|
| **HR** | Holding Register | đọc và ghi | đọc FC03, ghi FC06 / FC16 | cài đặt, lệnh điều khiển (một số hãng đặt cả số đo) |
| **IR** | Input Register | chỉ đọc | đọc FC04 | số đo |

`HR 100` và `IR 100` là hai ô khác nhau.

Mở **ba cửa sổ terminal** trong thư mục `modbus-lab`.

**1. Bật simulator**

```bash
make sim                   # giá trị chỉ đổi khi đặt bằng tay (khởi đầu ở sim.base của Point Map)
make sim ARGS="--auto 5"   # tự thay đổi mỗi 5 giây; đổi được ngay trên trang hoặc bằng make auto S=10
```

**Tự thay đổi giá trị** (trang điều khiển: ô *Tự thay đổi* — Tắt / 5 / 10 / 30 giây): mỗi nhịp, điểm có `sim.noise`
dao động quanh giá trị đặt gần nhất trong biên độ ±noise. Đặt nhiệt độ tủ 31,5 °C rồi bật thì nhiệt độ dao động
quanh 31,5. Điểm `writable` (giá trị client ghi vào) không tự đổi. Tắt thì giá trị đứng yên tới khi đặt bằng tay.

Điều khiển thiết bị giả tại `http://localhost:5080`: cột trái là thiết bị nhóm theo gateway/địa chỉ (có ô tìm);
bên phải là bảng đặt giá trị cho thiết bị đang chọn, kèm ô **Tự thay đổi**. Lệnh client gửi tới xem ở khung tin
trang collector; khi test client khác thì dùng `make writes` / `make frames`. Hoặc dùng dòng lệnh:

```bash
make set P=dong-ho-dien-01.nhiet_do_tu V=31.5   # tạo tình huống: tủ điện nóng
make get                                         # xem giá trị hiện tại
make writes                                      # client đã ghi gì? (P=... để lọc một điểm)
make auto S=10                                   # tự thay đổi mỗi 10 giây (S=0: chỉ đặt bằng tay)
make reset                                       # về giá trị khởi đầu, xóa nhật ký
```

Giá trị được làm tròn đúng như thiết bị thật lưu: đặt `231.55` V vào ô `uint16` hệ số 0.1 thì thiết bị báo `231.6`.
Giá trị không vừa thanh ghi (ví dụ 7000 V > 6553.5) bị từ chối. Điểm chỉ đọc vẫn chỉ đọc đối với client Modbus;
chỉ kênh điều khiển này đặt được chúng.

**2. Bật collector**

```bash
make collect                        # đọc khi bấm nút — mỗi lần bấm là đúng một lượt yêu cầu Modbus
make collect ARGS="--interval 2"    # tự đọc mỗi 2 giây, giống edge chạy thật
```

Mặc định collector **không tự đọc**: bấm **Đọc tất cả / Đọc thiết bị này** (hoặc phím **R**), hay nút **Đọc** trên
từng dòng để gửi yêu cầu riêng một điểm. Nhờ vậy khung tin và lệnh ghi bên simulator khớp đúng từng thao tác khi
kiểm thử. Sau mỗi lượt, trang hiện số điểm đọc được và thời gian (ms); ghi xong thì tự đọc lại thiết bị đó.
Ô **Tự đọc** trên trang bật/tắt đọc định kỳ (2/5/10 giây) không cần khởi động lại.

Trang `http://localhost:8080`: cột trái là thiết bị nhóm theo gateway/địa chỉ, chấm màu cho trạng thái
(xanh bình thường, vàng lỗi đọc, đỏ có cảnh báo); bảng bên phải là điểm đo của thiết bị đang chọn hoặc tất cả.
Đường dẫn giữ thiết bị đang chọn (`#dev=bess-01`) nên gửi cho người khác được. Mỗi điểm có đường xu hướng
của 60 lượt đọc gần nhất. Phím `/` để tìm thiết bị.
Đặt nhiệt độ tủ trên 30 °C (`make set P=dong-ho-dien-01.nhiet_do_tu V=31.5`) để thấy **CẢNH BÁO**.
Điểm có `writable: true` (ví dụ `bess-01.che_do`) có nút ghi ngay trên trang, đi qua cùng rào chắn với `edge/write-service/write.py`.

API JSON: `GET /api/points` (số liệu, cảnh báo, mô tả điểm, lịch sử); `POST /api/read` với `{}`,
`{"device": "bess-01"}` hoặc `{"point": "bess-01.muc_pin"}` để đọc ngay; `POST /api/auto` với `{"interval": 5}`
(0 = tắt); `POST /api/write` với `{"point": "bess-01.che_do", "value": 1}`; `POST /api/relinquish` với
`{"point": "crah-01.diem_dat_nhiet"}` (BACnet: nhả lệnh).
Cổng 8080 bận thì dùng `make collect ARGS="--web-port 8090"`.

Muốn mở trang từ máy khác (ví dụ chạy trong máy ảo): `make collect ARGS="--web-host 0.0.0.0"`.
Lưu ý: khi mở ra ngoài như vậy, ai vào được trang cũng bấm ghi được (vẫn bị rào chắn giới hạn).

**3. Thử ghi qua rào chắn**

```bash
make write P=bess-01.che_do V=1        # được phép: ghi rồi đọc lại xác nhận
make write P=bess-01.che_do V=5        # bị chặn: giá trị không nằm trong danh sách cho phép
make write P=dong-ho-dien-01.dien_ap V=999   # bị chặn: điểm chỉ đọc
make audit                             # ai ghi gì, vào đâu, lúc nào, kết quả (kể cả lệnh bị chặn)
```

Mọi lệnh ghi — từ `make write` (`cli:<user>`) hay từ trang collector (`web:<ip>`) — để lại một dòng JSON trong
`var/audit/writes.jsonl`: thời điểm, người ghi, môi trường, điểm, địa chỉ thật, giá trị, kết quả
(`written` / `released` / `blocked` / `failed`), giá trị trước và sau, mức ưu tiên BACnet, mã lỗi. File chỉ ghi thêm.

**4. Chạy kiểm thử tự động** (không cần bật simulator, test tự bật ở cổng 5021)

```bash
make test
```

## Modbus RTU, SNMP, BACnet

**Modbus RTU** (`dong-ho-rs485-03`, `transport: rtu`): Point Map khai cổng serial thật (`/dev/ttyUSB0`, 9600 8N1);
môi trường lab ánh xạ sang cổng ảo `var/serial/ttyUSB0` do simulator tạo (cặp pty, không cần socat hay thiết bị).
Khung tin RTU có CRC-16 ở cuối thay cho phần đầu MBAP; trang collector giải nghĩa và báo CRC sai. Một bus chỉ có
một master: đang chạy `make collect` thì `make once` sẽ không mở được cùng cổng.

**SNMP** (`ups-01`, `protocol: snmp`): mỗi điểm là một OID của UPS-MIB (RFC 1628), chỉ đọc; `scale` đổi số nguyên
thiết bị trả sang đơn vị kỹ thuật (ví dụ 545 × 0,1 = 54,5 V). Lab dùng cổng 1161 vì cổng 161 cần quyền root.

**BACnet/IP** (`crah-01`, `protocol: bacnet`): mỗi điểm là một đối tượng `loại,số` (`analog-input,1`...). Điểm ghi được
(`analog-value`, `binary-value`, `*-output`) phải khai `priority` 1–16. Thiết bị giữ mảng 16 mức ưu tiên: lệnh ở mức
cao nhất thắng; **nhả lệnh** (ghi Null ở đúng mức đó) trả quyền về mức thấp hơn hoặc giá trị mặc định.

```bash
make write P=crah-01.diem_dat_nhiet V=21           # ghi ở mức ưu tiên 8, đọc lại xác nhận
make write P=crah-01.diem_dat_nhiet V=relinquish   # nhả lệnh khi xong việc
```

Trang collector có icon **↶** cạnh ✎ để nhả lệnh. Trên trang simulator, đặt giá trị cho điểm ghi được = đổi giá trị
mặc định của thiết bị (giá trị khi không ai ra lệnh); `make reset` xóa mọi lệnh như thiết bị vừa khởi động lại.
Client BACnet phải gửi từ cổng khác cổng thiết bị khi chạy cùng máy (Point Map `bacnet.client`, lab `127.0.0.1:47809`).
Ghi vào `analog-input` bị thiết bị từ chối (`write-access-denied`), và lệnh đó vẫn có trong `make writes`.

## Sinh cấu hình Telegraf

```bash
make telegraf                 # môi trường site (địa chỉ thật) -> edge/collectors/telegraf/telegraf.site.conf
make telegraf ENV=lab         # trỏ vào simulator -> telegraf.lab.conf
make telegraf ARGS="--out -"  # in ra màn hình
```

Mỗi kết nối Modbus (TCP `host:port` hoặc cổng serial RTU) một khối `inputs.modbus` (`configuration_type = "request"`,
`slave_id`, `byte_order`, `scale` từ Point Map); mỗi agent SNMP một khối `inputs.snmp`. Thiết bị BACnet được ghi chú ở
đầu file và bỏ qua — collector Python đọc chúng. File sinh ra không đưa vào git; đừng sửa tay, sửa Point Map rồi sinh
lại. **Chưa chạy thử với Telegraf thật**: kiểm thử chỉ kiểm cấu trúc; trước khi dùng hãy chạy
`telegraf --config <file> --test` với simulator.

## Xem khung tin Modbus thô

**Collector** (bên gửi yêu cầu và nhận phản hồi) bắt từng byte trên đường truyền, trước khi giải mã: trang
`http://localhost:8080`, thẻ **Khung tin Modbus** phía dưới. Mỗi lần bấm Đọc/Ghi là đúng các cặp hỏi/đáp của thao
tác đó; bấm một dòng để xem từng byte. Phía client còn thấy sự cố mà thiết bị không thấy: **không phản hồi**
(gửi đi nhưng hết thời gian chờ) và **không kết nối được**. API: `GET /api/frames` của collector.

Khi kiểm thử một client khác (ví dụ dự án edge thật của bạn) với simulator, xem khung tin **thiết bị nhận được**
bằng `make frames` hoặc `SimControl().frames()` (API `/api/frames` của simulator):

```
#1     11:42:25.245  Đồng hồ điện tủ phân phối 01 @ 10.20.0.21:502 · Đọc holding register (FC03) · 0.16 ms
  Gửi   00 01 | 00 00 | 00 06 | 01 | 03 | 00 00 | 00 01      đọc holding từ ô 0, 1 ô
        Mã giao dịch | Giao thức | Độ dài | Unit ID | Mã lệnh | Ô đầu | Số ô
  Nhận  00 01 | 00 00 | 00 05 | 01 | 03 | 02 | 09 01      trả 1 thanh ghi
        Mã giao dịch | Giao thức | Độ dài | Unit ID | Mã lệnh | Số byte | Dữ liệu
        09 01 = 2305 (×0.1) → Điện áp = 230.5 V
```

- "Gửi" là client gửi tới thiết bị, "Nhận" là thiết bị trả về. Đủ FC03, FC04, FC06, FC16 và phản hồi lỗi
  (`83 02` = đọc holding lỗi 02, kèm ý nghĩa mã lỗi).
- Dòng cuối nối từ byte thô tới giá trị: thanh ghi nào thuộc điểm nào, số nguyên thô, byte order, hệ số.
- Lọc: `make frames D=bess-01`, `make frames ARGS="--errors"`, `ARGS="--function 16 --limit 50"`. Trang collector
  có lọc theo thiết bị, theo lệnh, chỉ lỗi, và nút tạm dừng.
- Code kiểm thử: `SimControl().frames(device=..., function=..., errors=True)`; API `GET /api/frames`.
- Simulator giữ 500 cặp gần nhất (`make sim ARGS="--frames 2000"` để giữ nhiều hơn); `make reset` xóa cả khung tin.

## Song ngữ tiếng Việt / tiếng Nhật

Hai trang web (collector `:8080`, điều khiển simulator `:5080`) có nút **Tiếng Việt / 日本語** ở góc trên. Lựa chọn
được nhớ trên trình duyệt (riêng cho từng trang); lần đầu theo ngôn ngữ trình duyệt; ép bằng `?lang=ja` hoặc `?lang=vi`.

- **Chữ giao diện và thông báo lỗi** nằm ở `i18n/messages.yml`. Lỗi server trả về gồm `error` (tiếng Việt, cho dòng lệnh
  và log), `code` và `params`; trang web dịch `code` theo ngôn ngữ đang chọn. Dòng lệnh và log luôn là tiếng Việt.
- **Tên thiết bị, điểm đo, câu cảnh báo** nằm trong Point Map: `label: { vi: ..., ja: ... }` và `message: { vi: ..., ja: ... }`.
  Mã như `dien_ap` vẫn hiện nhỏ bên dưới để đối chiếu.
- `make test` bắt lỗi thiếu một ngôn ngữ, lệch tham số `{tên}` giữa vi và ja, và khóa dùng mà từ điển không có.
- **Bản tiếng Nhật cần người Nhật duyệt** trước khi dùng chính thức: `make i18n-export > ban-dich.tsv` rồi mở bằng Excel.
  Đầu file `i18n/messages.yml` liệt kê các thuật ngữ cần xác nhận (ガード, 計測点, 保持レジスタ...).

## Kiểm thử client (edge) với simulator

Mẫu một bài kiểm thử cho logic điều khiển: tạo tình huống, chờ client phản ứng, kiểm tra lệnh ghi.

```python
from simctl import SimControl

def test_tu_nong_thi_bess_chuyen_che_do():
    ctl = SimControl()                                  # http://127.0.0.1:5080, hoặc biến SIM_URL
    ctl.reset()
    mark = ctl.last_seq()                               # bỏ qua mọi lệnh ghi trước mốc này
    ctl.set("dong-ho-dien-01.nhiet_do_tu", 31.5)        # đầu vào X
    w = ctl.wait_for_write("bess-01.che_do", timeout=10, since=mark)
    assert w["accepted"] and w["points"][0]["value"] == 1   # client ghi đúng Y
    assert ctl.writes(since=mark) == [w]                # và không ghi gì khác
```

Mỗi mục nhật ký (`GET /api/writes`) gồm: `seq`, `at`, `device`, `device_id`, `function` (6 hoặc 16), `address`,
`registers` (giá trị thô), `points` (`key`, `before`, `value` theo đơn vị kỹ thuật), `accepted`, `exception`
(mã lỗi Modbus nếu thiết bị từ chối). Lệnh ghi vào ô không khai báo hoặc sai `device_id` vẫn được ghi lại với
`points` rỗng, để bắt client cấu hình nhầm địa chỉ. Lệnh ghi BACnet có `function: "bacnet-write"`, `address` là đối
tượng (`analog-value,1`), `priority`; nhả lệnh có `value: null`.

Client viết bằng ngôn ngữ khác thì gọi thẳng HTTP API (xem đầu file `tools/simulator/sim_control.py`).
Để client ở máy hoặc container khác truy cập: tạo một môi trường mới, ví dụ `environments/lan.yml`, ánh xạ mỗi
địa chỉ thật sang IP của máy chạy simulator với **cổng khác nhau** (`"10.20.0.21:502": "0.0.0.0:5021"`,
`"10.20.0.30:502": "0.0.0.0:5022"`), chạy `make sim ARGS="--env lan --control-host 0.0.0.0"`, và cho client trỏ tới
`IP-máy:5021`, `IP-máy:5022`.

## Các bài kiểm thử

| Mã | Kiểm tra gì |
|---|---|
| MB-01 | Đọc một ô có giá trị biết trước |
| MB-02 | Bốn kiểu byte order; thiết bị BESS dùng CDAB, đọc nhầm ABCD ra số sai |
| MB-03 | Cấu hình lệch một ô thì đọc nhầm sang thông số khác |
| MB-04 | Số âm: −2,0 °C đọc nhầm kiểu không dấu ra 6551,6 °C |
| MB-05 | Đọc ô không tồn tại → mã lỗi 02 |
| MB-06 | Hỏi sai số thiết bị → lỗi |
| MB-07 | Mất kết nối → collector báo lỗi từng điểm, không sập |
| MB-10 | Ghi hợp lệ và đọc lại; rào chắn chặn ghi sai (ngoài `allowed`, ngoài `[min, max]`, điểm ghi được mà không khai giới hạn); thiết bị tự từ chối ghi ô chỉ đọc |
| Point Map | Ô nhớ đè nhau (tính cả kiểu 32 bit chiếm 2 ô), byte_order sai, type sai, điểm ghi được thiếu giới hạn, thiếu unit, thiếu trường bắt buộc; host/port/device_id/timeout sai; trùng device_id hoặc khác timeout sau cùng gateway; file môi trường thiếu, thừa, trùng địa chỉ; simulator và collector từ chối khởi động |
| Mạng | Gateway phục vụ nhiều thiết bị theo device_id; cùng device_id ở hai địa chỉ là hai thiết bị; thiết bị cùng gateway dùng chung kết nối; một địa chỉ mất kết nối không ảnh hưởng địa chỉ khác |
| Simulator | Giá trị đứng yên; đặt giá trị rồi đọc lại qua Modbus đúng kiểu, byte order, hệ số; đặt sai thì không đổi gì; nhật ký ghi lại lệnh được nhận, lệnh vào ô chỉ đọc, ô không khai báo, sai device_id; chờ lệnh ghi; dòng lệnh |
| web | Trang chính, `GET /api/points`, ghi qua `POST /api/write`: hợp lệ, bị rào chắn chặn (kèm mã lỗi để dịch), yêu cầu sai dạng; `/i18n.json`, `/i18n.js`, `?lang=` |
| Khung tin | Tách trường đúng byte trên đường truyền (FC03/04/06/16, lỗi, khung hỏng); ghép hỏi/đáp; giải nghĩa byte order, số âm, float; lọc, xóa, giới hạn số cặp; dòng lệnh |
| RTU | Cổng serial ảo; đọc, ghi, CRC đúng và sai; khung tin RTU ở collector và simulator; bus bận |
| SNMP | Point Map (OID, version, community); đọc theo hệ số; OID không có; agent không trả lời; Telegraf `inputs.snmp` |
| BACnet | Point Map (đối tượng, priority, client); đọc analog/binary; ghi kèm priority rồi nhả lệnh; thiết bị từ chối ghi input; simulator ghi nhận lệnh |
| Telegraf | Một khối cho mỗi kết nối; TCP và RTU; byte order, slave_id, scale; SNMP; bỏ qua BACnet |
| Kiểm toán | Ghi được, bị chặn, bị thiết bị từ chối, nhả lệnh; ghi từ web kèm địa chỉ người ghi |
| Bản dịch | Mỗi khóa đủ vi và ja, cùng tham số; mọi khóa trang web và code dùng đều có; xuất bảng duyệt |

## Bài tập gợi ý

1. **Tự gây lỗi byte order.** Copy `edge/point-map/devices.yml` thành `edge/point-map/devices-sai.yml`, đổi `byte_order` của `bess-01` thành `ABCD`.
   Giữ simulator chạy bằng file gốc, rồi chạy `make once ARGS="--config edge/point-map/devices-sai.yml"` — mức pin sẽ ra số vô nghĩa mà không có lỗi nào.
2. **Thêm thiết bị mới.** Thêm một khối vào `edge/point-map/devices.yml`, ví dụ máy lạnh sau gateway điện với `host: 10.20.0.21`, `port: 502`, `device_id: 3`.
   Thiết bị có IP riêng thì thêm một dòng địa chỉ vào `environments/lab.yml`. Không phải sửa code; khởi động lại simulator và collector.
3. **Thêm cảnh báo.** Thêm một dòng vào mục `alerts`, ví dụ điện áp dưới 210 V.

## Quy tắc Point Map

Simulator, collector và công cụ ghi kiểm tra Point Map khi khởi động; có lỗi thì in hết lỗi kèm tên thiết bị và điểm rồi dừng.

**Kết nối.** Mỗi thiết bị khai báo địa chỉ thật của chính nó:

```yaml
- name: dong-ho-dien-01
  host: 10.20.0.21     # IP thật của thiết bị hoặc của gateway
  port: 502            # cổng chuẩn Modbus TCP
  device_id: 1         # Unit ID / slave address — tra tài liệu hoặc màn hình cài đặt thiết bị
  byte_order: ABCD     # tra tài liệu, KHÔNG đoán
  timeout: 3           # giây, tùy chọn (mặc định 3); thiết bị thật chậm hơn simulator
```

- `host` khác rỗng, `port` 1–65535, `device_id` 0–255, `timeout` > 0.
- **Thiết bị trùng `host:port` = cùng sau một gateway**: dùng chung một kết nối TCP, `device_id` không trùng và nằm trong
  1–247 (địa chỉ RTU trên bus), cùng `timeout`. Hai địa chỉ khác nhau thì đều dùng `device_id: 1` được.
- Đổi IP gateway thì phải sửa ở mọi thiết bị phía sau; sửa sót một thiết bị thì nó bị coi là thiết bị riêng.

**Môi trường.** Mặc định mọi công cụ chạy `--env lab`: mỗi địa chỉ thật được ánh xạ sang simulator theo
`environments/lab.yml` (mỗi gateway một dòng). Chỉ `--env site` mới kết nối địa chỉ thật — ví dụ
`make once ARGS="--env site"`, `make write P=... V=... ARGS="--env site"`. File môi trường phải có đủ mọi địa chỉ,
không thừa, không hai địa chỉ trỏ chung một chỗ.

**Dữ liệu.**

- Mỗi thiết bị và mỗi điểm có `label: { vi: "...", ja: "..." }` không rỗng; mỗi cảnh báo có `message: { vi, ja }`
  và phải trỏ tới điểm có thật.

- `byte_order` là `ABCD`, `CDAB`, `BADC` hoặc `DCBA`.
- Mỗi điểm có `name`, `table` (`holding` hoặc `input`), `address`, `type` (`int16`, `uint16`, `int32`, `uint32`, `float32`) và `unit` (để `""` nếu không có đơn vị).
- Hai điểm cùng thiết bị, cùng bảng không được đè ô nhớ của nhau; kiểu 32 bit chiếm 2 ô liền nhau.
- Điểm `writable: true` phải có `allowed: [...]`, hoặc có đủ `min` và `max` (min ≤ max). Rào chắn ghi chặn mọi giá trị ngoài giới hạn đó.
- **RTU:** `transport: rtu`, `serial: { port, baudrate, parity, stop_bits }`, `device_id` 1–247; thiết bị cùng cổng
  serial phải cùng tham số. File môi trường ánh xạ cổng serial ở mục `serial`.
- **SNMP:** `protocol: snmp`, `snmp: { version: "1" | "2c", community }`; mỗi điểm có `oid` (không trùng), `type`
  (`integer`, `gauge32`, `counter32`), chỉ đọc.
- **BACnet:** `protocol: bacnet`, `device_instance` 0–4194302 (không trùng trong site); mỗi điểm có `object` dạng
  `loại,số` (không trùng); điểm ghi được chỉ là `*-value` / `*-output`, có `priority` 1–16, binary chỉ cho 0/1.
  Site có thiết bị BACnet phải khai `bacnet: { client: "IP/mask:cổng" }`.

## Lưu ý

- **Simulator nghiêm ngặt hơn nhiều thiết bị thật:** ô không khai báo trong Point Map luôn trả mã lỗi 02. Nếu một công cụ đọc gộp nhiều ô liền nhau mà đi qua ô trống, nó sẽ bị lỗi — điều này cũng xảy ra với một số thiết bị thật.
- **Hỏi sai số thiết bị**, simulator trả mã lỗi 04; thiết bị thật thường **im lặng tới khi hết thời gian chờ**. Simulator chỉ đúng bằng mô tả dùng để dựng nó.
- Simulator mở Modbus ở các IP loopback `127.0.1.x` (Linux dùng được cả dải `127.x.x.x` không cần cấu hình; macOS phải thêm alias cho `lo0`).
- Cổng 5020, 5080 hoặc 8080 đang bận thì báo lỗi khi khởi động — tắt chương trình đang dùng cổng đó, hoặc đổi địa chỉ trong `edge/point-map/environments/lab.yml` (Modbus), `make sim ARGS="--control-port ..."` (điều khiển), `make collect ARGS="--web-port ..."` (trang xem).
