/* AELABS WEB alarm controller — browser sound is supplementary to onsite safety controls.
 * An explicit click unlocks audio. Critical alerts repeat until acknowledged or cleared.
 * Warning alerts sound once per new condition. Silence/ack never hides active alerts.
 */
(function (root) {
  'use strict';
  const soundButton = document.getElementById('soundToggle');
  const testButton = document.getElementById('alarmTest');
  const ackButton = document.getElementById('alarmAck');
  const status = document.getElementById('alarmAudioStatus');
  const volumeInput = document.getElementById('alarmVolume');
  const criticalAudio = new Audio('/alarm-critical.wav');
  const warningAudio = new Audio('/alarm-warning.wav');
  criticalAudio.loop = true;
  criticalAudio.preload = 'auto';
  warningAudio.preload = 'auto';
  let enabled = false;  // A new page load requires a new user gesture to unlock browser audio.
  let playbackError = false;
  let current = new Map();
  let acknowledged = new Set();
  let heardWarningKeys = new Set();
  let volume = 0.65;
  try {
    const storedVolume = Number(localStorage.getItem('aelabs_alarm_volume_v1'));
    if (Number.isFinite(storedVolume) && storedVolume >= 0 && storedVolume <= 1) volume = storedVolume;
  } catch (_) {}
  volumeInput.value = String(Math.round(volume * 100));
  function syncVolume() {
    criticalAudio.volume = volume;
    warningAudio.volume = volume;
  }
  syncVolume();
  function labelKey(a) {
    if (a.key) return String(a.key);
    // Preserve channel indices; strip changing measured decimal values and timestamps.
    return String(a.text || '').trim().toLowerCase()
      .replace(/\b\d{1,4}[.,]\d+\b/g, '#')
      .replace(/\s+/g, ' ').slice(0, 180);
  }
  function unacknowledgedCritical() {
    return Array.from(current.entries()).some(([key, a]) => a.level === 'error' && !acknowledged.has(key));
  }
  function unacknowledged() {
    return Array.from(current.keys()).filter(key => !acknowledged.has(key)).length;
  }
  function stopCritical() {
    if (!criticalAudio.paused) criticalAudio.pause();
    try { criticalAudio.currentTime = 0; } catch (_) {}
  }
  function stopWarning() {
    if (!warningAudio.paused) warningAudio.pause();
    try { warningAudio.currentTime = 0; } catch (_) {}
  }
  function setPlaybackError() {
    playbackError = true;
    drawControls();
  }
  function tryPlay(audio) {
    try {
      const result = audio.play();
      if (result && typeof result.catch === 'function') result.catch(setPlaybackError);
    } catch (_) { setPlaybackError(); }
  }
  function syncCriticalSound() {
    if (!enabled || !unacknowledgedCritical()) { stopCritical(); return; }
    if (criticalAudio.paused) {
      stopWarning();
      tryPlay(criticalAudio);
    }
  }
  function drawControls() {
    const pending = unacknowledged();
    const critical = unacknowledgedCritical();
    soundButton.textContent = enabled ? '🔊 Звук включён' : '🔇 Включить звук';
    soundButton.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    soundButton.classList.toggle('sound-enabled', enabled);
    ackButton.disabled = !pending;
    if (!enabled) status.textContent = 'Звуковые уведомления выключены';
    else if (playbackError) status.textContent = 'Звук заблокирован браузером — нажмите «Проверить звук»';
    else if (critical) status.textContent = 'Критическая тревога · звук до квитирования';
    else if (pending) status.textContent = 'Предупреждения активны';
    else if (current.size) status.textContent = 'Все активные события квитированы';
    else status.textContent = 'Звуковая сигнализация готова';
  }
  function update(alarms) {
    const next = new Map();
    for (const a of (Array.isArray(alarms) ? alarms : [])) {
      if (!a || !['error', 'warning'].includes(a.level)) continue;
      const key = labelKey(a);
      if (key) next.set(key, {level: a.level, text: String(a.text || '')});
    }
    // Removed alerts lose their acknowledgement. An escalation from yellow to
    // critical is treated as a new danger, even when the key stays the same.
    acknowledged = new Set([...acknowledged].filter(key => next.has(key) &&
      !(current.get(key)?.level === 'warning' && next.get(key).level === 'error')));
    heardWarningKeys = new Set([...heardWarningKeys].filter(key => next.has(key)));
    current = next;
    if (enabled && !unacknowledgedCritical()) {
      const freshWarning = [...next.entries()].some(([key, a]) =>
        a.level === 'warning' && !acknowledged.has(key) && !heardWarningKeys.has(key));
      if (freshWarning) {
        stopWarning();
        tryPlay(warningAudio);
      }
    }
    for (const [key, a] of next) if (a.level === 'warning') heardWarningKeys.add(key);
    syncCriticalSound();
    drawControls();
  }
  function enableAndPreview(preview) {
    enabled = true;
    playbackError = false;
    if (unacknowledgedCritical()) {
      syncCriticalSound(); // play() occurs synchronously in the user click handler
    } else if (preview) {
      stopWarning();
      tryPlay(warningAudio);
    }
    drawControls();
  }
  soundButton.addEventListener('click', () => {
    if (enabled) {
      enabled = false;
      stopCritical();
      stopWarning();
      drawControls();
    } else enableAndPreview(true);
  });
  testButton.addEventListener('click', () => {
    if (!enabled) { enableAndPreview(true); return; }
    playbackError = false;
    if (unacknowledgedCritical()) {
      stopCritical();
      syncCriticalSound();
    } else {
      stopWarning();
      tryPlay(warningAudio);
    }
    drawControls();
  });
  ackButton.addEventListener('click', () => {
    for (const key of current.keys()) acknowledged.add(key);
    stopCritical();
    stopWarning();
    drawControls();
  });
  volumeInput.addEventListener('input', () => {
    volume = Math.max(0, Math.min(1, Number(volumeInput.value) / 100));
    syncVolume();
    try { localStorage.setItem('aelabs_alarm_volume_v1', String(volume)); } catch (_) {}
  });
  criticalAudio.addEventListener('error', setPlaybackError);
  warningAudio.addEventListener('error', setPlaybackError);
  // Browser tab focus alone may not unlock audio; we only retry previously enabled sound.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && enabled) syncCriticalSound();
  });
  root.AELABSAlarm = {
    update,
    getState: () => ({enabled, active: current.size, critical: unacknowledgedCritical(), pending: unacknowledged()})
  };
  drawControls();
})(window);
