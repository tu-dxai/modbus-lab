# Modbus Lab — bàn thử Modbus, SNMP, BACnet trên máy của bạn<br>Modbus Lab — 手元の PC で動く Modbus・SNMP・BACnet テストベンチ

> Tài liệu song ngữ: mỗi đoạn tiếng Việt đi ngay trước bản tiếng Nhật; bảng ghi hai dòng trong một ô; chú thích trong
> code ghi `tiếng Việt / 日本語`. Sửa một bên thì sửa luôn bên kia. Bản tiếng Nhật cần người Nhật duyệt.
>
> 本書はベトナム語・日本語の併記です。各段落はベトナム語の直後に日本語が続き、表は 1 セルに 2 行、コード内のコメントは
> `ベトナム語 / 日本語` の形式です。片方を修正したら、もう片方も必ず修正してください。日本語版はネイティブによる確認が必要です。

Bàn thử để kiểm phần mềm edge **trước khi chạm vào thiết bị thật**: simulator đóng vai thiết bị, giá trị do người
kiểm thử đặt và đứng yên tới khi đổi; simulator ghi lại mọi lệnh ghi client gửi tới (kể cả lệnh bị từ chối) để kiểm
"với đầu vào X, client có ghi đúng Y vào đúng thiết bị không". Thiết bị giả nói đủ bốn kiểu kết nối của container:
**Modbus TCP** (đồng hồ điện sau gateway, pin BESS), **Modbus RTU** qua cổng serial ảo (đồng hồ RS-485), **SNMP**
(UPS) và **BACnet/IP** (điều hòa CRAH, ghi kèm mức ưu tiên và nhả lệnh). Kèm collector mẫu có trang web, công cụ ghi
có rào chắn và nhật ký kiểm toán, Telegraf thật (Docker) đọc thiết bị theo cấu hình sinh từ Point Map, bộ kiểm tra Point Map, sơ đồ DC (EPMS, BMS, edge, DCIM) và 375 bài kiểm thử
tự động. Hai trang web hiển thị song ngữ **tiếng Việt / tiếng Nhật**.

エッジソフトウェアを**実機に触れる前に**検証するためのテストベンチです。シミュレーターが機器の役を務め、値はテスト担当者が
設定し、変更するまで固定されます。シミュレーターはクライアントから届いたすべての書き込み（拒否されたものを含む）を記録し、
「入力 X に対して、クライアントは正しい機器に正しく Y を書き込んだか」を検証できます。模擬機器はコンテナの 4 種類の接続方式を
すべて話します：**Modbus TCP**（ゲートウェイ配下の電力計、BESS 蓄電池）、仮想シリアルポート経由の **Modbus RTU**
（RS-485 電力計）、**SNMP**（UPS）、**BACnet/IP**（空調機 CRAH。優先度付き書き込みと指令の解除）。さらに Web 画面付きの
サンプルコレクター、ガードと監査ログ付きの書き込みツール、Point Map から生成した設定で機器を読む実際の Telegraf（Docker）、
Point Map チェッカー、DC 構成図（EPMS、BMS、エッジ、DCIM）、375 件の自動テストを含みます。2 つの Web 画面は
**ベトナム語／日本語**の 2 言語表示です。

## Có gì trong thư mục<br>フォルダー構成

| Đường dẫn<br>パス | Vai trò<br>役割 |
|---|---|
| `edge/point-map/devices.yml` | **Point Map** của site — địa chỉ thật (host, port, device_id) từng thiết bị, ô nhớ, kiểu dữ liệu, byte order, hệ số, cảnh báo<br>サイトの **Point Map** — 各機器の実アドレス（host、port、device_id）、レジスタ、データ型、バイト順、係数、警報 |
| `edge/point-map/environments/lab.yml` | Ánh xạ từng địa chỉ thật sang simulator trên máy này (môi trường mặc định)<br>各実アドレスをこの PC 上のシミュレーターに対応付け（デフォルト環境） |
| `edge/point-map/point_map.py` | Đọc Point Map, áp môi trường, **kiểm tra**; mọi công cụ gọi khi khởi động, có lỗi thì báo hết rồi dừng<br>Point Map の読み込み、環境の適用、**検証**。全ツールが起動時に呼び出し、エラーがあればすべて報告して停止 |
| `edge/modbus/modbus_io.py` | Đọc điểm và quản lý kết nối: một kết nối cho mỗi `host:port` hoặc cổng serial, thiết bị cùng gateway/bus dùng chung; điểm SNMP/BACnet chuyển sang module tương ứng<br>計測点の読み取りと接続管理：`host:port` またはシリアルポートごとに 1 接続、同じゲートウェイ／バスの機器は共有。SNMP／BACnet の計測点は対応モジュールへ委譲 |
| `edge/modbus/async_bridge.py` | Vòng lặp asyncio chạy nền để code đồng bộ gọi thư viện async (pysnmp, bacpypes3)<br>同期コードから非同期ライブラリ（pysnmp、bacpypes3）を呼ぶためのバックグラウンド asyncio ループ |
| `edge/snmp/snmp_io.py` | Đọc điểm SNMP (GET theo OID, v1/v2c)<br>SNMP 計測点の読み取り（OID で GET、v1/v2c） |
| `edge/collectors/bacnet/bacnet_io.py` | Collector Python cho BACnet/IP: đọc presentValue, ghi kèm priority, nhả lệnh (relinquish)<br>BACnet/IP 用 Python コレクター：presentValue の読み取り、priority 付き書き込み、指令の解除（relinquish） |
| `tools/dashboard/telegraf_source.py`, `edge/collectors/telegraf/lab-collector.conf` | **Nguồn Telegraf** của collector: chạy Docker `telegraf:1.32`, nhận số liệu Telegraf gửi về<br>コレクターの **Telegraf ソース**：Docker `telegraf:1.32` を起動し、Telegraf から届くデータを受信 |
| `edge/collectors/telegraf/generate.py` | `make telegraf`: **sinh cấu hình Telegraf** (`inputs.modbus` TCP/RTU, `inputs.snmp`) từ Point Map<br>`make telegraf`：Point Map から **Telegraf 設定を生成**（`inputs.modbus` TCP/RTU、`inputs.snmp`） |
| `i18n/messages.yml` | **Từ điển song ngữ vi/ja**: mọi chữ trên hai trang web và mọi thông báo lỗi trang web hiển thị<br>**vi/ja 対訳辞書**：2 つの Web 画面のすべての文言と、画面に表示するすべてのエラーメッセージ |
| `i18n/i18n.py`, `i18n.js` | Dịch phía server (lỗi mang mã) và phía trình duyệt (nút đổi ngôn ngữ, dịch chữ và lỗi)<br>サーバー側（コード付きエラー）とブラウザー側（言語切替ボタン、文言とエラーの翻訳）の翻訳 |
| `i18n/export.py` | `make i18n-export`: xuất mọi cặp vi/ja ra bảng TSV để người duyệt bản dịch<br>`make i18n-export`：翻訳レビュー用に vi/ja の全ペアを TSV に出力 |
| `edge/write-service/write.py` | Ghi một điểm **qua rào chắn**: chỉ điểm được phép, giá trị trong `allowed` hoặc `[min, max]`, đọc lại xác nhận; BACnet ghi kèm priority và nhả lệnh<br>**ガード経由**で 1 計測点を書き込み：許可された計測点のみ、値は `allowed` または `[min, max]` の範囲内、読み戻し確認。BACnet は priority 付きで書き込み、指令を解除 |
| `edge/write-service/audit.py` | **Nhật ký kiểm toán** lệnh ghi (JSON Lines, chỉ ghi thêm, `var/audit/writes.jsonl`); `make audit`<br>書き込みの**監査ログ**（JSON Lines、追記のみ、`var/audit/writes.jsonl`）。`make audit` |
| `tools/simulator/sim.py` | Simulator: mỗi địa chỉ một thiết bị giả — Modbus TCP, Modbus RTU (serial ảo), SNMP agent, BACnet device<br>シミュレーター：アドレスごとに 1 台の模擬機器 — Modbus TCP、Modbus RTU（仮想シリアル）、SNMP エージェント、BACnet デバイス |
| `tools/simulator/vserial.py` | Cặp cổng serial ảo (pty) thay cho bus RS-485, không cần socat<br>RS-485 バスの代わりとなる仮想シリアルポートのペア（pty）。socat 不要 |
| `tools/simulator/topology.py`, `tools/web/diagram.js` | **Sơ đồ DC**: kiến trúc theo lớp (EPMS, BMS → edge → DCIM) và đơn tuyến điện, dữ liệu từ Point Map<br>**DC 構成図**：階層アーキテクチャ（EPMS、BMS → エッジ → DCIM）と電気の単線結線図。データは Point Map から |
| `tools/simulator/snmp_agent.py`, `bacnet_device.py` | UPS giả (SNMP, UPS-MIB) và CRAH giả (BACnet/IP, mảng ưu tiên 16 mức)<br>模擬 UPS（SNMP、UPS-MIB）と模擬 CRAH（BACnet/IP、16 段階の優先度配列） |
| `tools/simulator/sim_state.py` | Giá trị hiện tại của mọi điểm và **nhật ký lệnh ghi** (nhân chứng)<br>全計測点の現在値と**書き込みログ**（証跡） |
| `tools/simulator/sim_control.py`, `control.html` | Kênh điều khiển HTTP và trang web đặt giá trị, xem lệnh ghi (cổng 5080)<br>HTTP 制御チャネルと、値の設定・書き込み確認用の Web 画面（ポート 5080） |
| `edge/modbus/frames.py` | **Khung tin thô**: bắt từng byte gửi và nhận, tách trường, giải nghĩa ra giá trị điểm đo (FrameLog dùng chung)<br>**生フレーム**：送受信の全バイトを取得し、フィールドに分解、計測点の値まで解釈（共通の FrameLog） |
| `edge/modbus/udp_trace.py`, `edge/snmp/snmp_frames.py`, `edge/collectors/bacnet/bacnet_frames.py` | Bắt byte UDP của SNMP / BACnet và tách trường từng gói<br>SNMP／BACnet の UDP バイトを取得し、パケットごとにフィールドを分解 |
| `tools/simulator/simctl.py` | Điều khiển simulator từ code kiểm thử (`SimControl`) hoặc dòng lệnh (`make set/get/writes/reset`)<br>テストコード（`SimControl`）またはコマンドライン（`make set/get/writes/reset`）からシミュレーターを操作 |
| `tools/codec/codec.py` | Mã hóa, giải mã số theo 4 kiểu byte order<br>4 種類のバイト順による数値のエンコード／デコード |
| `tools/dashboard/collector.py` | Đọc mọi điểm, giải mã, kiểm tra cảnh báo, phục vụ trang web và API JSON (đọc và ghi)<br>全計測点の読み取り、デコード、警報判定、Web 画面と JSON API（読み取り・書き込み）の提供 |
| `tools/dashboard/collector.html` | Trang web của collector: số liệu theo thiết bị, xu hướng, cảnh báo, nút ghi qua rào chắn<br>コレクターの Web 画面：機器ごとの計測値、トレンド、警報、ガード経由の書き込みボタン |
| `tools/web/ui.css`, `ui.js` | Giao diện dùng chung cho hai trang: bố cục một màn hình, cột thiết bị, bảng, màu trạng thái<br>2 つの画面の共通 UI：1 画面レイアウト、機器一覧、表、状態色 |
| `tests/acceptance/` | 20 bài kiểm thử nghiệm thu, mã MB-xx khớp tài liệu nghiên cứu<br>受け入れテスト 20 件。MB-xx の番号は調査資料と一致 |
| `tests/point_map/` | 81 bài kiểm thử bộ kiểm tra Point Map và môi trường, mỗi loại lỗi một bài<br>Point Map と環境のチェッカーのテスト 81 件。エラーの種類ごとに 1 件 |
| `tests/simulator/` | 165 bài kiểm thử simulator: đặt giá trị, tự thay đổi, bật/tắt thiết bị, sơ đồ DC, nhật ký lệnh ghi, khung tin thô (cả SNMP, BACnet), RTU, SNMP, BACnet<br>シミュレーターのテスト 165 件：値の設定、自動変化、機器の電源オン／オフ、DC 構成図、書き込みログ、生フレーム（SNMP、BACnet を含む）、RTU、SNMP、BACnet |
| `tests/tools/` | 70 bài kiểm thử collector: đọc khi bấm, tự đọc, ghi, nhả lệnh BACnet, khung tin phía client, nguồn Telegraf (chạy Telegraf thật), song ngữ<br>コレクターのテスト 70 件：手動読み取り、自動読み取り、書き込み、BACnet の指令解除、クライアント側フレーム、Telegraf ソース（実際の Telegraf を起動）、2 言語表示 |
| `tests/telegraf/` | 9 bài kiểm thử cấu hình Telegraf sinh ra (chỉ kiểm cấu trúc, chưa chạy Telegraf thật)<br>生成された Telegraf 設定のテスト 9 件（構造のみ検証、実際の Telegraf は起動しない） |
| `tests/write_service/` | 18 bài kiểm thử rào chắn và nhật ký kiểm toán: ghi được, bị chặn, bị từ chối, ghi từ web, giá trị lẻ hơn hệ số, BACnet nhả lệnh khi ghi thất bại, nhật ký lỗi<br>ガードと監査ログのテスト 18 件：書き込み成功、ガードで遮断、機器が拒否、Web からの書き込み、係数より細かい値、書き込み失敗時の BACnet 指令解除、監査ログの障害 |
| `tests/translations/` | 12 bài kiểm thử từ điển: đủ vi và ja, khớp tham số, mọi khóa trang web và code dùng đều có<br>辞書のテスト 12 件：vi と ja がそろっている、パラメーターが一致、画面とコードが使う全キーが存在 |
| `tests/conftest.py` | Bật simulator kiểm thử (môi trường lab, cổng 5021), dùng chung cho mọi bài<br>テスト用シミュレーター（lab 環境、ポート 5021）を起動。全テストで共用 |

