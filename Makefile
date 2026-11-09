PY = .venv/bin/python
# Các module import nhau theo tên ngắn (codec, sim, collector, write, point_map, modbus_io); khai báo nơi tìm ở đây.
# pytest.ini giữ cùng danh sách này.
export PYTHONPATH := tools/codec:tools/simulator:tools/dashboard:edge/write-service:edge/point-map:edge/modbus

.PHONY: help setup setup-uv sim set get writes reset collect once write test

help:
	@echo "make setup      cai thu vien (can Python >= 3.10)"
	@echo "make setup-uv   cai bang uv, tu tai Python 3.12"
	@echo "make sim        chay simulator (gia tri dung yen), dieu khien tai http://localhost:5080"
	@echo "                ARGS=--noise de them nhieu va do troi"
	@echo "make set P=dong-ho-dien-01.dien_ap V=231.5   dat gia tri thiet bi gia"
	@echo "make get [P=...]                             xem gia tri hien tai cua simulator"
	@echo "make writes [P=...]                          xem cac lenh ghi client da gui"
	@echo "make reset                                   ve gia tri khoi dau, xoa nhat ky"
	@echo "make collect    chay collector, xem tai http://localhost:8080"
	@echo "make once       doc mot luot roi thoat"
	@echo "make write P=bess-01.che_do V=1   ghi qua rao chan"
	@echo "make test       chay kiem thu tu dong"
	@echo "Them tham so cho sim/collect/once qua ARGS, vd: make collect ARGS=\"--web-port 8090\""
	@echo "Simulator o dia chi khac: SIM_URL=http://host:5080 make set ..."

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
