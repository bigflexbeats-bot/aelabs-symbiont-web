(() => {
  const list = document.getElementById("active-task-list");
  const timestamp = document.getElementById("active-task-timestamp");
  const labels = {
    csv: "Запись CSV", git_log: "Запись GIT LOG", git_web: "Публикация GIT WEB",
    ini: "Чтение INI", serial: "Опрос COM", station: "Связь с титростанцией",
    titration: "Подача реагента", selftest: "Самопроверка станции", diagnostics: "Диагностика комплекса", alarms: "Активные аварии"
  };
  const states = {active: "Работает", off: "Остановлено", waiting: "Ожидание",
                  paused: "Приостановлено", error: "Ошибка"};
  const descriptions = {
    csv: {active:"Запись идёт", paused:"Пауза · нет свежих данных INI", waiting:"Ожидание первой записи"},
    git_log: {active:"Запись подтверждена", waiting:"Ожидание записи", off:"Не настроено"},
    git_web: {active:"Снимок получен"},
    ini: {off:"Источник не подключён", active:"Данные поступают"},
    station: {active:"Телеметрия поступает", off:"Отключена", waiting:"Ожидание телеметрии"},
    titration: {active:"Подача идёт", off:"Насосы остановлены"},
    selftest: {active:"Выполняется", off:"Не запущена"},
    alarms: {off:"Нет активных", error:"Есть активные"}
  };
  const time = value => new Date(value * 1000).toLocaleTimeString("ru-RU");
  let snapshot;
  let previousFresh;
  function render() {
    const observed = snapshot?.observed_at;
    const age = Date.now() / 1000 - observed;
    const fresh = Number.isFinite(observed) && age >= -30 && age < 40;
    timestamp.textContent = fresh ? "Обновлено в " + time(observed) :
      Number.isFinite(observed) ? "Статусы устарели · последний снимок в " + time(observed) :
      "Ожидание статусов из AE AUTOLABS";
    list.replaceChildren();
    for (const [key, label] of Object.entries(labels)) {
      const task = snapshot?.[key];
      const state = fresh && Object.hasOwn(states, task?.state) ? task.state : "unknown";
      const details = [];
      if (state !== "unknown") {
        if (key === "serial" && Number.isInteger(task.configured)) details.push(task.online + " из " + task.configured + " на связи");
        if (key === "alarms" && Number.isInteger(task.count)) details.push(String(task.count));
        if (Number.isFinite(task.last_success_at)) details.push("последняя запись " + time(task.last_success_at));
        if (Number.isFinite(task.interval_s) && state !== "off") details.push("интервал " + task.interval_s + " с");
      }
      const row = document.createElement("div");
      const name = document.createElement("dt");
      const value = document.createElement("dd");
      name.textContent = label;
      value.dataset.state = state;
      value.textContent = [descriptions[key]?.[state] ?? states[state] ?? "Нет свежих данных", ...details].join(" · ");
      row.append(name, value);
      list.append(row);
    }
    previousFresh = fresh;
  }
  window.AELabsTasks = {update(value) { snapshot = value; render(); }};
  setInterval(() => {
    if (previousFresh && Date.now() / 1000 - snapshot.observed_at >= 40) render();
  }, 1000);
  render();
})();