Các module import nhau theo tên ngắn (`codec`, `sim`, `sim_state`, `simctl`, `collector`, `write`, `audit`, `point_map`, `modbus_io`, `snmp_io`, `bacnet_io`, `generate`, `i18n`). Nơi tìm module khai báo trong
`Makefile` (`PYTHONPATH`) và `pytest.ini` (`pythonpath`), nên hãy chạy qua `make` thay vì gọi thẳng `python`.

モジュール同士は短い名前（`codec`、`sim`、`sim_state`、`simctl`、`collector`、`write`、`audit`、`point_map`、`modbus_io`、`snmp_io`、`bacnet_io`、`generate`、`i18n`）で
import します。モジュールの検索パスは `Makefile`（`PYTHONPATH`）と `pytest.ini`（`pythonpath`）で宣言しているため、`python` を直接呼ばずに `make` 経由で実行してください。

## Cài đặt<br>インストール

**Yêu cầu:** Linux (hoặc WSL2 trên Windows), Python **3.10 trở lên** (pymodbus 3.16.2 cần), `git`, `make`,
`python3-venv`, và mạng để tải thư viện lần đầu. Đã thử trên Ubuntu 24.04 / Python 3.12.
Thư viện (ghim phiên bản trong `requirements.txt`): pymodbus 3.16.2, pyserial 3.5 (RTU), pysnmp 7.1.32 (SNMP),
bacpypes3 0.0.110 (BACnet), pyyaml, pytest, tomli (chỉ cài trên Python 3.10).

**要件：** Linux（または Windows 上の WSL2）、Python **3.10 以上**（pymodbus 3.16.2 の要件）、`git`、`make`、
`python3-venv`、初回のライブラリ取得用のネットワーク。Ubuntu 24.04 / Python 3.12 で動作確認済み。
ライブラリ（`requirements.txt` でバージョン固定）：pymodbus 3.16.2、pyserial 3.5（RTU）、pysnmp 7.1.32（SNMP）、
bacpypes3 0.0.110（BACnet）、pyyaml、pytest、tomli（Python 3.10 のみ）。

```bash
git clone git@github.com:tu-dxai/modbus-lab.git
cd modbus-lab
make setup        # tạo .venv và cài thư viện trong requirements.txt / .venv を作成し requirements.txt のライブラリをインストール
make test         # tự bật simulator riêng ở cổng 5021-5022, không cần chuẩn bị gì thêm / ポート 5021-5022 で専用シミュレーターを自動起動、事前準備は不要
```

Ubuntu chưa có `venv` hay `make`: `sudo apt install -y python3-venv make`.

Ubuntu に `venv` や `make` がない場合：`sudo apt install -y python3-venv make`。

**Máy chỉ có Python cũ** (Ubuntu 20.04 có Python 3.8): dùng `uv`, tự tải Python 3.12 riêng cho dự án,
không đụng Python của hệ thống:

