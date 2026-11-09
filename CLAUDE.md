# Total DCIM — Lớp thu thập dữ liệu tại edge (Modbus, BACnet, SNMP)

## Bối cảnh

- Hệ thống DCIM cho trung tâm dữ liệu AI dạng container. Mỗi container có một **Edge Site Stack** chạy độc lập (thu thập, cảnh báo tại chỗ, vẫn chạy khi mất WAN). Trung tâm đặt trên AWS Tokyo.
- Công nghệ đã thống nhất: **Telegraf** đọc SNMP và Modbus tại edge; **collector Python** đọc BACnet; backend **Rails**; frontend **Nuxt**; **PostgreSQL**; gửi số liệu lên trung tâm qua **MQTT TLS**.
- Repo này bắt đầu từ một lab học tập (`modbus-lab`): simulator, collector mẫu, bộ giải mã byte order, công cụ ghi có rào chắn, 16 bài kiểm thử MB-xx.

## Nguyên tắc bắt buộc

1. **Point Map (`devices.yml`) là nguồn dữ liệu duy nhất.** Cấu hình Telegraf, simulator và bộ kiểm thử đều sinh ra hoặc đọc từ Point Map. Không viết tay lặp lại thông tin thiết bị ở nơi khác.
2. **Byte order cấu hình theo từng thiết bị**, hỗ trợ đủ ABCD, CDAB, BADC, DCBA. Hàm `convert_from_registers` của pymodbus chỉ đảo thứ tự word — dùng `codec.py` cho BADC và DCBA.
3. **pymodbus ghim bản 3.16.2.** Dùng `SimData` và `SimDevice`; **không dùng** `ModbusDeviceContext`, `ModbusSequentialDataBlock`, `ModbusServerContext` (đã lỗi thời, bị gỡ ở bản 4). Tham số chỉ định thiết bị là `device_id`, không phải `slave`.
4. **Mọi lệnh ghi đi qua write-service:** chỉ điểm `writable`, giá trị nằm trong `allowed` hoặc khoảng cho phép, đọc trạng thái trước khi ghi, ghi, đọc lại xác nhận, ghi nhật ký kiểm toán. Với BACnet: ghi kèm mức ưu tiên đã cấu hình và luôn nhả lệnh (relinquish) khi xong.
5. **Kiểm thử chỉ chạy với simulator**, không bao giờ kết nối hay ghi lên thiết bị thật.
6. **An toàn không phụ thuộc trung tâm hay LLM:** luật cảnh báo khẩn cấp phải chạy được tại edge khi mất kết nối.

## Cấu trúc repo hướng tới

```
edge/
  point-map/        devices.yml theo từng site + schema và bộ kiểm tra
  collectors/
    telegraf/       cấu hình SINH TỰ ĐỘNG từ Point Map
    bacnet/         collector Python, dùng lại codec
  write-service/    rào chắn, phân quyền, nhật ký kiểm toán
tools/
  simulator/        Modbus (đã có), BACnet, SNMP — cùng đọc Point Map
  codec/
tests/
  acceptance/       MB-xx, BN-xx, SN-xx chạy với simulator
```

## Quy ước

- Python 3.10 trở lên, có type hints, kiểm thử bằng pytest.
- Tên biến, hàm, file bằng **tiếng Anh**; comment và tài liệu được viết tiếng Việt.
- Mỗi bài kiểm thử mang mã khớp tài liệu nghiên cứu: `test_mb05_...`, `test_bn02_...`, `test_sn03_...`.
- Không thêm thư viện mới khi chưa hỏi.
- Mỗi thay đổi phải giữ `make test` qua toàn bộ.

## Lệnh

- `make setup` — cài thư viện
- `make sim` — chạy simulator
- `make test` — chạy kiểm thử

## Khi không chắc chắn

Hỏi lại thay vì đoán, đặc biệt với: địa chỉ thanh ghi, byte order, hệ số tỷ lệ, kiểu có dấu hay không dấu, mức ưu tiên BACnet, và mọi thứ liên quan tới lệnh ghi. Một con số sai trong Modbus không báo lỗi — nó chỉ âm thầm sai.
