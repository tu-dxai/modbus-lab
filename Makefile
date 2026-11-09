PY = .venv/bin/python
# Các module import nhau theo tên ngắn (codec, sim, collector, write, point_map, modbus_io, i18n); khai báo nơi tìm ở đây.
# pytest.ini giữ cùng danh sách này.
export PYTHONPATH := tools/codec:tools/simulator:tools/dashboard:edge/write-service:edge/point-map:edge/modbus:i18n

.PHONY: help setup setup-uv sim set get writes reset collect once write test i18n-export

help:
	@echo "Cài đặt"
	@echo "  make setup         cài thư viện vào .venv (cần Python 3.10 trở lên)"
	@echo "  make setup-uv      cài bằng uv, tự tải Python 3.12 riêng cho dự án"
	@echo ""
	@echo "Simulator (thiết bị giả)"
	@echo "  make sim           chạy simulator, giá trị đứng yên; trang điều khiển http://localhost:5080"
	@echo "                     ARGS=--noise để thêm nhiễu và độ trôi"
	@echo "  make set P=dong-ho-dien-01.dien_ap V=231.5   đặt giá trị cho thiết bị giả"
	@echo "  make get [P=...]   xem giá trị hiện tại của simulator"
	@echo "  make writes [P=...]  xem các lệnh ghi client đã gửi tới"
	@echo "  make reset         về giá trị khởi đầu, xóa nhật ký lệnh ghi"
	@echo "  Simulator ở địa chỉ khác: SIM_URL=http://host:5080 make set ..."
	@echo ""
	@echo "Đọc và ghi (mặc định môi trường lab; ARGS=\"--env site\" để dùng thiết bị thật)"
	@echo "  make collect       chạy collector, trang xem số liệu http://localhost:8080"
	@echo "  make once          đọc một lượt rồi thoát"
	@echo "  make write P=bess-01.che_do V=1   ghi qua rào chắn, đọc lại xác nhận"
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

reset:
	$(PY) tools/simulator/simctl.py reset

collect:
	$(PY) tools/dashboard/collector.py $(ARGS)

once:
	$(PY) tools/dashboard/collector.py --once $(ARGS)

write:
	$(PY) edge/write-service/write.py $(P) $(V) $(ARGS)

test:
	.venv/bin/pytest -v

i18n-export:
	$(PY) i18n/export.py