**古い Python しかない PC**（Ubuntu 20.04 は Python 3.8）：`uv` を使うと、プロジェクト専用の Python 3.12 を自動で取得し、
システムの Python には触れません：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # cài uv, mở terminal mới sau đó / uv をインストールし、その後ターミナルを開き直す
make setup-uv
```

**macOS:** chưa chạy thẳng được. Simulator và kiểm thử dùng IP loopback `127.0.1.21`, `.30`, `.40`, `.50`; Linux dùng
được cả dải `127.x.x.x`, còn macOS phải thêm alias trước (mất sau khi khởi động lại máy), ví dụ
`sudo ifconfig lo0 alias 127.0.1.21 up` cho từng IP. Cổng serial ảo dùng pty của Linux. Chưa thử trên macOS.

**macOS：** そのままでは動きません。シミュレーターとテストはループバック IP `127.0.1.21`、`.30`、`.40`、`.50` を使います。
Linux は `127.x.x.x` の全範囲をそのまま使えますが、macOS では事前にエイリアスの追加が必要です（再起動で消えます）。
例：IP ごとに `sudo ifconfig lo0 alias 127.0.1.21 up`。仮想シリアルポートは Linux の pty を使います。macOS では未検証です。

**Windows thuần** (không WSL) không chạy được vì Makefile dùng đường dẫn `.venv/bin`.

**素の Windows**（WSL なし）では、Makefile が `.venv/bin` のパスを使うため動きません。

Các cổng cần trống: 5020 (Modbus TCP), UDP 1161 (SNMP), UDP 47808 (BACnet thiết bị) và 47809 (BACnet client),
5080 (điều khiển simulator), 8080 (trang collector); kiểm thử dùng 5021-5025, 5041 và UDP 47819.

空けておく必要があるポート：5020（Modbus TCP）、UDP 1161（SNMP）、UDP 47808（BACnet 機器）と 47809（BACnet クライアント）、
5080（シミュレーター制御）、8080（コレクター画面）。テストは 5021-5025、5041、UDP 47819 を使います。

## Chạy<br>実行

> **Mới dùng lần đầu?** Cả hai trang có nút **?** (phím `?`) mở hướng dẫn nhanh: trang dùng để làm gì, các bước
> thao tác, thuật ngữ (HR, IR, FC, Unit ID, byte order, hệ số, gateway) và phím tắt. Lần đầu mở trang, hướng dẫn
> tự hiện. Rê chuột lên chữ **HR** / **IR** ở bất kỳ đâu để xem chú thích. Nút **☰** (phím `[`) thu gọn danh sách
> thiết bị; icon **✎** cạnh giá trị để sửa ngay tại chỗ (Enter lưu, Esc hủy); icon **⟳** đọc riêng một điểm.
>
> **初めて使う場合：** どちらの画面にも **?** ボタン（`?` キー）があり、クイックガイドを開けます：画面の用途、操作手順、
> 用語（HR、IR、FC、Unit ID、バイト順、係数、ゲートウェイ）、ショートカットキー。初回表示時はガイドが自動で開きます。
> どこでも **HR** / **IR** の文字にカーソルを合わせると説明が出ます。**☰** ボタン（`[` キー）で機器一覧を折りたたみ、
> 値の横の **✎** アイコンでその場で編集（Enter で保存、Esc で取り消し）、**⟳** アイコンで 1 計測点だけ読み取ります。

**HR và IR** — hai vùng thanh ghi riêng của Modbus:

**HR と IR** — Modbus の 2 つの独立したレジスタ領域：

| | Tên đầy đủ<br>正式名 | Đọc / ghi<br>読み／書き | Lệnh<br>コマンド | Thường dùng cho<br>主な用途 |
|---|---|---|---|---|
| **HR** | Holding Register<br>保持レジスタ | đọc và ghi<br>読み書き可 | đọc FC03, ghi FC06 / FC16<br>読み FC03、書き FC06 / FC16 | cài đặt, lệnh điều khiển (một số hãng đặt cả số đo)<br>設定値、制御指令（計測値を置くメーカーもある） |
| **IR** | Input Register<br>入力レジスタ | chỉ đọc<br>読み取り専用 | đọc FC04<br>読み FC04 | số đo<br>計測値 |

`HR 100` và `IR 100` là hai ô khác nhau.

`HR 100` と `IR 100` は別のレジスタです。

Mở **ba cửa sổ terminal** trong thư mục `modbus-lab`.

`modbus-lab` フォルダーで**ターミナルを 3 つ**開きます。

**1. Bật simulator<br>シミュレーターを起動**

```bash
make sim                   # giá trị chỉ đổi khi đặt bằng tay (khởi đầu ở sim.base của Point Map) / 値は手動設定時のみ変化（初期値は Point Map の sim.base）
make sim ARGS="--auto 5"   # tự thay đổi mỗi 5 giây; đổi được ngay trên trang hoặc bằng make auto S=10 / 5 秒ごとに自動変化。画面上または make auto S=10 ですぐ変更可
```

**Tự thay đổi giá trị** (trang điều khiển: ô *Tự thay đổi* — Tắt / 5 / 10 / 30 giây): mỗi nhịp, điểm có `sim.noise`
dao động quanh giá trị đặt gần nhất trong biên độ ±noise. Đặt nhiệt độ tủ 31,5 °C rồi bật thì nhiệt độ dao động
quanh 31,5. Điểm `writable` (giá trị client ghi vào) không tự đổi. Tắt thì giá trị đứng yên tới khi đặt bằng tay.

**値の自動変化**（制御画面の「自動変化」— オフ / 5 / 10 / 30 秒）：周期ごとに、`sim.noise` を持つ計測点が直近の設定値を中心に
±noise の幅で変動します。盤内温度を 31.5 °C に設定してからオンにすると、31.5 付近で変動します。`writable` の計測点
（クライアントが書き込む値）は自動変化しません。オフにすると、手動で設定するまで値は固定されます。

Điều khiển thiết bị giả tại `http://localhost:5080`: cột trái là thiết bị nhóm theo gateway/địa chỉ (có ô tìm);
bên phải là bảng đặt giá trị cho thiết bị đang chọn, kèm ô **Tự thay đổi**. Lệnh client gửi tới xem ở khung tin
trang collector; khi test client khác thì dùng `make writes` / `make frames`. Hoặc dùng dòng lệnh:

模擬機器の操作は `http://localhost:5080` で行います：左列はゲートウェイ／アドレスごとにまとめた機器一覧（検索欄あり）、
右側は選択中の機器の値を設定する表と「**自動変化**」欄です。クライアントから届いたコマンドはコレクター画面の通信フレームで
確認できます。別のクライアントをテストするときは `make writes` / `make frames` を使います。コマンドラインでも操作できます：

```bash
make set P=dong-ho-dien-01.nhiet_do_tu V=31.5   # tạo tình huống: tủ điện nóng / 状況を作る：分電盤が高温
make get                                         # xem giá trị hiện tại / 現在値を表示
make writes                                      # client đã ghi gì? (P=... để lọc một điểm) / クライアントが何を書いたか（P=... で 1 計測点に絞り込み）
make auto S=10                                   # tự thay đổi mỗi 10 giây (S=0: chỉ đặt bằng tay) / 10 秒ごとに自動変化（S=0：手動設定のみ）
make power D=bess-01 S=off                       # tắt thiết bị (giả lập mất điện); S=on bật lại / 機器をオフ（停電を模擬）、S=on で再びオン
make reset                                       # về giá trị khởi đầu, xóa nhật ký, bật lại mọi thiết bị / 初期値に戻し、ログを消去し、全機器をオン
```

**Bật / tắt thiết bị** (nút **Đang bật / Đã tắt** ở đầu mỗi thiết bị, `make power`, `POST /api/power`): thiết bị
tắt phản ứng như mất điện, theo kiểu kết nối, để kiểm edge xử lý thiết bị mất kết nối:

**機器の電源オン／オフ**（各機器の先頭にある「**電源オン／電源オフ**」ボタン、`make power`、`POST /api/power`）：オフにした機器は
接続方式に応じて停電時と同じ反応をします。エッジが通信断の機器をどう扱うかの検証に使います：

| Thiết bị<br>機器 | Khi tắt, client thấy<br>オフ時にクライアントから見える挙動 |
|---|---|
| Có IP riêng (một mình một `host:port`, ví dụ `bess-01`)<br>専用 IP（`host:port` を単独で使用、例：`bess-01`） | bị từ chối kết nối TCP; kết nối đang mở bị cắt<br>TCP 接続が拒否される。開いている接続は切断される |
| Sau gateway (chung `host:port`, ví dụ `dong-ho-dien-02`)<br>ゲートウェイ配下（`host:port` を共有、例：`dong-ho-dien-02`） | gateway vẫn trả lời: mã lỗi **0B**; thiết bị khác cùng gateway vẫn đọc được<br>ゲートウェイは応答する：例外コード **0B**。同じゲートウェイの他の機器は読み取り可能 |
| RS-485, SNMP, BACnet | không trả lời, chờ hết `timeout`<br>応答なし。`timeout` まで待つ |

Thiết bị tắt không thực thi lệnh nào (lệnh ghi không đổi giá trị; ghi qua gateway được nhật ký ghi lại với mã 0B).
Giá trị đặt lúc thiết bị tắt có hiệu lực khi bật lại. `make reset` bật lại mọi thiết bị. Collector gặp một thiết bị
không trả lời thì bỏ qua các điểm còn lại của thiết bị đó trong lượt ("bỏ qua: ... không trả lời"), để một thiết bị
mất điện không làm cả lượt đọc chờ timeout cho từng điểm.

オフの機器はどのコマンドも実行しません（書き込みでは値が変わらず、ゲートウェイ経由の書き込みは例外コード 0B としてログに
残ります）。オフ中に設定した値は、オンに戻したときに有効になります。`make reset` で全機器がオンに戻ります。コレクターは
応答しない機器があると、その巡回ではその機器の残りの計測点をスキップします（「bỏ qua: ... không trả lời」）。停電した
1 台のために、計測点ごとにタイムアウトを待って巡回全体が遅れることを防ぐためです。

Giá trị được làm tròn đúng như thiết bị thật lưu: đặt `231.55` V vào ô `uint16` hệ số 0.1 thì thiết bị báo `231.6`.
Giá trị không vừa thanh ghi (ví dụ 7000 V > 6553.5) bị từ chối. Điểm chỉ đọc vẫn chỉ đọc đối với client Modbus;
chỉ kênh điều khiển này đặt được chúng.

値は実機が保存するのと同じように丸められます：係数 0.1 の `uint16` レジスタに `231.55` V を設定すると、機器は `231.6` を
返します。レジスタに収まらない値（例：7000 V > 6553.5）は拒否されます。読み取り専用の計測点は Modbus クライアントからは
読み取り専用のままで、設定できるのはこの制御チャネルだけです。

**2. Bật collector<br>コレクターを起動**

```bash
make collect                        # đọc khi bấm nút — mỗi lần bấm là đúng một lượt yêu cầu Modbus / ボタンを押したときに読み取り — 1 回押すとちょうど 1 巡分の Modbus 要求
make collect ARGS="--interval 2"    # tự đọc mỗi 2 giây, giống edge chạy thật / 本番のエッジと同じく 2 秒ごとに自動読み取り
```

Collector **tự tìm thiết bị qua simulator đang chạy**:
- Collector hỏi trang điều khiển của simulator (mặc định `http://127.0.0.1:5080`, đổi bằng `SIM_URL`) xem từng thiết bị đang nghe ở đâu.
- Vì vậy đọc được cả simulator chạy bằng `make sim` (127.0.1.x) lẫn simulator trong Docker của demo A04 (đúng IP site 10.20.0.x).
- Với simulator trong Docker, thiết bị RS-485 bị bỏ qua và có ghi lý do: cổng serial nằm trong container. Collector không mở cổng serial thật của máy này.
- Không kết nối được simulator thì collector tạm dùng `environments/lab.yml` — cả khi simulator đang chạy rồi dừng: collector không giữ địa chỉ simulator cũ (simulator Docker báo địa chỉ site thật).
- Mỗi lượt đọc, collector hỏi lại simulator. Simulator chạy sau collector, hay khởi động lại ở chỗ khác (`make sim` ↔ Docker), thì collector tự theo kịp, không cần khởi động lại.
- Muốn cố định môi trường: `ARGS="--env lab"` hoặc `ARGS="--env site"` (thiết bị thật).

コレクターは**稼働中のシミュレーターから機器を自動で探します**：
- コレクターはシミュレーターの制御画面（デフォルト `http://127.0.0.1:5080`、`SIM_URL` で変更）に、各機器がどこで待ち受けているかを問い合わせます。
- そのため `make sim` で動くシミュレーター（127.0.1.x）も、デモ A04 の Docker 内シミュレーター（サイトと同じ IP 10.20.0.x）も読めます。
- Docker 内のシミュレーターの場合、RS-485 機器は理由を記録したうえでスキップします：シリアルポートがコンテナ内にあるためです。コレクターはこの PC の実シリアルポートを開きません。
- シミュレーターに接続できないときは、一時的に `environments/lab.yml` を使います — 稼働中のシミュレーターが停止した場合も同様で、古いシミュレーターのアドレスは保持しません（Docker のシミュレーターはサイトの実アドレスを返すため）。
- 巡回ごとにシミュレーターへ問い合わせ直します。シミュレーターがコレクターより後に起動しても、別の場所で再起動しても（`make sim` ↔ Docker）、コレクターは再起動なしで自動的に追従します。
- 環境を固定する場合：`ARGS="--env lab"` または `ARGS="--env site"`（実機）。

Mặc định collector **không tự đọc**: bấm **Đọc tất cả / Đọc thiết bị này** (hoặc phím **R**), hay nút **Đọc** trên
từng dòng để gửi yêu cầu riêng một điểm. Nhờ vậy khung tin và lệnh ghi bên simulator khớp đúng từng thao tác khi
kiểm thử. Sau mỗi lượt, trang hiện số điểm đọc được và thời gian (ms); ghi xong thì tự đọc lại thiết bị đó.
Ô **Tự đọc** trên trang bật/tắt đọc định kỳ (2/5/10 giây) không cần khởi động lại.

デフォルトではコレクターは**自動で読み取りません**：「**すべて読み取り／この機器を読み取り**」（または **R** キー）を押すか、
各行の「**読取**」ボタンで 1 計測点だけ要求を送ります。これにより、テスト時にシミュレーター側の通信フレームと書き込みが
操作 1 回ごとに正確に対応します。巡回のたびに、読み取れた計測点数と所要時間（ms）が表示され、書き込み後はその機器を
自動で読み直します。画面の「**自動読み取り**」欄で、再起動なしに定期読み取り（2/5/10 秒）をオン／オフできます。

Trang `http://localhost:8080`: cột trái là thiết bị nhóm theo gateway/địa chỉ, chấm màu cho trạng thái
(xanh bình thường, vàng lỗi đọc, đỏ có cảnh báo); bảng bên phải là điểm đo của thiết bị đang chọn hoặc tất cả.
Đường dẫn giữ thiết bị đang chọn (`#dev=bess-01`) nên gửi cho người khác được. Mỗi điểm có đường xu hướng
của 60 lượt đọc gần nhất. Phím `/` để tìm thiết bị.
Đặt nhiệt độ tủ trên 30 °C (`make set P=dong-ho-dien-01.nhiet_do_tu V=31.5`) để thấy **CẢNH BÁO**.
Điểm có `writable: true` (ví dụ `bess-01.che_do`) có nút ghi ngay trên trang, đi qua cùng rào chắn với `edge/write-service/write.py`.

`http://localhost:8080` の画面：左列はゲートウェイ／アドレスごとの機器一覧で、色付きの点が状態を示します
（緑：正常、黄：読み取りエラー、赤：警報あり）。右側の表は選択中の機器（またはすべて）の計測点です。
URL に選択中の機器が残る（`#dev=bess-01`）ので、そのまま他の人に送れます。各計測点には直近 60 回分のトレンド線が
あります。`/` キーで機器を検索します。
盤内温度を 30 °C 超に設定する（`make set P=dong-ho-dien-01.nhiet_do_tu V=31.5`）と**警報**が出ます。
`writable: true` の計測点（例：`bess-01.che_do`）には画面上に書き込みボタンがあり、`edge/write-service/write.py` と同じガードを通ります。

API JSON: `GET /api/points` (số liệu, cảnh báo, mô tả điểm, lịch sử); `POST /api/read` với `{}`,
`{"device": "bess-01"}` hoặc `{"point": "bess-01.muc_pin"}` để đọc ngay; `POST /api/auto` với `{"interval": 5}`
(0 = tắt); `POST /api/write` với `{"point": "bess-01.che_do", "value": 1}`; `POST /api/relinquish` với
`{"point": "crah-01.diem_dat_nhiet"}` (BACnet: nhả lệnh).
Cổng 8080 bận thì dùng `make collect ARGS="--web-port 8090"`.

JSON API：`GET /api/points`（計測値、警報、計測点の説明、履歴）。即時読み取りは `POST /api/read` に `{}`、
`{"device": "bess-01"}` または `{"point": "bess-01.muc_pin"}`。`POST /api/auto` に `{"interval": 5}`
（0 = オフ）。`POST /api/write` に `{"point": "bess-01.che_do", "value": 1}`。`POST /api/relinquish` に
`{"point": "crah-01.diem_dat_nhiet"}`（BACnet：指令の解除）。
ポート 8080 が使用中なら `make collect ARGS="--web-port 8090"` を使います。

Muốn mở trang từ máy khác (ví dụ chạy trong máy ảo): `make collect ARGS="--web-host 0.0.0.0"`.
Lưu ý: khi mở ra ngoài như vậy, ai vào được trang cũng bấm ghi được (vẫn bị rào chắn giới hạn).

別の PC から画面を開く場合（例：仮想マシン内で実行）：`make collect ARGS="--web-host 0.0.0.0"`。
注意：このように外部へ公開すると、画面にアクセスできる人は誰でも書き込みボタンを押せます（ガードによる制限は有効）。

**3. Thử ghi qua rào chắn<br>ガード経由で書き込みを試す**

```bash
make write P=bess-01.che_do V=1        # được phép: ghi rồi đọc lại xác nhận / 許可：書き込み後に読み戻し確認
make write P=bess-01.che_do V=5        # bị chặn: giá trị không nằm trong danh sách cho phép / 遮断：値が許可リストにない
make write P=dong-ho-dien-01.dien_ap V=999   # bị chặn: điểm chỉ đọc / 遮断：読み取り専用の計測点
make audit                             # ai ghi gì, vào đâu, lúc nào, kết quả (kể cả lệnh bị chặn) / 誰が・何を・どこへ・いつ書いたか、結果（遮断されたものを含む）
```

Mọi lệnh ghi — từ `make write` (`cli:<user>`) hay từ trang collector (`web:<ip>`) — để lại dòng JSON trong
`var/audit/writes.jsonl`: thời điểm, người ghi, môi trường, điểm, địa chỉ thật, giá trị, kết quả
(`attempt` / `written` / `released` / `blocked` / `failed`), giá trị trước và sau, mức ưu tiên BACnet, mã lỗi. File chỉ ghi thêm.
Lệnh được gửi tới thiết bị có hai dòng: `attempt` ngay trước khi gửi (không ghi được dòng này thì lệnh **không được gửi**),
rồi dòng kết quả. Thiết bị đã đổi mà không ghi được dòng kết quả thì báo rõ "ĐÃ ghi vào thiết bị… đừng ghi lại lần nữa"
(web trả 500 kèm `"written": true`), không báo là ghi thất bại.

Rào chắn chỉ cho ghi giá trị thiết bị lưu đúng được: điểm số nguyên có hệ số 0.1 nhận 21.3 nhưng chặn 21.35 (không làm
tròn ngầm). Đọc lại so với đúng số thiết bị lưu (float32 / BACnet REAL: 21.3 lưu thành 21.299999). BACnet: lệnh đã gửi
mà không xác nhận được (không trả lời, đọc lại không khớp vì mức ưu tiên cao hơn đang giữ) thì nhả lệnh ngay ở mức đó,
để nó không âm thầm có hiệu lực khi mức cao hơn nhả ra; nhật ký ghi `relinquished`.

すべての書き込みは — `make write`（`cli:<user>`）からでもコレクター画面（`web:<ip>`）からでも — `var/audit/writes.jsonl` に
JSON 行を残します：日時、書き込み者、環境、計測点、実アドレス、値、結果（`attempt` / `written` / `released` / `blocked` / `failed`）、
書き込み前後の値、BACnet の優先度、エラーコード。ファイルは追記のみです。
機器へ送るコマンドは 2 行になります：送信直前の `attempt`（この行を記録できなければコマンドは**送信しません**）と結果の行です。
機器は変わったのに結果の行を記録できない場合は「機器への書き込みは完了しました…再度書き込まないでください」と明示し
（Web は `"written": true` 付きで 500 を返す）、書き込み失敗とは報告しません。

ガードは機器が正確に保存できる値だけを許可します：係数 0.1 の整数型の計測点は 21.3 を受け付けますが、21.35 は遮断します
（暗黙の丸めはしません）。読み戻しは機器が実際に保存する値と比較します（float32 / BACnet REAL では 21.3 が 21.299999 になる）。
BACnet：送信したのに確認できなかったコマンド（無応答、より高い優先度が値を保持していて読み戻し不一致）は、その優先度で
すぐに解除します。高い優先度が解除されたときに黙って有効にならないようにするためで、ログには `relinquished` を記録します。

**4. Chạy kiểm thử tự động<br>自動テストを実行** (không cần bật simulator, test tự bật ở cổng 5021 / シミュレーターの起動は不要、テストがポート 5021 で自動起動)

```bash
make test
```

## Sơ đồ DC (BMS, EPMS, edge, DCIM)<br>DC 構成図（BMS、EPMS、エッジ、DCIM）

Data center cần điện, làm mát, và người vận hành biết chuyện gì đang xảy ra. Mỗi hệ thống lo một phần:

データセンターには、電力、冷却、そして運用者が今何が起きているかを把握できることが必要です。各システムがその一部を担います：

| Hệ thống<br>システム | Là gì<br>概要 | Trả lời câu hỏi<br>答える問い | Trong lab này<br>この lab では |
|---|---|---|---|
| **EPMS** — Electrical Power Monitoring System | Giám sát điện năng ở mọi chặng: lưới vào, tủ phân phối, UPS, pin, tới rack<br>受電、分電盤、UPS、蓄電池からラックまで、全区間の電力監視 | Điện có đủ, ổn định, còn dự phòng bao lâu?<br>電力は足りているか、安定しているか、バックアップはあとどれだけ持つか？ | 3 đồng hồ điện, BESS, UPS<br>電力計 3 台、BESS、UPS |
| **BMS** — Building Management System | Quản lý tòa nhà: điều hòa, nhiệt độ, độ ẩm, quạt. Khác EPMS: thường **ra lệnh** cho thiết bị, không chỉ đo; hay dùng BACnet<br>建物管理：空調、温度、湿度、ファン。EPMS との違い：計測だけでなく機器に**指令を出す**ことが多く、BACnet をよく使う | Rack có đủ mát không?<br>ラックは十分に冷えているか？ | Điều hòa CRAH 01<br>空調機 CRAH 01 |
| **Edge** | Máy tính trong container: đọc mọi thiết bị, cảnh báo tại chỗ, ghi qua rào chắn, gửi lên trung tâm; vẫn chạy khi mất WAN<br>コンテナ内のコンピューター：全機器の読み取り、現地での警報、ガード経由の書き込み、センターへの送信。WAN 断でも動作 | Container này đang ra sao, kể cả khi mất mạng?<br>このコンテナは今どうなっているか（ネットワーク断の間も）？ | Point Map, Telegraf, collector BACnet, write-service<br>Point Map、Telegraf、BACnet コレクター、write-service |
| **DCIM** — Data Center Infrastructure Management | Gom EPMS, BMS (và thiết bị IT) của mọi container về một nơi: giám sát, cảnh báo, công suất, PUE<br>全コンテナの EPMS、BMS（と IT 機器）を 1 か所に集約：監視、警報、容量、PUE | Toàn bộ hạ tầng đang ra sao?<br>インフラ全体は今どうなっているか？ | Chưa có (Rails + Nuxt, AWS Tokyo)<br>未実装（Rails + Nuxt、AWS 東京） |
| **ITSM** — IT Service Management | Quy trình vận hành: sự cố, yêu cầu, thay đổi, có phiếu và người chịu trách nhiệm<br>運用プロセス：インシデント、リクエスト、変更。チケットと担当者を持つ | Ai xử lý, tới đâu rồi?<br>誰が対応し、どこまで進んだか？ | Chưa có<br>未実装 |

Trên trang, nút **EPMS, BMS, DCIM… là gì?** ở đầu mỗi tab sơ đồ mở phần giải thích đầy đủ (kèm UPS, BESS, CRAH,
tủ phân phối / PDU, sơ đồ đơn tuyến).

画面では、各構成図タブの先頭にある「**EPMS、BMS、DCIM… とは？**」ボタンで詳しい説明（UPS、BESS、CRAH、分電盤／PDU、
単線結線図を含む）を開けます。

Trang simulator (`http://localhost:5080`) có ba tab: **Thiết bị** (bảng đặt giá trị), **Sơ đồ kiến trúc**,
**Sơ đồ đơn tuyến**. Hai sơ đồ cập nhật mỗi giây: giá trị, thiết bị bật / tắt; bấm một thiết bị để mở nó ở tab bảng.

シミュレーター画面（`http://localhost:5080`）には 3 つのタブがあります：「**機器**」（値の設定表）、「**アーキテクチャ図**」、
「**単線結線図**」。2 つの図は毎秒更新されます（値、機器のオン／オフ）。機器をクリックすると表タブでその機器を開きます。

- **Sơ đồ kiến trúc** — dữ liệu đi từ đâu tới đâu: thiết bị hiện trường nhóm theo hệ thống (**EPMS** quản lý điện
  năng: đồng hồ, BESS, UPS · **BMS** quản lý tòa nhà / làm mát: CRAH) → kết nối (gateway, RS-485, IP riêng, SNMP,
  BACnet) → **Edge Site Stack** (Point Map, Telegraf, collector BACnet, write-service, cảnh báo tại chỗ) →
  MQTT TLS → trung tâm (**DCIM**, **ITSM**). Mỗi phần mềm có nhãn **Đã có / Một phần / Chưa có**; phần chưa có
  (MQTT, DCIM, ITSM) vẽ nét đứt, mờ.
- **Sơ đồ đơn tuyến** — đường cấp điện: lưới → tủ phân phối chính → BESS / UPS / tủ phụ → tủ rack → dãy rack GPU,
  kèm đồng hồ đo tại từng tủ và đường làm mát của CRAH. **Đây là sơ đồ GIẢ ĐỊNH** (trang hiện cảnh báo), vì chưa có
  bản vẽ điện thật của site.

- **アーキテクチャ図** — データがどこからどこへ流れるか：システム別にまとめた現場機器（**EPMS** 電力管理：電力計、BESS、UPS ·
  **BMS** 建物管理／冷却：CRAH）→ 接続（ゲートウェイ、RS-485、専用 IP、SNMP、BACnet）→ **Edge Site Stack**（Point Map、
  Telegraf、BACnet コレクター、write-service、現地警報）→ MQTT TLS → センター（**DCIM**、**ITSM**）。各ソフトウェアには
  「**実装済み／一部実装／未実装**」のラベルが付き、未実装の部分（MQTT、DCIM、ITSM）は薄い破線で描かれます。
- **単線結線図** — 給電経路：系統 → 主分電盤 → BESS / UPS / 副分電盤 → ラック盤 → GPU ラック列。各盤の計測器と CRAH の
  冷却経路も示します。サイトの実際の電気図面がまだないため、**これは仮定の図です**（画面に注意表示が出ます）。

Dữ liệu sơ đồ lấy từ Point Map (`system:` trên từng thiết bị, mục `topology:` ở cuối `devices.yml`) và bộ kiểm tra
Point Map bắt lỗi: trỏ tới thiết bị / nút không có, trùng id, vòng cấp điện. Có bản vẽ đơn tuyến thật thì sửa mục
`topology.power` theo bản vẽ rồi đổi `assumed: false`. Phần mềm và trạng thái của chúng nằm ở
`tools/simulator/topology.py` — khi làm xong MQTT / DCIM / ITSM thì đổi trạng thái ở đó. API: `GET /api/topology`.

図のデータは Point Map（各機器の `system:`、`devices.yml` 末尾の `topology:`）から取り、Point Map チェッカーが
存在しない機器／ノードの参照、ID の重複、給電のループを検出します。実際の単線結線図が手に入ったら、図面どおりに
`topology.power` を修正し、`assumed: false` にします。ソフトウェアとその状態は `tools/simulator/topology.py` にあり、
MQTT / DCIM / ITSM が完成したらそこで状態を変更します。API：`GET /api/topology`。

## Modbus RTU, SNMP, BACnet

**Modbus RTU** (`dong-ho-rs485-03`, `transport: rtu`): Point Map khai cổng serial thật (`/dev/ttyUSB0`, 9600 8N1);
môi trường lab ánh xạ sang cổng ảo `var/serial/ttyUSB0` do simulator tạo (cặp pty, không cần socat hay thiết bị).
Khung tin RTU có CRC-16 ở cuối thay cho phần đầu MBAP; trang collector giải nghĩa và báo CRC sai. Một bus chỉ có
một master: đang chạy `make collect` thì `make once` sẽ không mở được cùng cổng.

**Modbus RTU**（`dong-ho-rs485-03`、`transport: rtu`）：Point Map には実シリアルポート（`/dev/ttyUSB0`、9600 8N1）を記述し、
lab 環境ではシミュレーターが作る仮想ポート `var/serial/ttyUSB0` に対応付けます（pty のペア。socat も機器も不要）。
RTU フレームは MBAP ヘッダーの代わりに末尾に CRC-16 があり、コレクター画面で解釈して CRC 異常を表示します。1 つのバスの
マスターは 1 台だけなので、`make collect` の実行中は `make once` で同じポートを開けません。

**SNMP** (`ups-01`, `protocol: snmp`): mỗi điểm là một OID của UPS-MIB (RFC 1628), chỉ đọc; `scale` đổi số nguyên
thiết bị trả sang đơn vị kỹ thuật (ví dụ 545 × 0,1 = 54,5 V). Lab dùng cổng 1161 vì cổng 161 cần quyền root.

**SNMP**（`ups-01`、`protocol: snmp`）：各計測点は UPS-MIB（RFC 1628）の OID 1 つで、読み取り専用です。`scale` で機器が返す
整数を工学単位に変換します（例：545 × 0.1 = 54.5 V）。ポート 161 は root 権限が必要なため、lab ではポート 1161 を使います。

**BACnet/IP** (`crah-01`, `protocol: bacnet`): mỗi điểm là một đối tượng `loại,số` (`analog-input,1`...). Điểm ghi được
(`analog-value`, `binary-value`, `*-output`) phải khai `priority` 1–16. Thiết bị giữ mảng 16 mức ưu tiên: lệnh ở mức
cao nhất thắng; **nhả lệnh** (ghi Null ở đúng mức đó) trả quyền về mức thấp hơn hoặc giá trị mặc định.

**BACnet/IP**（`crah-01`、`protocol: bacnet`）：各計測点は `種類,番号` 形式のオブジェクト（`analog-input,1` など）です。
書き込み可能な計測点（`analog-value`、`binary-value`、`*-output`）には `priority` 1–16 の記述が必須です。機器は 16 段階の
優先度配列を持ち、最も高い優先度の指令が勝ちます。**指令の解除**（その優先度に Null を書く）で、制御はより低い優先度
またはデフォルト値に戻ります。

```bash
make write P=crah-01.diem_dat_nhiet V=21           # ghi ở mức ưu tiên 8, đọc lại xác nhận / 優先度 8 で書き込み、読み戻し確認
make write P=crah-01.diem_dat_nhiet V=relinquish   # nhả lệnh khi xong việc / 作業が終わったら指令を解除
```

Trang collector có icon **↶** cạnh ✎ để nhả lệnh. Trên trang simulator, đặt giá trị cho điểm ghi được = đổi giá trị
mặc định của thiết bị (giá trị khi không ai ra lệnh); `make reset` xóa mọi lệnh như thiết bị vừa khởi động lại.
Client BACnet phải gửi từ cổng khác cổng thiết bị khi chạy cùng máy (Point Map `bacnet.client`, lab `127.0.0.1:47809`).
Ghi vào `analog-input` bị thiết bị từ chối (`write-access-denied`), và lệnh đó vẫn có trong `make writes`.

コレクター画面では ✎ の横の **↶** アイコンで指令を解除します。シミュレーター画面で書き込み可能な計測点に値を設定すると、
機器のデフォルト値（誰も指令していないときの値）が変わります。`make reset` は機器を再起動したときと同じくすべての指令を
消去します。同じ PC で動かす場合、BACnet クライアントは機器と別のポートから送信する必要があります（Point Map の
`bacnet.client`、lab では `127.0.0.1:47809`）。`analog-input` への書き込みは機器に拒否されます（`write-access-denied`）が、
そのコマンドも `make writes` に残ります。

## Telegraf: đọc thiết bị như edge thật<br>Telegraf：本番エッジと同じ方法で機器を読む

```bash
make telegraf                 # môi trường site (địa chỉ thật) -> edge/collectors/telegraf/telegraf.site.conf / site 環境（実アドレス）
make telegraf ENV=lab         # trỏ vào simulator -> telegraf.lab.conf / シミュレーター向け
make telegraf ARGS="--out -"  # in ra màn hình / 画面に出力
```

Mỗi kết nối Modbus (TCP `host:port`, cổng serial RTU, hoặc bus RS-485 qua TCP → `RTUoverTCP`) một khối `inputs.modbus`
(`configuration_type = "request"`, `slave_id`, `byte_order`, `scale` từ Point Map); mỗi agent SNMP một khối `inputs.snmp`.
Thiết bị BACnet được ghi chú ở đầu file và bỏ qua — Telegraf không có plugin BACnet. File sinh ra không đưa vào git;
đừng sửa tay, sửa Point Map rồi sinh lại.

Modbus 接続（TCP `host:port`、RTU シリアルポート、または TCP 経由の RS-485 バス → `RTUoverTCP`）ごとに `inputs.modbus` ブロックを
1 つ（`configuration_type = "request"`、`slave_id`、`byte_order`、`scale` は Point Map から）、SNMP エージェントごとに
`inputs.snmp` ブロックを 1 つ生成します。BACnet 機器はファイル冒頭に注記してスキップします — Telegraf には BACnet
プラグインがありません。生成ファイルは git に入れません。手で編集せず、Point Map を修正して再生成してください。

**Chạy Telegraf thật trên trang collector** — chọn **Nguồn: Telegraf** ở góc trên bảng điểm đo (hoặc
`make collect ARGS="--source telegraf"`). Collector sinh cấu hình từ Point Map vào `var/telegraf/devices.conf` và chạy
container `telegraf:1.32` (cùng bản demo A04, mạng host) với `edge/collectors/telegraf/lab-collector.conf`; Telegraf đọc
mỗi 2 giây và gửi số liệu về collector (`POST /api/telegraf`) thay cho MQTT của edge thật. Mỗi điểm ghi rõ do
**Telegraf** hay **Python** đọc:

**コレクター画面で実際の Telegraf を動かす** — 計測点の表の上部で「**ソース：Telegraf**」を選びます（または
`make collect ARGS="--source telegraf"`）。コレクターは Point Map から `var/telegraf/devices.conf` に設定を生成し、
`edge/collectors/telegraf/lab-collector.conf` を使って `telegraf:1.32` コンテナ（デモ A04 と同じバージョン、host ネットワーク）を
起動します。Telegraf は 2 秒ごとに読み取り、本番エッジの MQTT の代わりにコレクターへデータを送ります（`POST /api/telegraf`）。
各計測点には、**Telegraf** と **Python** のどちらが読んだかが表示されます：

| Thiết bị<br>機器 | Nguồn Telegraf<br>Telegraf ソース時 |
|---|---|
| Modbus TCP (gateway, IP riêng), SNMP<br>Modbus TCP（ゲートウェイ、専用 IP）、SNMP | Telegraf đọc<br>Telegraf が読む |
| Bus RS-485 qua TCP (simulator Docker demo A04: `10.20.0.60:7000`; `make sim ARGS="--serial-tcp /dev/ttyUSB0=HOST:PORT"`)<br>TCP 経由の RS-485 バス（デモ A04 の Docker シミュレーター：`10.20.0.60:7000`。`make sim ARGS="--serial-tcp /dev/ttyUSB0=HOST:PORT"`） | Telegraf đọc (RTUoverTCP)<br>Telegraf が読む（RTUoverTCP） |
| Bus RS-485 ở cổng serial ảo trên máy (`make sim` mặc định)<br>PC 上の仮想シリアルポートの RS-485 バス（`make sim` のデフォルト） | Python đọc — không đưa cổng ảo vào container<br>Python が読む — 仮想ポートはコンテナに渡さない |
| BACnet | Python đọc — Telegraf không có plugin (demo A04 dùng `inputs.execd` chạy script Python)<br>Python が読む — Telegraf にプラグインがない（デモ A04 は `inputs.execd` で Python スクリプトを実行） |

Điểm Telegraf không gửi về quá 3 chu kỳ báo lỗi **"Telegraf không gửi số liệu ... giây"** (thiết bị tắt, không trả lời,
hoặc Telegraf dừng); rê chuột lên dòng trạng thái để xem log lỗi của Telegraf. Ở nguồn Telegraf không có nút Đọc và khung
tin Modbus / SNMP phía collector (byte do Telegraf gửi) — chuyển về **Python** để debug từng lệnh, hoặc xem khung tin
phía thiết bị bằng `make frames`. Ghi vẫn đi qua write-service. Tắt collector (Ctrl+C, SIGTERM) thì container cũng được gỡ.

Telegraf からのデータが 3 周期を超えて届かない計測点は、「**Telegraf からこの計測点のデータが … 秒届いていません**」という
エラーになります（機器がオフ、応答しない、または Telegraf が停止）。状態表示の行にカーソルを合わせると Telegraf のエラーログが
見られます。Telegraf ソースでは「読取」ボタンと、コレクター側の Modbus / SNMP 通信フレーム（Telegraf が送るバイト）はありません —
コマンド単位でデバッグするには **Python** に戻すか、`make frames` で機器側のフレームを確認します。書き込みは引き続き
write-service を通ります。コレクターを停止すると（Ctrl+C、SIGTERM）、コンテナも削除されます。

Cần Docker và image `telegraf:1.32` (`docker pull telegraf:1.32`; đã có nếu từng build demo A04). Kiểm thử chạy Telegraf
thật với simulator và so từng giá trị (byte order, số âm, hệ số, RTU qua TCP); không có Docker thì các bài đó tự bỏ qua.

Docker とイメージ `telegraf:1.32` が必要です（`docker pull telegraf:1.32`。デモ A04 をビルドしたことがあれば取得済み）。
テストは実際の Telegraf をシミュレーターに対して動かし、値を 1 つずつ照合します（バイト順、負の数、係数、TCP 経由の RTU）。
Docker がない場合、それらのテストは自動でスキップされます。

## Xem khung tin thô (Modbus, SNMP, BACnet)<br>生フレームを見る（Modbus、SNMP、BACnet）

**Collector** (bên gửi yêu cầu và nhận phản hồi) bắt từng byte trên đường truyền, trước khi giải mã: trang
`http://localhost:8080`, thẻ **Khung tin** phía dưới — đủ Modbus TCP / RTU, SNMP và BACnet/IP. Mỗi lần bấm Đọc/Ghi là đúng các cặp hỏi/đáp của thao
tác đó; bấm một dòng để xem từng byte. Phía client còn thấy sự cố mà thiết bị không thấy: **không phản hồi**
(gửi đi nhưng hết thời gian chờ) và **không kết nối được**. API: `GET /api/frames` của collector.

**コレクター**（要求を送り応答を受ける側）は、デコード前に回線上の全バイトを取得します：`http://localhost:8080` 画面下部の
「**通信フレーム**」タブ — Modbus TCP / RTU、SNMP、BACnet/IP のすべてに対応。読み取り／書き込みを 1 回押すと、その操作の
要求／応答ペアがそのまま表示され、行をクリックするとバイト単位で見られます。クライアント側では、機器からは見えない障害も
分かります：**応答なし**（送信したがタイムアウト）と**接続不可**。API：コレクターの `GET /api/frames`。

Khi kiểm thử một client khác (ví dụ dự án edge thật của bạn) với simulator, xem khung tin **thiết bị nhận được**
bằng `make frames` hoặc `SimControl().frames()` (API `/api/frames` của simulator):

別のクライアント（例：実際のエッジプロジェクト）をシミュレーターでテストするときは、**機器が受け取った**フレームを
`make frames` または `SimControl().frames()`（シミュレーターの API `/api/frames`）で確認します：

```
#1     11:42:25.245  Đồng hồ điện tủ phân phối 01 @ 10.20.0.21:502 · Đọc holding register (FC03) · 0.16 ms
  Gửi   00 01 | 00 00 | 00 06 | 01 | 03 | 00 00 | 00 01      đọc holding từ ô 0, 1 ô
        Mã giao dịch | Giao thức | Độ dài | Unit ID | Mã lệnh | Ô đầu | Số ô
  Nhận  00 01 | 00 00 | 00 05 | 01 | 03 | 02 | 09 01      trả 1 thanh ghi
        Mã giao dịch | Giao thức | Độ dài | Unit ID | Mã lệnh | Số byte | Dữ liệu
        09 01 = 2305 (×0.1) → Điện áp = 230.5 V
```

Dòng lệnh và log luôn là tiếng Việt, nên ví dụ trên giữ nguyên tiếng Việt.

コマンドラインとログは常にベトナム語のため、上の出力例はベトナム語のままです。主な語：Gửi = 送信、Nhận = 受信、
Mã giao dịch = トランザクション ID、Giao thức = プロトコル ID、Độ dài = 長さ、Mã lệnh = ファンクションコード、
Ô đầu = 開始アドレス、Số ô = レジスタ数、Số byte = バイト数、Dữ liệu = データ、Điện áp = 電圧。

- "Gửi" là client gửi tới thiết bị, "Nhận" là thiết bị trả về. Đủ FC03, FC04, FC06, FC16 và phản hồi lỗi
  (`83 02` = đọc holding lỗi 02, kèm ý nghĩa mã lỗi).
- Dòng cuối nối từ byte thô tới giá trị: thanh ghi nào thuộc điểm nào, số nguyên thô, byte order, hệ số.
- Lọc: `make frames D=bess-01`, `make frames ARGS="--errors"`, `ARGS="--function 16 --limit 50"`. Trang collector
  có lọc theo thiết bị, theo lệnh, chỉ lỗi, và nút tạm dừng.
- Code kiểm thử: `SimControl().frames(device=..., function=..., errors=True)`; API `GET /api/frames`.
- Simulator giữ 500 cặp gần nhất (`make sim ARGS="--frames 2000"` để giữ nhiều hơn); `make reset` xóa cả khung tin.

- 「Gửi」はクライアントから機器への送信、「Nhận」は機器からの応答です。FC03、FC04、FC06、FC16 と例外応答に対応
  （`83 02` = 保持レジスタ読み出しの例外 02。例外コードの意味も表示）。
- 最終行は生バイトから値までをつなぎます：どのレジスタがどの計測点か、生の整数、バイト順、係数。
- 絞り込み：`make frames D=bess-01`、`make frames ARGS="--errors"`、`ARGS="--function 16 --limit 50"`。コレクター画面にも
  機器別、コマンド別、エラーのみの絞り込みと一時停止ボタンがあります。
- テストコード：`SimControl().frames(device=..., function=..., errors=True)`。API `GET /api/frames`。
- シミュレーターは直近 500 ペアを保持します（さらに保持するには `make sim ARGS="--frames 2000"`）。`make reset` でフレームも消去されます。

**SNMP** (mã hóa BER: kiểu | độ dài | giá trị), cột Lệnh hiện `GET`:

**SNMP**（BER エンコード：型 | 長さ | 値）。コマンド列には `GET` と表示されます：

```
  Gửi   30 2b | 02 01 01 | 04 06 70 75 62 6c 69 63 | a0 1e | 02 04 00 fb b4 f8 | 02 01 00 | 02 01 00 | 30 10 | 30 0e | 06 0a 2b 06 01 02 01 21 01 02 04 00 | 05 00
        Gói SNMP | Phiên bản | Community | Loại PDU | Request ID | Mã lỗi | Vị trí lỗi | Danh sách biến | Biến | OID | Giá trị
  Nhận  ... | a2 1f | 02 04 00 fb b4 f8 | ... | 06 0a 2b 06 01 02 01 21 01 02 04 00 | 02 01 64
        64 = 100 (integer) × 1 → Mức pin = 100 %
```

`a0` là GET, `a2` là phản hồi; lệnh và phản hồi ghép theo Request ID. OID không có trên thiết bị trả `80 00`
(noSuchObject) và được tô đỏ.

`a0` は GET、`a2` は応答です。要求と応答は Request ID で対応付けます。機器にない OID は `80 00`（noSuchObject）が返り、
赤で表示されます。（出力内の語：Gói SNMP = SNMP パケット、Phiên bản = バージョン、Loại PDU = PDU 種別、Mã lỗi = エラーコード、
Vị trí lỗi = エラー位置、Danh sách biến = 変数リスト、Biến = 変数、Giá trị = 値、Mức pin = 電池残量）

**BACnet/IP** (BVLC | NPDU | APDU), cột Lệnh hiện `RP` (ReadProperty) / `WP` (WriteProperty):

**BACnet/IP**（BVLC | NPDU | APDU）。コマンド列には `RP`（ReadProperty）/ `WP`（WriteProperty）と表示されます：

```
  Gửi   81 | 0a | 00 1a | 01 | 04 | 02 | 44 | 01 | 0f | 0c 00 80 00 01 | 19 55 | 3e | 44 41 b0 00 00 | 3f | 49 08
        BVLC | Chức năng BVLC | Độ dài gói | NPDU | Điều khiển NPDU | Loại APDU | Kích thước tối đa | Invoke ID | Dịch vụ | Đối tượng | Thuộc tính | Mở giá trị | Giá trị | Đóng giá trị | Mức ưu tiên
  Nhận  81 | 0a | 00 09 | 01 | 00 | 20 | 01 | 0f      xác nhận đã ghi (Simple-ACK)
        41 b0 00 00 = 22.0 (REAL) → Điểm đặt nhiệt độ gió cấp = 22.0 °C
```

`0c 00 80 00 01` là đối tượng analog-value,1; `19 55` là present-value; `44` mở đầu số REAL; `49 08` là mức ưu tiên 8.
Nhả lệnh thì giá trị là `00` (NULL). Thiết bị từ chối thì phản hồi là gói Error, ví dụ `50 .. 0f 91 02 91 28`
= property: write-access-denied. Lệnh và phản hồi ghép theo Invoke ID.

`0c 00 80 00 01` はオブジェクト analog-value,1、`19 55` は present-value、`44` は REAL 値の開始、`49 08` は優先度 8 です。
指令の解除では値が `00`（NULL）になります。機器が拒否すると応答は Error パケットになります。例：`50 .. 0f 91 02 91 28`
= property: write-access-denied。要求と応答は Invoke ID で対応付けます。（出力内の語：Chức năng BVLC = BVLC 機能、
Độ dài gói = パケット長、Điều khiển NPDU = NPDU 制御、Loại APDU = APDU 種別、Kích thước tối đa = 最大サイズ、Dịch vụ = サービス、
Đối tượng = オブジェクト、Thuộc tính = プロパティ、Mở／Đóng giá trị = 値の開始／終了タグ、Mức ưu tiên = 優先度、
xác nhận đã ghi = 書き込み確認、Điểm đặt nhiệt độ gió cấp = 給気温度設定値）

Lọc theo loại lệnh: `make frames ARGS="--function get"`, `--function read-property`, `--function write-property`;
API `?function=get`. pysnmp và bacpypes3 không có hook như `trace_packet` của pymodbus, nên `edge/modbus/udp_trace.py`
bọc hàm gửi / nhận datagram của hai thư viện để chép byte (không đổi byte nào).

コマンド種別での絞り込み：`make frames ARGS="--function get"`、`--function read-property`、`--function write-property`。
API では `?function=get`。pysnmp と bacpypes3 には pymodbus の `trace_packet` のようなフックがないため、
`edge/modbus/udp_trace.py` が両ライブラリのデータグラム送受信関数をラップしてバイトを複製します（バイトは一切変更しません）。

## Song ngữ tiếng Việt / tiếng Nhật<br>ベトナム語／日本語の 2 言語表示

Hai trang web (collector `:8080`, điều khiển simulator `:5080`) có nút **Tiếng Việt / 日本語** ở góc trên. Lựa chọn
được nhớ trên trình duyệt (riêng cho từng trang); lần đầu theo ngôn ngữ trình duyệt; ép bằng `?lang=ja` hoặc `?lang=vi`.

2 つの Web 画面（コレクター `:8080`、シミュレーター制御 `:5080`）の上部に「**Tiếng Việt / 日本語**」ボタンがあります。選択は
ブラウザーに保存され（画面ごとに別々）、初回はブラウザーの言語に従います。`?lang=ja` または `?lang=vi` で強制できます。

- **Chữ giao diện và thông báo lỗi** nằm ở `i18n/messages.yml`. Lỗi server trả về gồm `error` (tiếng Việt, cho dòng lệnh
  và log), `code` và `params`; trang web dịch `code` theo ngôn ngữ đang chọn. Dòng lệnh và log luôn là tiếng Việt.
- **Tên thiết bị, điểm đo, câu cảnh báo** nằm trong Point Map: `label: { vi: ..., ja: ... }` và `message: { vi: ..., ja: ... }`.
  Mã như `dien_ap` vẫn hiện nhỏ bên dưới để đối chiếu.
- `make test` bắt lỗi thiếu một ngôn ngữ, lệch tham số `{tên}` giữa vi và ja, và khóa dùng mà từ điển không có.
- **Bản tiếng Nhật cần người Nhật duyệt** trước khi dùng chính thức: `make i18n-export > ban-dich.tsv` rồi mở bằng Excel.
  Đầu file `i18n/messages.yml` liệt kê các thuật ngữ cần xác nhận (ガード, 計測点, 保持レジスタ...).

- **画面の文言とエラーメッセージ**は `i18n/messages.yml` にあります。サーバーが返すエラーは `error`（ベトナム語、コマンドラインと
  ログ用）、`code`、`params` からなり、Web 画面は選択中の言語で `code` を翻訳します。コマンドラインとログは常にベトナム語です。
- **機器名、計測点名、警報文**は Point Map にあります：`label: { vi: ..., ja: ... }` と `message: { vi: ..., ja: ... }`。
  `dien_ap` のようなコードも照合用に下に小さく表示されます。
- `make test` は、言語の欠落、vi と ja の間の `{名前}` パラメーターの不一致、辞書にないキーの使用を検出します。
- **日本語版は正式利用の前にネイティブの確認が必要です**：`make i18n-export > ban-dich.tsv` で出力し、Excel で開きます。
  `i18n/messages.yml` の冒頭に確認が必要な用語（ガード、計測点、保持レジスタ…）を列挙しています。

## Kiểm thử client (edge) với simulator<br>シミュレーターでクライアント（エッジ）をテストする

Mẫu một bài kiểm thử cho logic điều khiển: tạo tình huống, chờ client phản ứng, kiểm tra lệnh ghi.

制御ロジックのテスト例：状況を作り、クライアントの反応を待ち、書き込みを検証します。

```python
from simctl import SimControl

def test_tu_nong_thi_bess_chuyen_che_do():
    ctl = SimControl()                                  # http://127.0.0.1:5080, hoặc biến SIM_URL / または環境変数 SIM_URL
    ctl.reset()
    mark = ctl.last_seq()                               # bỏ qua mọi lệnh ghi trước mốc này / この時点より前の書き込みは無視
    ctl.set("dong-ho-dien-01.nhiet_do_tu", 31.5)        # đầu vào X / 入力 X
    w = ctl.wait_for_write("bess-01.che_do", timeout=10, since=mark)
    assert w["accepted"] and w["points"][0]["value"] == 1   # client ghi đúng Y / クライアントが正しく Y を書いた
    assert ctl.writes(since=mark) == [w]                # và không ghi gì khác / そして他には何も書いていない
```

Mỗi mục nhật ký (`GET /api/writes`) gồm: `seq`, `at`, `device`, `device_id`, `function` (6 hoặc 16), `address`,
`registers` (giá trị thô), `points` (`key`, `before`, `value` theo đơn vị kỹ thuật), `accepted`, `exception`
(mã lỗi Modbus nếu thiết bị từ chối). Lệnh ghi vào ô không khai báo hoặc sai `device_id` vẫn được ghi lại với
`points` rỗng, để bắt client cấu hình nhầm địa chỉ. Lệnh ghi BACnet có `function: "bacnet-write"`, `address` là đối
tượng (`analog-value,1`), `priority`; nhả lệnh có `value: null`.

ログの各エントリー（`GET /api/writes`）の内容：`seq`、`at`、`device`、`device_id`、`function`（6 または 16）、`address`、
`registers`（生の値）、`points`（`key`、`before`、工学単位の `value`）、`accepted`、`exception`（機器が拒否した場合の
Modbus 例外コード）。未定義のレジスタや誤った `device_id` への書き込みも `points` が空のまま記録され、アドレス設定を誤った
クライアントを検出できます。BACnet の書き込みは `function: "bacnet-write"`、`address` はオブジェクト（`analog-value,1`）、
`priority` を持ち、指令の解除は `value: null` です。

Client viết bằng ngôn ngữ khác thì gọi thẳng HTTP API (xem đầu file `tools/simulator/sim_control.py`).
Để client ở máy hoặc container khác truy cập: tạo một môi trường mới, ví dụ `environments/lan.yml`, ánh xạ mỗi
địa chỉ thật sang IP của máy chạy simulator với **cổng khác nhau** (`"10.20.0.21:502": "0.0.0.0:5021"`,
`"10.20.0.30:502": "0.0.0.0:5022"`), chạy `make sim ARGS="--env lan --control-host 0.0.0.0"`, và cho client trỏ tới
`IP-máy:5021`, `IP-máy:5022`.

他の言語で書いたクライアントは HTTP API を直接呼びます（`tools/simulator/sim_control.py` の冒頭を参照）。
別の PC やコンテナのクライアントからアクセスさせるには：新しい環境（例：`environments/lan.yml`）を作り、各実アドレスを
シミュレーターを動かす PC の IP と**それぞれ異なるポート**に対応付け（`"10.20.0.21:502": "0.0.0.0:5021"`、
`"10.20.0.30:502": "0.0.0.0:5022"`）、`make sim ARGS="--env lan --control-host 0.0.0.0"` を実行し、クライアントを
`PCのIP:5021`、`PCのIP:5022` に向けます。

Bus RS-485 (thiết bị `transport: rtu`) mặc định là cổng serial ảo. Client ở máy hoặc container khác không mở được cổng này. Muốn đọc từ nơi khác thì mở bus qua TCP, như đặt bus sau một bộ chuyển serial ↔ Ethernet:
`make sim ARGS="--serial-tcp /dev/ttyUSB0=0.0.0.0:7000"`. Cách này:
- dùng khung RTU có CRC, chạy trên TCP (RTU over TCP);
- client mở cổng `socket://IP-máy:7000`, pyserial hỗ trợ sẵn URL này;
- Telegraf đọc bằng `transmission_mode = "RTUoverTCP"`, và `generate.py` tự sinh cấu hình này khi cổng có dạng `socket://`;
- collector `--env auto` tự nhận ra bus qua TCP.

RS-485 バス（`transport: rtu` の機器）はデフォルトでは仮想シリアルポートで、別の PC やコンテナのクライアントからは開けません。
他の場所から読むには、シリアル ↔ Ethernet 変換器の後ろにバスを置くのと同じように、バスを TCP で公開します：
`make sim ARGS="--serial-tcp /dev/ttyUSB0=0.0.0.0:7000"`。この方法では：
- CRC 付きの RTU フレームを TCP 上で使います（RTU over TCP）。
- クライアントは `socket://PCのIP:7000` を開きます。pyserial はこの URL に標準で対応しています。
- Telegraf は `transmission_mode = "RTUoverTCP"` で読み、ポートが `socket://` 形式なら `generate.py` がこの設定を自動生成します。
- コレクターの `--env auto` は TCP 経由のバスを自動で認識します。

Demo A04 dùng cách này để bus RS-485 của simulator trong Docker đọc được từ các container Telegraf và từ máy host.

デモ A04 はこの方法で、Docker 内シミュレーターの RS-485 バスを Telegraf コンテナとホスト PC から読めるようにしています。

## Các bài kiểm thử<br>テスト一覧

| Mã<br>番号 | Kiểm tra gì<br>検証内容 |
|---|---|
| MB-01 | Đọc một ô có giá trị biết trước<br>既知の値を持つレジスタを 1 つ読む |
| MB-02 | Bốn kiểu byte order; thiết bị BESS dùng CDAB, đọc nhầm ABCD ra số sai<br>4 種類のバイト順。BESS は CDAB を使い、ABCD で誤読すると誤った数値になる |
| MB-03 | Cấu hình lệch một ô thì đọc nhầm sang thông số khác<br>設定が 1 アドレスずれると別のパラメーターを読んでしまう |
| MB-04 | Số âm: −2,0 °C đọc nhầm kiểu không dấu ra 6551,6 °C<br>負の数：−2.0 °C を符号なしで誤読すると 6551.6 °C になる |
| MB-05 | Đọc ô không tồn tại → mã lỗi 02<br>存在しないレジスタを読む → 例外コード 02 |
| MB-06 | Hỏi sai số thiết bị → lỗi<br>誤った機器番号に問い合わせる → エラー |
| MB-07 | Mất kết nối → collector báo lỗi từng điểm, không sập<br>通信断 → コレクターは計測点ごとにエラーを報告し、落ちない |
| MB-10 | Ghi hợp lệ và đọc lại; rào chắn chặn ghi sai (ngoài `allowed`, ngoài `[min, max]`, điểm ghi được mà không khai giới hạn, lẻ hơn hệ số); thiết bị tự từ chối ghi ô chỉ đọc<br>正しい書き込みと読み戻し。ガードが誤った書き込みを遮断（`allowed` 外、`[min, max]` 外、制限未定義の書き込み可能点、係数より細かい値）。読み取り専用レジスタへの書き込みは機器自身が拒否 |
| Point Map | Ô nhớ đè nhau (tính cả kiểu 32 bit chiếm 2 ô), byte_order sai, type sai, điểm ghi được thiếu giới hạn, thiếu unit, thiếu trường bắt buộc; host/port/device_id/timeout sai; trùng device_id hoặc khác timeout sau cùng gateway; file môi trường thiếu, thừa, trùng địa chỉ; simulator và collector từ chối khởi động<br>レジスタの重なり（32 ビット型が 2 レジスタを占めることも考慮）、byte_order の誤り、type の誤り、書き込み可能点の制限漏れ、unit の欠落、必須項目の欠落。host/port/device_id/timeout の誤り。同一ゲートウェイ配下での device_id 重複や timeout の不一致。環境ファイルのアドレスの不足・過剰・重複。シミュレーターとコレクターが起動を拒否 |
| Mạng<br>ネットワーク | Gateway phục vụ nhiều thiết bị theo device_id; cùng device_id ở hai địa chỉ là hai thiết bị; thiết bị cùng gateway dùng chung kết nối; một địa chỉ mất kết nối không ảnh hưởng địa chỉ khác<br>ゲートウェイが device_id で複数機器に応答。2 つのアドレスの同じ device_id は別の機器。同じゲートウェイの機器は接続を共有。1 つのアドレスの通信断は他のアドレスに影響しない |
| Simulator<br>シミュレーター | Giá trị đứng yên; đặt giá trị rồi đọc lại qua Modbus đúng kiểu, byte order, hệ số; đặt sai thì không đổi gì; nhật ký ghi lại lệnh được nhận, lệnh vào ô chỉ đọc, ô không khai báo, sai device_id; chờ lệnh ghi; dòng lệnh<br>値が固定される。値を設定して Modbus で読み戻すと型、バイト順、係数が正しい。誤った設定では何も変わらない。ログが受理された書き込み、読み取り専用レジスタ・未定義レジスタ・誤った device_id への書き込みを記録。書き込みの待機。コマンドライン |
| Sơ đồ DC<br>DC 構成図 | Mọi thiết bị thuộc EPMS / BMS; nhóm theo hệ thống và kiểu kết nối; phần mềm có trạng thái; nút đơn tuyến lấy nhãn và điểm theo thiết bị; Point Map báo lỗi trỏ sai, trùng id, vòng cấp điện; thiết bị không tới được bị gỡ khỏi sơ đồ nhưng nút vẫn còn; `GET /api/topology`<br>全機器が EPMS / BMS に属する。システムと接続方式でグループ化。ソフトウェアに状態がある。単線結線図のノードが機器からラベルと計測点を取る。Point Map が誤参照、ID 重複、給電ループを報告。到達できない機器は図から外れるがノードは残る。`GET /api/topology` |
| Bật / tắt<br>電源オン／オフ | Thiết bị IP riêng từ chối kết nối và cắt kết nối đang mở; sau gateway trả 0B, không thực thi lệnh ghi, thiết bị cùng gateway vẫn chạy; RS-485 / SNMP / BACnet im lặng; đặt lại bật lại tất cả; collector bỏ qua phần còn lại của thiết bị không trả lời và không sập khi gặp mã lỗi Modbus<br>専用 IP の機器は接続を拒否し、開いている接続を切断。ゲートウェイ配下は 0B を返し、書き込みを実行せず、同じゲートウェイの機器は動き続ける。RS-485 / SNMP / BACnet は無応答。リセットで全機器がオン。コレクターは応答しない機器の残りをスキップし、Modbus 例外コードでも落ちない |
| web | Trang chính, `GET /api/points`, ghi qua `POST /api/write`: hợp lệ, bị rào chắn chặn (kèm mã lỗi để dịch), yêu cầu sai dạng; `/i18n.json`, `/i18n.js`, `?lang=`<br>メイン画面、`GET /api/points`、`POST /api/write` による書き込み：正常、ガードで遮断（翻訳用のエラーコード付き）、不正な形式の要求。`/i18n.json`、`/i18n.js`、`?lang=` |
| Khung tin<br>通信フレーム | Tách trường đúng byte trên đường truyền (FC03/04/06/16, lỗi, khung hỏng); ghép hỏi/đáp; giải nghĩa byte order, số âm, float; lọc, xóa, giới hạn số cặp; dòng lệnh<br>回線上のバイトどおりのフィールド分解（FC03/04/06/16、例外、壊れたフレーム）。要求／応答の対応付け。バイト順、負の数、float の解釈。絞り込み、消去、ペア数の上限。コマンドライン |
| Khung tin SNMP / BACnet<br>SNMP / BACnet フレーム | Tách trường đúng byte bắt được (GET, phản hồi, noSuchObject, ReadProperty, WriteProperty có ưu tiên, nhả lệnh, Error); gói hỏng không làm sập; bắt ở collector, simulator, khi timeout; lọc theo lệnh<br>取得したバイトどおりのフィールド分解（GET、応答、noSuchObject、ReadProperty、優先度付き WriteProperty、指令の解除、Error）。壊れたパケットでも落ちない。コレクター、シミュレーター、タイムアウト時の取得。コマンド別の絞り込み |
| RTU | Cổng serial ảo; đọc, ghi, CRC đúng và sai; khung tin RTU ở collector và simulator; bus bận<br>仮想シリアルポート。読み取り、書き込み、正しい CRC と誤った CRC。コレクターとシミュレーターの RTU フレーム。バス使用中 |
| SNMP | Point Map (OID, version, community); đọc theo hệ số; OID không có; agent không trả lời; Telegraf `inputs.snmp`<br>Point Map（OID、version、community）。係数付きの読み取り。存在しない OID。エージェント無応答。Telegraf `inputs.snmp` |
| BACnet | Point Map (đối tượng, priority, client); đọc analog/binary; ghi kèm priority rồi nhả lệnh; thiết bị từ chối ghi input; simulator ghi nhận lệnh<br>Point Map（オブジェクト、priority、client）。analog/binary の読み取り。priority 付き書き込みと指令の解除。機器が input への書き込みを拒否。シミュレーターがコマンドを記録 |
| Telegraf thật<br>実際の Telegraf | Telegraf 1.32 trong Docker đọc mọi điểm Modbus TCP, RTU qua TCP, SNMP đúng như simulator; BACnet vẫn Python; đặt giá trị tới được Telegraf; thiết bị tắt thành "cũ"; tắt collector bằng SIGTERM gỡ container<br>Docker 内の Telegraf 1.32 が Modbus TCP、TCP 経由の RTU、SNMP の全計測点をシミュレーターどおりに読む。BACnet は Python のまま。設定した値が Telegraf に届く。オフの機器は「古い」扱い。SIGTERM でコレクターを止めるとコンテナが削除される |
| Telegraf | Một khối cho mỗi kết nối; TCP và RTU; byte order, slave_id, scale; SNMP; bỏ qua BACnet<br>接続ごとに 1 ブロック。TCP と RTU。バイト順、slave_id、scale。SNMP。BACnet はスキップ |
| Kiểm toán<br>監査 | Dòng `attempt` trước khi gửi; ghi được, bị chặn, bị thiết bị từ chối, nhả lệnh; ghi từ web kèm địa chỉ người ghi; không ghi được nhật ký thì không gửi lệnh; ghi xong mà nhật ký lỗi thì báo thiết bị đã đổi<br>送信前の `attempt` 行。書き込み成功、遮断、機器による拒否、指令の解除。Web からの書き込みは書き込み者のアドレス付き。ログに記録できなければ送信しない。書き込み後にログが失敗したら機器が変わったことを報告 |
| Bản dịch<br>翻訳 | Mỗi khóa đủ vi và ja, cùng tham số; mọi khóa trang web và code dùng đều có; xuất bảng duyệt<br>各キーに vi と ja がそろい、パラメーターが同じ。画面とコードが使う全キーが存在。レビュー表の出力 |

## Bài tập gợi ý<br>練習課題

1. **Tự gây lỗi byte order.** Copy `edge/point-map/devices.yml` thành `edge/point-map/devices-sai.yml`, đổi `byte_order` của `bess-01` thành `ABCD`.
   Giữ simulator chạy bằng file gốc, rồi chạy `make once ARGS="--config edge/point-map/devices-sai.yml"` — mức pin sẽ ra số vô nghĩa mà không có lỗi nào.
2. **Thêm thiết bị mới.** Thêm một khối vào `edge/point-map/devices.yml`, ví dụ máy lạnh sau gateway điện với `host: 10.20.0.21`, `port: 502`, `device_id: 3`.
   Thiết bị có IP riêng thì thêm một dòng địa chỉ vào `environments/lab.yml`. Không phải sửa code; khởi động lại simulator và collector.
3. **Thêm cảnh báo.** Thêm một dòng vào mục `alerts`, ví dụ điện áp dưới 210 V.

1. **バイト順の誤りを自分で起こす。** `edge/point-map/devices.yml` を `edge/point-map/devices-sai.yml` にコピーし、`bess-01` の `byte_order` を `ABCD` に変えます。
   シミュレーターは元のファイルで動かしたまま `make once ARGS="--config edge/point-map/devices-sai.yml"` を実行すると、電池残量が意味のない数値になり、しかもエラーは一切出ません。
2. **新しい機器を追加する。** `edge/point-map/devices.yml` にブロックを 1 つ追加します。例：電力ゲートウェイ配下の空調機（`host: 10.20.0.21`、`port: 502`、`device_id: 3`）。
   専用 IP の機器なら `environments/lab.yml` にアドレスを 1 行追加します。コードの修正は不要で、シミュレーターとコレクターを再起動するだけです。
3. **警報を追加する。** `alerts` に 1 行追加します。例：電圧が 210 V 未満。

## Quy tắc Point Map<br>Point Map のルール

Simulator, collector và công cụ ghi kiểm tra Point Map khi khởi động; có lỗi thì in hết lỗi kèm tên thiết bị và điểm rồi dừng.

シミュレーター、コレクター、書き込みツールは起動時に Point Map を検証し、エラーがあれば機器名と計測点名付きですべて表示して停止します。

**Kết nối.** Mỗi thiết bị khai báo địa chỉ thật của chính nó:

**接続。** 各機器は自分自身の実アドレスを記述します：

```yaml
- name: dong-ho-dien-01
  host: 10.20.0.21     # IP thật của thiết bị hoặc của gateway / 機器またはゲートウェイの実 IP
  port: 502            # cổng chuẩn Modbus TCP / Modbus TCP の標準ポート
  device_id: 1         # Unit ID / slave address — tra tài liệu hoặc màn hình cài đặt thiết bị / 機器の資料または設定画面で確認
  byte_order: ABCD     # tra tài liệu, KHÔNG đoán / 資料で確認すること、推測は禁止
  timeout: 3           # giây, tùy chọn (mặc định 3); thiết bị thật chậm hơn simulator / 秒、任意（デフォルト 3）。実機はシミュレーターより遅い
```

- `host` khác rỗng, `port` 1–65535, `device_id` 0–255, `timeout` > 0.
- **Thiết bị trùng `host:port` = cùng sau một gateway**: dùng chung một kết nối TCP, `device_id` không trùng và nằm trong
  1–247 (địa chỉ RTU trên bus), cùng `timeout`. Hai địa chỉ khác nhau thì đều dùng `device_id: 1` được.
- Đổi IP gateway thì phải sửa ở mọi thiết bị phía sau; sửa sót một thiết bị thì nó bị coi là thiết bị riêng.

- `host` は空でない、`port` は 1–65535、`device_id` は 0–255、`timeout` > 0。
- **`host:port` が同じ機器 = 同じゲートウェイの配下**：1 本の TCP 接続を共有し、`device_id` は重複せず 1–247
  （バス上の RTU アドレス）の範囲、`timeout` も同じにします。アドレスが異なれば、どちらも `device_id: 1` で構いません。
- ゲートウェイの IP を変えたら、配下のすべての機器を修正します。1 台でも修正漏れがあると、その機器は別の機器として扱われます。

**Môi trường.** Mặc định mọi công cụ chạy `--env lab`: mỗi địa chỉ thật được ánh xạ sang simulator theo
`environments/lab.yml` (mỗi gateway một dòng). Riêng collector (`make collect`, `make once`) mặc định
`--env auto`: lấy ánh xạ từ simulator đang chạy (xem mục bật collector). Chỉ `--env site` mới kết nối địa chỉ thật — ví dụ
`make once ARGS="--env site"`, `make write P=... V=... ARGS="--env site"`. File môi trường phải có đủ mọi địa chỉ,
không thừa, không hai địa chỉ trỏ chung một chỗ.

**環境。** デフォルトでは全ツールが `--env lab` で動き、各実アドレスは `environments/lab.yml`（ゲートウェイごとに 1 行）に従って
シミュレーターに対応付けられます。コレクター（`make collect`、`make once`）だけはデフォルトが `--env auto` で、稼働中の
シミュレーターから対応付けを取得します（コレクターの起動の節を参照）。実アドレスに接続するのは `--env site` のときだけです —
例：`make once ARGS="--env site"`、`make write P=... V=... ARGS="--env site"`。環境ファイルにはすべてのアドレスがそろい、
余分がなく、2 つのアドレスが同じ場所を指さないようにします。

**Dữ liệu.**

**データ。**

- Mỗi thiết bị và mỗi điểm có `label: { vi: "...", ja: "..." }` không rỗng; mỗi cảnh báo có `message: { vi, ja }`
  và phải trỏ tới điểm có thật.
- `byte_order` là `ABCD`, `CDAB`, `BADC` hoặc `DCBA`.
- Mỗi điểm có `name`, `table` (`holding` hoặc `input`), `address`, `type` (`int16`, `uint16`, `int32`, `uint32`, `float32`) và `unit` (để `""` nếu không có đơn vị).
- Hai điểm cùng thiết bị, cùng bảng không được đè ô nhớ của nhau; kiểu 32 bit chiếm 2 ô liền nhau.
- Điểm `writable: true` phải có `allowed: [...]`, hoặc có đủ `min` và `max` (min ≤ max). Rào chắn ghi chặn mọi giá trị ngoài giới hạn đó.
- `address` là số nguyên 0–65535 (kiểu 32 bit: tới 65534); `scale` là số khác 0. Chỉ điểm `holding` mới `writable`.
  Mỗi giá trị trong `allowed`, `min`, `max` và `sim.base` phải lưu đúng được vào thanh ghi: vừa kiểu dữ liệu, và với kiểu
  số nguyên thì là bội số của `scale`.
- **Sơ đồ DC (tùy chọn):** `system:` là `EPMS` hoặc `BMS`. `topology.power`: mỗi nút có `id` không trùng, `kind`
  (`grid`, `panel`, `ups`, `battery`, `load`, `cooling`), `from` trỏ tới nút có thật và không tạo vòng; `device` / `meters`
  trỏ tới thiết bị có thật, mỗi thiết bị ở tối đa một nút; `show` là điểm của thiết bị đó; nút không gắn thiết bị
  phải có `label` song ngữ. `topology.cooling`: `device` có thật, `serves` là nút có thật.
- **RTU:** `transport: rtu`, `serial: { port, baudrate, parity, stop_bits }`, `device_id` 1–247; thiết bị cùng cổng
  serial phải cùng tham số. File môi trường ánh xạ cổng serial ở mục `serial`.
- **SNMP:** `protocol: snmp`, `snmp: { version: "1" | "2c", community }`; mỗi điểm có `oid` (không trùng), `type`
  (`integer`, `gauge32`, `counter32`), chỉ đọc.
- **BACnet:** `protocol: bacnet`, `device_instance` 0–4194302 (không trùng trong site); mỗi điểm có `object` dạng
  `loại,số` (không trùng); điểm ghi được chỉ là `*-value` / `*-output`, có `priority` 1–16, binary dùng `allowed: [0, 1]` (không dùng min/max).
  Site có thiết bị BACnet phải khai `bacnet: { client: "IP/mask:cổng" }`.

- 各機器と各計測点には空でない `label: { vi: "...", ja: "..." }` が必要です。各警報には `message: { vi, ja }` が必要で、
  実在する計測点を指していなければなりません。
- `byte_order` は `ABCD`、`CDAB`、`BADC`、`DCBA` のいずれか。
- 各計測点には `name`、`table`（`holding` または `input`）、`address`、`type`（`int16`、`uint16`、`int32`、`uint32`、`float32`）、`unit`（単位がなければ `""`）が必要です。
- 同じ機器・同じテーブルの 2 つの計測点はレジスタが重なってはいけません。32 ビット型は連続する 2 レジスタを占めます。
- `writable: true` の計測点には `allowed: [...]`、または `min` と `max` の両方（min ≤ max）が必要です。書き込みガードはその範囲外の値をすべて遮断します。
- `address` は 0–65535 の整数（32 ビット型は 65534 まで）、`scale` は 0 以外の数値です。`writable` にできるのは `holding` の計測点のみです。
  `allowed`、`min`、`max`、`sim.base` の各値はレジスタに正確に保存できること：データ型に収まり、整数型では `scale` の倍数であること。
- **DC 構成図（任意）：** `system:` は `EPMS` または `BMS`。`topology.power`：各ノードは重複しない `id`、`kind`
  （`grid`、`panel`、`ups`、`battery`、`load`、`cooling`）を持ち、`from` は実在するノードを指してループを作らないこと。`device` / `meters`
  は実在する機器を指し、各機器は最大 1 つのノードにのみ属します。`show` はその機器の計測点です。機器を持たないノードには
  2 言語の `label` が必要です。`topology.cooling`：`device` は実在、`serves` は実在するノード。
- **RTU：** `transport: rtu`、`serial: { port, baudrate, parity, stop_bits }`、`device_id` 1–247。同じシリアルポートの機器は
  パラメーターをそろえます。環境ファイルでは `serial` の項でシリアルポートを対応付けます。
- **SNMP：** `protocol: snmp`、`snmp: { version: "1" | "2c", community }`。各計測点には `oid`（重複なし）、`type`
  （`integer`、`gauge32`、`counter32`）が必要で、読み取り専用です。
- **BACnet：** `protocol: bacnet`、`device_instance` 0–4194302（サイト内で重複なし）。各計測点の `object` は `種類,番号` 形式
  （重複なし）。書き込み可能なのは `*-value` / `*-output` のみで、`priority` 1–16 が必要。binary は `allowed: [0, 1]` を使う（min/max は不可）。
  BACnet 機器のあるサイトでは `bacnet: { client: "IP/mask:ポート" }` の記述が必要です。

## Lưu ý<br>注意事項

- **Simulator nghiêm ngặt hơn nhiều thiết bị thật:** ô không khai báo trong Point Map luôn trả mã lỗi 02. Nếu một công cụ đọc gộp nhiều ô liền nhau mà đi qua ô trống, nó sẽ bị lỗi — điều này cũng xảy ra với một số thiết bị thật.
- **Hỏi sai số thiết bị**, simulator trả mã lỗi 04; thiết bị thật thường **im lặng tới khi hết thời gian chờ**. Simulator chỉ đúng bằng mô tả dùng để dựng nó.
- Thiết bị trả NaN / vô cực (float32 `0x7FC00000`, nhiều đồng hồ dùng cho "không có dữ liệu") thì collector báo **lỗi đọc**, không coi là số đo — cảnh báo so sánh với NaN luôn sai. Simulator cũng không nhận đặt NaN.
- Simulator mở Modbus ở các IP loopback `127.0.1.x` (Linux dùng được cả dải `127.x.x.x` không cần cấu hình; macOS phải thêm alias cho `lo0`).
- Cổng 5020, 5080 hoặc 8080 đang bận thì báo lỗi khi khởi động — tắt chương trình đang dùng cổng đó, hoặc đổi địa chỉ trong `edge/point-map/environments/lab.yml` (Modbus), `make sim ARGS="--control-port ..."` (điều khiển), `make collect ARGS="--web-port ..."` (trang xem).

- **シミュレーターは多くの実機より厳格です：** Point Map で定義していないレジスタは常に例外コード 02 を返します。連続する複数レジスタをまとめて読むツールが空きレジスタをまたぐとエラーになります — 一部の実機でも同じことが起こります。
- **誤った機器番号に問い合わせると**、シミュレーターは例外コード 04 を返しますが、実機は多くの場合**タイムアウトまで無応答**です。シミュレーターは、それを作るのに使った仕様の分だけしか正確ではありません。
- 機器が NaN／無限大（float32 `0x7FC00000`。多くの電力計が「データなし」に使う）を返すと、コレクターは計測値ではなく**読み取りエラー**として扱います — NaN との比較では警報が常に成立しないためです。シミュレーターも NaN の設定を受け付けません。
- シミュレーターはループバック IP `127.0.1.x` で Modbus を開きます（Linux は `127.x.x.x` の全範囲を設定なしで使えます。macOS は `lo0` へのエイリアス追加が必要）。
- ポート 5020、5080、8080 が使用中だと起動時にエラーになります — そのポートを使っているプログラムを止めるか、`edge/point-map/environments/lab.yml`（Modbus）、`make sim ARGS="--control-port ..."`（制御）、`make collect ARGS="--web-port ..."`（表示画面）でアドレスを変更してください。
