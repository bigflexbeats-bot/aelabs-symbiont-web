(() => {
  "use strict";
  const status = document.getElementById("station-status");
  const values = document.getElementById("station-values");
  let station = null;

  const shown = (value, unit = "") => Number.isFinite(value) ? value + unit : "—";
  const pair = (a, b, unit) => shown(a, unit) + " / " + shown(b, unit);
  const pump = (on, pct) => on === true ? "Вкл. · " + shown(pct, " %") : on === false ? "Выкл." : "—";

  function render() {
    const heartbeat = Date.parse(station?.heartbeat_at);
    const age = Date.now() - heartbeat;
    const fresh = station?.telemetry_fresh === true && age >= -5000 && age < 15000;
    status.textContent = !station ? "Телеметрия станции недоступна"
      : !station.serial_online ? "COM станции отключён"
      : fresh ? "Станция на связи" : "Телеметрия устарела или отсутствует";
    values.replaceChildren();
    if (station) {
      const rows = [
        ["Режим", ({manual: "Ручной", semi: "Полуавтомат", auto: "Автомат"})[station.mode] ?? "—"],
        ["Прошивка", station.firmware ?? "—"],
        ["Аварийный стоп", fresh ? station.estop ? "Активен" : "Снят" : "—"],
        ["Насос щёлочи", fresh ? pump(station.base_running, station.base_pct) : "—"],
        ["Насос кислоты", fresh ? pump(station.acid_running, station.acid_pct) : "—"],
        ["Щёлочь · pH пуск / стоп", pair(station.base_start_ph, station.base_stop_ph, "")],
        ["Кислота · pH пуск / стоп", pair(station.acid_start_ph, station.acid_stop_ph, "")],
        ["Щёлочь · доза / пауза", pair(station.base_dose_s, station.base_pause_s, " с")],
        ["Кислота · доза / пауза", pair(station.acid_dose_s, station.acid_pause_s, " с")],
      ];
      for (const [label, value] of rows) {
        const dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = label;
        dd.textContent = value;
        values.append(dt, dd);
      }
    }

  }

  window.AELabsStation = { update(next) { station = next ?? null; render(); } };
  setInterval(render, 1000);
})();
