(() => {
  const form = document.getElementById("remote-station-form");
  const result = document.getElementById("remote-station-result");
  const submit = form.querySelector("button");
  const fields = form.elements;
  function syncParameter() {
    const parameter = fields.parameter.value;
    const mode = parameter === "mode";
    const pulse = parameter === "base_pulse_s" || parameter === "acid_pulse_s";
    const noSeconds = mode || parameter === "pump_stop";
    submit.textContent = parameter === "pump_stop" ? "Остановить WEB-подачу" : "Отправить заявку";
    document.getElementById("remote-station-mode").hidden = !mode;
    document.getElementById("remote-station-seconds").hidden = noSeconds;
    fields.value.disabled = noSeconds;
    const ph = parameter.endsWith("_ph");
    document.getElementById("remote-station-unit").textContent = ph ? "pH" : "Секунды";
    fields.value.min = ph ? "0" : pulse || parameter.endsWith("_pause_s") ? "1" : "0.1";
    fields.value.max = ph ? "14" : pulse ? "5" : "120";
  }
  fields.parameter.addEventListener("change", syncParameter);
  syncParameter();
  let pending = null, timer = null;
  window.AELabsRemote = { update(station) {
    form.hidden = !station?.remote_station || station.remote_execution !== "automatic";
    for (const option of fields.parameter.querySelectorAll("[data-pump]")) {
      option.disabled = !station?.remote_pump_control;
    }
    const reply = station?.remote_result;
    if (!pending || reply?.id !== pending) return;
    const waitingForStop = reply.state === "pulse_started";
    if (!waitingForStop) {
      clearTimeout(timer);
      pending = null;
      syncParameter();
    }
    submit.disabled = false;
    result.textContent = ({
      applied: "ESP32 подтвердил изменение",
      mode_applied: "Режим изменён на ПК станции",
      pulse_started: "ESP32 подтвердил запуск. Подача остановится по таймеру на ПК",
      pulse_stopped: "WEB-подача остановлена",
      not_ready: "Заявка отклонена: станция не готова. Для следующей попытки отправьте новую заявку",
      storage_error: "Заявка отклонена: ПК не смог сохранить её в журнале",
      unconfirmed: "Подтверждение ESP32 не получено. Проверьте станцию перед повтором"
    })[reply.state] || "Заявка обработана";
  }};
  form.addEventListener("submit", async event => {
    event.preventDefault();
    submit.disabled = true;
    try {
      if (!window.isSecureContext) throw new Error("Откройте веб-монитор по HTTPS");
      const parameter = fields.parameter.value;
      const value = parameter === "mode" ? fields.mode.value :
        parameter === "pump_stop" ? true : fields.value.valueAsNumber;
      const response = await fetch("/api/titration/request", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({parameter, value}),
        signal: AbortSignal.timeout(35000)
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Заявка не отправлена");
      clearTimeout(timer);
      pending = body.id;
      if (parameter === "base_pulse_s" || parameter === "acid_pulse_s") {
        fields.parameter.value = "pump_stop";
        syncParameter();
        submit.disabled = false;
      }
      result.textContent = "Заявка отправлена. Ожидается ответ станции";
      timer = setTimeout(() => {
        pending = null;
      syncParameter();
        submit.disabled = false;
        result.textContent = "Подтверждение не получено в срок";
      }, parameter === "pump_stop" || parameter.endsWith("_pulse_s") ? 30000 : 145000);
    } catch (error) {
      submit.disabled = false;
      result.textContent = error.message;
    }
  });
})();
