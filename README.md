# Modbus Lab — bàn thử Modbus trên máy của bạn

Bàn thử để kiểm phần mềm edge **trước khi chạm vào thiết bị thật**: simulator đóng vai thiết bị, giá trị do người
kiểm thử đặt và đứng yên tới khi đổi; simulator ghi lại mọi lệnh ghi client gửi tới (kể cả lệnh bị từ chối) để kiểm
"với đầu vào X, client có ghi đúng Y vào đúng thiết bị không". Kèm collector mẫu có trang web, công cụ ghi có rào chắn,
bộ kiểm tra Point Map và 122 bài kiểm thử tự động. Hai trang web hiển thị song ngữ **tiếng Việt / tiếng Nhật**.

## Có gì trong thư mục

| Đường dẫn | Vai trò |
|---|---|
| `edge/point-map/devices.yml` | **Point Map** của site — địa chỉ thật (host, port, device_id) từng thiết bị, ô nhớ, kiểu dữ liệu, byte order, hệ số, cảnh báo |
| `edge/point-map/environments/lab.yml` | Ánh xạ từng địa chỉ thật sang simulator trên máy này (môi trường mặc định) |
| `edge/point-map/point_map.py` | Đọc Point Map, áp môi trường, **kiểm tra**; mọi công cụ gọi khi khởi động, có lỗi thì báo hết rồi dừng |
| `edge/modbus/modbus_io.py` | Đọc điểm và quản lý kết nối: một kết nối cho mỗi `host:port`, thiết bị sau cùng gateway dùng chung |
| `i18n/messages.yml` | **Từ điển song ngữ vi/ja**: mọi chữ trên hai trang web và mọi thông báo lỗi trang web hiển thị |
| `i18n/i18n.py`, `i18n.js` | Dịch phía server (lỗi mang mã) và phía trình duyệt (nút đổi ngôn ngữ, dịch chữ và lỗi) |
| `i18n/export.py` | `make i18n-export`: xuất mọi cặp vi/ja ra bảng TSV để người duyệt bản dịch |
| `edge/write-service/write.py` | Ghi một điểm **qua rào chắn**: chỉ điểm được phép, giá trị trong `allowed` hoặc `[min, max]`, đọc lại xác nhận |
| `tools/simulator/sim.py` | Simulator Modbus TCP: mỗi địa chỉ một server — gateway điện (2 đồng hồ, ABCD) và pin BESS (CDAB) |
| `tools/simulator/sim_state.py` | Giá trị hiện tại của mọi điểm và **nhật ký lệnh ghi** (nhân chứng) |
| `tools/simulator/sim_control.py`, `control.html` | Kênh điều khiển HTTP và trang web đặt giá trị, xem lệnh ghi (cổng 5080) |
| `tools/simulator/simctl.py` | Điều khiển simulator từ code kiểm thử (`SimControl`) hoặc dòng lệnh (`make set/get/writes/reset`) |
| `tools/codec/codec.py` | Mã hóa, giải mã số theo 4 kiểu byte order |
| `tools/dashboard/collector.py` | Đọc mọi điểm, giải mã, kiểm tra cảnh báo, phục vụ trang web và API JSON (đọc và ghi) |
| `tools/dashboard/collector.html` | Trang web của collector: số liệu theo thiết bị, xu hướng, cảnh báo, nút ghi qua rào chắn |
| `tests/acceptance/` | 20 bài kiểm thử nghiệm thu, mã MB-xx khớp tài liệu nghiên cứu |
| `tests/point_map/` | 52 bài kiểm thử bộ kiểm tra Point Map và môi trường, mỗi loại lỗi một bài |
| `tests/simulator/` | 29 bài kiểm thử simulator: đặt giá trị, nhật ký lệnh ghi, dòng lệnh, nhiều địa chỉ và gateway |
| `tests/tools/` | 12 bài kiểm thử trang xem số liệu và API web |
| `tests/translations/` | 9 bài kiểm thử từ điển: đủ vi và ja, khớp tham số, mọi khóa trang web và code dùng đều có |
| `tests/conftest.py` | Bật simulator kiểm thử (môi trường lab, cổng 5021), dùng chung cho mọi bài |
| `telegraf/` | Cấu hình Telegraf viết tay — **cũ, chưa theo Point Map mới, chưa chạy thử**; sẽ thay bằng cấu hình sinh từ Point Map |

Các module import nhau theo tên ngắn (`codec`, `sim`, `sim_state`, `simctl`, `collector`, `write`, `point_map`, `modbus_io`, `i18n`). Nơi tìm module khai báo trong
`Makefile` (`PYTHONPATH`) và `pytest.ini` (`pythonpath`), nên hãy chạy qua `make` thay vì gọi thẳng `python`.

## Cài đặt

**Yêu cầu:** Linux (hoặc WSL2 trên Windows), Python **3.10 trở lên** (pymodbus 3.16.2 cần), `git`, `make`,
`python3-venv`, và mạng để tải thư viện lần đầu. Đã thử trên Ubuntu 24.04 / Python 3.12.

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

