PY = .venv/bin/python
# Các module import nhau theo tên ngắn (codec, sim, collector, write, point_map, modbus_io, i18n); khai báo nơi tìm ở đây.
# pytest.ini giữ cùng danh sách này.
export PYTHONPATH := tools/codec:tools/simulator:tools/dashboard:edge/write-service:edge/point-map:edge/modbus:edge/snmp:edge/collectors/telegraf:edge/collectors/bacnet:i18n

.PHONY: help setup setup-uv sim set get writes frames auto reset collect once write audit telegraf test i18n-export

help:
	@echo "Cài đặt"
	@echo "  make setup         cài thư viện vào .venv (cần Python 3.10 trở lên)"
	@echo "  make setup-uv      cài bằng uv, tự tải Python 3.12 riêng cho dự án"
	@echo ""
	@echo "Simulator (thiết bị giả)"
	@echo "  make sim           chạy simulator, trang điều khiển http://localhost:5080"
	@echo "                     giá trị chỉ đổi khi đặt bằng tay; ARGS=\"--auto 5\" để tự thay đổi mỗi 5 giây"
	@echo "  make set P=dong-ho-dien-01.dien_ap V=231.5   đặt giá trị cho thiết bị giả"
	@echo "  make get [P=...]   xem giá trị hiện tại của simulator"
	@echo "  make writes [P=...]  xem các lệnh ghi client đã gửi tới"
	@echo "  make frames [D=thiết-bị]  xem khung tin thô Modbus / SNMP / BACnet: từng byte gửi và nhận, kèm giải nghĩa"
	@echo "  make auto [S=5]    xem / đặt tự thay đổi giá trị mỗi S giây (S=0: chỉ đặt bằng tay)"
	@echo "  make reset         về giá trị khởi đầu, xóa nhật ký lệnh ghi"
	@echo "  Simulator ở địa chỉ khác: SIM_URL=http://host:5080 make set ..."
	@echo ""
	@echo "Đọc và ghi (mặc định môi trường lab; ARGS=\"--env site\" để dùng thiết bị thật)"
	@echo "  make collect       chạy collector, trang http://localhost:8080; đọc khi bấm nút (phím R)"
	@echo "                     ARGS=\"--interval 2\" để tự đọc mỗi 2 giây như edge chạy thật"
	@echo "  make once          đọc một lượt rồi thoát"
	@echo "  make write P=bess-01.che_do V=1   ghi qua rào chắn, đọc lại xác nhận"
	@echo "  make write P=crah-01.diem_dat_nhiet V=relinquish   BACnet: nhả lệnh ở mức ưu tiên của điểm"
	@echo "  make audit         xem nhật ký kiểm toán lệnh ghi (ai ghi gì, lúc nào, kết quả)"
	@echo "  make telegraf [ENV=site]  sinh cấu hình Telegraf từ Point Map (edge/collectors/telegraf/)"
	@echo ""
	@echo "Kiểm thử và bản dịch"
	@echo "  make test          chạy kiểm thử tự động"
	@echo "  make i18n-export   xuất mọi cặp vi/ja ra bảng TSV để người duyệt bản dịch"
	@echo ""
	@echo "Thêm tham số cho sim/collect/once/write qua ARGS, ví dụ: make collect ARGS=\"--web-port 8090\""

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

setup-uv:
	uv venv --python 3.12 && uv pip install -r requirements.txt

sim:
	$(PY) tools/simulator/sim.py $(ARGS)

set:
	$(PY) tools/simulator/simctl.py set $(P) $(V)

get:
	$(PY) tools/simulator/simctl.py get $(P)

writes:
	$(PY) tools/simulator/simctl.py writes $(if $(P),--point $(P))

frames:
	$(PY) tools/simulator/simctl.py frames $(if $(D),--device $(D)) $(ARGS)

auto:
	$(PY) tools/simulator/simctl.py auto $(S)

reset:
	$(PY) tools/simulator/simctl.py reset

collect:
	$(PY) tools/dashboard/collector.py $(ARGS)

once:
	$(PY) tools/dashboard/collector.py --once $(ARGS)

write:
	$(PY) edge/write-service/write.py $(P) $(V) $(ARGS)

audit:
	$(PY) edge/write-service/audit.py $(ARGS)

telegraf:
	$(PY) edge/collectors/telegraf/generate.py --env $(or $(ENV),site) $(ARGS)

test:
	.venv/bin/pytest -v

i18n-export:
	$(PY) i18n/export.py