**macOS:** chưa chạy thẳng được. Simulator và kiểm thử dùng IP loopback `127.0.1.21`, `127.0.1.30`; Linux dùng
được cả dải `127.x.x.x`, còn macOS phải thêm alias trước (mất sau khi khởi động lại máy):
`sudo ifconfig lo0 alias 127.0.1.21 up && sudo ifconfig lo0 alias 127.0.1.30 up`. Chưa thử trên macOS.

**Windows thuần** (không WSL) không chạy được vì Makefile dùng đường dẫn `.venv/bin`.

Các cổng cần trống: 5020 (Modbus), 5080 (điều khiển simulator), 8080 (trang collector), 5021-5022 (kiểm thử).

## Chạy

Mở **ba cửa sổ terminal** trong thư mục `modbus-lab`.

**1. Bật simulator**

```bash
make sim                 # giá trị đứng yên ở sim.base của Point Map
make sim ARGS=--noise    # thêm nhiễu và độ trôi (mục sim: noise/drift), chỉ để xem cho sinh động
```

Điều khiển thiết bị giả tại `http://localhost:5080`: bên trái đặt giá trị từng điểm, bên phải là nhật ký lệnh ghi
client gửi tới. Hoặc dùng dòng lệnh:

```bash
make set P=dong-ho-dien-01.nhiet_do_tu V=31.5   # tạo tình huống: tủ điện nóng
make get                                         # xem giá trị hiện tại
make writes                                      # client đã ghi gì? (P=... để lọc một điểm)
make reset                                       # về giá trị khởi đầu, xóa nhật ký
```

Giá trị được làm tròn đúng như thiết bị thật lưu: đặt `231.55` V vào ô `uint16` hệ số 0.1 thì thiết bị báo `231.6`.
Giá trị không vừa thanh ghi (ví dụ 7000 V > 6553.5) bị từ chối. Điểm chỉ đọc vẫn chỉ đọc đối với client Modbus;
chỉ kênh điều khiển này đặt được chúng.

**2. Bật collector**

```bash
make collect
```

Mở trình duyệt tại `http://localhost:8080`. Số liệu cập nhật mỗi 2 giây, kèm đường xu hướng của 60 lượt gần nhất.
Đặt nhiệt độ tủ trên 30 °C (`make set P=dong-ho-dien-01.nhiet_do_tu V=31.5`) để thấy **CẢNH BÁO**.
Điểm có `writable: true` (ví dụ `bess-01.che_do`) có nút ghi ngay trên trang, đi qua cùng rào chắn với `edge/write-service/write.py`.

API JSON: `GET /api/points` (số liệu, cảnh báo, mô tả điểm, lịch sử) và `POST /api/write` với `{"point": "bess-01.che_do", "value": 1}`.
Cổng 8080 bận thì dùng `make collect ARGS="--web-port 8090"`.

Muốn mở trang từ máy khác (ví dụ chạy trong máy ảo): `make collect ARGS="--web-host 0.0.0.0"`.
Lưu ý: khi mở ra ngoài như vậy, ai vào được trang cũng bấm ghi được (vẫn bị rào chắn giới hạn).

**3. Thử ghi qua rào chắn**

```bash
make write P=bess-01.che_do V=1        # được phép: ghi rồi đọc lại xác nhận
make write P=bess-01.che_do V=5        # bị chặn: giá trị không nằm trong danh sách cho phép
make write P=dong-ho-dien-01.dien_ap V=999   # bị chặn: điểm chỉ đọc
```

**4. Chạy kiểm thử tự động** (không cần bật simulator, test tự bật ở cổng 5021)

```bash
make test
```

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
`points` rỗng, để bắt client cấu hình nhầm địa chỉ.

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

## Lưu ý

- **Simulator nghiêm ngặt hơn nhiều thiết bị thật:** ô không khai báo trong Point Map luôn trả mã lỗi 02. Nếu một công cụ đọc gộp nhiều ô liền nhau mà đi qua ô trống, nó sẽ bị lỗi — điều này cũng xảy ra với một số thiết bị thật.
- **Hỏi sai số thiết bị**, simulator trả mã lỗi 04; thiết bị thật thường **im lặng tới khi hết thời gian chờ**. Simulator chỉ đúng bằng mô tả dùng để dựng nó.
- Simulator mở Modbus ở các IP loopback `127.0.1.x` (Linux dùng được cả dải `127.x.x.x` không cần cấu hình; macOS phải thêm alias cho `lo0`).
- Cổng 5020, 5080 hoặc 8080 đang bận thì báo lỗi khi khởi động — tắt chương trình đang dùng cổng đó, hoặc đổi địa chỉ trong `edge/point-map/environments/lab.yml` (Modbus), `make sim ARGS="--control-port ..."` (điều khiển), `make collect ARGS="--web-port ..."` (trang xem).
