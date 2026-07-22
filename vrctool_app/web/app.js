const $ = (id) => document.getElementById(id);

let currentState = null;
let pulseEnabled = true;
let qrModalOpen = false;
let settingsModalOpen = false;
let releaseNotesModalOpen = false;
let releaseNotesHandledThisSession = false;
let releaseNotesClosing = false;
let performanceGrantPending = false;
let weatherLocationRequested = false;
const debounceTimers = new Map();
const batchSourceLabels = {
  custom: "自定义文字",
  device: "设备信息",
  afk: "挂机计时",
  heart_rate: "心率",
  performance: "游戏帧率",
  now_playing: "正在播放",
  weather: "天气",
  dglab: "郊狼状态",
};
const sectionTitles = {
  overview: "总览",
  chatbox: "ChatBox",
  heart: "心率广播",
  performance: "游戏帧率",
  "now-playing": "正在播放",
  weather: "天气",
  dglab: "郊狼控制",
  osc: "OSC 映射",
  logs: "日志",
};

async function api(path, payload = null) {
  const options = payload
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    : { method: "GET" };
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const error = await response.json();
      message = error.detail || message;
    } catch (_error) {
      // The HTTP status remains useful when the response has no JSON body.
    }
    throw new Error(message);
  }
  const data = await response.json();
  render(data);
  return data;
}

function postDebounced(key, path, payloadFactory, delay = 240) {
  clearTimeout(debounceTimers.get(key));
  debounceTimers.set(
    key,
    setTimeout(() => {
      const payload = payloadFactory();
      if (!payload) return;
      api(path, payload).catch((error) => console.error(error));
    }, delay),
  );
}

function numericInputValue(id) {
  if ($(id).value === "") return null;
  const value = Number($(id).value);
  return Number.isFinite(value) ? value : null;
}

function portInputValue(id) {
  const value = numericInputValue(id);
  if (!Number.isInteger(value) || value < 1 || value > 65535) return null;
  return value;
}

function syncModalLock() {
  document.body.classList.toggle(
    "modal-open",
    qrModalOpen || settingsModalOpen || releaseNotesModalOpen,
  );
}

function openQrModal() {
  qrModalOpen = true;
  $("qrModal").classList.add("is-open");
  $("qrModal").setAttribute("aria-hidden", "false");
  syncModalLock();
  if (window.lucide) window.lucide.createIcons();
}

function closeQrModal() {
  qrModalOpen = false;
  $("qrModal").classList.remove("is-open");
  $("qrModal").setAttribute("aria-hidden", "true");
  syncModalLock();
}

function openSettingsModal() {
  settingsModalOpen = true;
  $("settingsFeedback").textContent = "";
  if (currentState) render(currentState);
  $("settingsModal").classList.add("is-open");
  $("settingsModal").setAttribute("aria-hidden", "false");
  syncModalLock();
  window.setTimeout(() => $("webPort").focus(), 40);
  if (window.lucide) window.lucide.createIcons();
}

function closeSettingsModal() {
  settingsModalOpen = false;
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  $("settingsModal").classList.remove("is-open");
  $("settingsModal").setAttribute("aria-hidden", "true");
  syncModalLock();
  if (currentState) render(currentState);
}

function renderReleaseNotes(appState) {
  const notes = appState?.release_notes || {};
  const version = notes.version || appState?.version || "";
  $("releaseNotesTitle").textContent = notes.title || "本次更新";
  $("releaseNotesVersion").textContent = version ? `v${version}` : "更新";
  const list = $("releaseNotesList");
  list.replaceChildren();
  (Array.isArray(notes.items) ? notes.items : []).forEach((item) => {
    const row = document.createElement("li");
    row.textContent = String(item);
    list.appendChild(row);
  });
}

function maybeOpenReleaseNotes() {
  if (releaseNotesHandledThisSession || !currentState?.app?.show_release_notes) return;
  releaseNotesHandledThisSession = true;
  releaseNotesModalOpen = true;
  $("dismissReleaseNotes").checked = false;
  $("releaseNotesFeedback").textContent = "";
  renderReleaseNotes(currentState.app);
  $("releaseNotesModal").classList.add("is-open");
  $("releaseNotesModal").setAttribute("aria-hidden", "false");
  syncModalLock();
  if (window.lucide) window.lucide.createIcons();
}

async function closeReleaseNotesModal() {
  if (!releaseNotesModalOpen || releaseNotesClosing) return;
  releaseNotesClosing = true;
  const dismissPermanently = $("dismissReleaseNotes").checked;
  try {
    if (dismissPermanently) {
      $("releaseNotesFeedback").textContent = "正在保存提醒设置…";
      await api("/api/app/release-notes", { dismissed: true });
    }
    releaseNotesModalOpen = false;
    $("releaseNotesModal").classList.remove("is-open");
    $("releaseNotesModal").setAttribute("aria-hidden", "true");
    syncModalLock();
  } catch (error) {
    $("releaseNotesFeedback").textContent = error.message || String(error);
  } finally {
    releaseNotesClosing = false;
  }
}

function setTheme(theme) {
  const nextTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;
  localStorage.setItem("vrctool-theme", nextTheme);
  const icon = nextTheme === "light" ? "moon" : "sun-medium";
  const button = $("themeToggle");
  if (button) {
    button.innerHTML = `<i data-lucide="${icon}"></i>`;
  }
  if (window.lucide) window.lucide.createIcons();
}

function setPill(el, active, goodText, badText) {
  el.textContent = active ? goodText : badText;
  el.classList.toggle("is-good", Boolean(active));
  el.classList.toggle("is-warn", !active);
}

function formatClock(seconds) {
  const h = Math.floor(seconds / 3600).toString().padStart(2, "0");
  const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, "0");
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function fillWaveforms(select, options, selected) {
  if (!select.dataset.ready) {
    select.innerHTML = options.map((item) => `<option value="${item.value}">${item.label}</option>`).join("");
    select.dataset.ready = "1";
  }
  select.value = selected;
}

function setModeButtons(channel, mode) {
  const interaction = $(`mode${channel}Interaction`);
  const panel = $(`mode${channel}Panel`);
  interaction.classList.toggle("is-selected", mode === "interaction");
  panel.classList.toggle("is-selected", mode === "panel");
}

function setValueUnlessFocused(id, value) {
  const el = $(id);
  if (document.activeElement !== el) {
    el.value = value;
  }
}

function setDglabConnectButton(dglab) {
  const button = $("toggleDglab");
  const connected = Boolean(dglab.bound);
  button.classList.toggle("primary", !connected);
  button.classList.toggle("danger", connected);
  button.innerHTML = connected
    ? '<i data-lucide="unlink"></i>取消连接'
    : '<i data-lucide="plug-zap"></i>连接设备';
  if (connected && qrModalOpen) {
    closeQrModal();
  }
}

function updateStrengthVisuals(dglab) {
  const limitA = Math.max(1, Number(dglab.safety_limit_a || 1));
  const limitB = Math.max(1, Number(dglab.safety_limit_b || 1));
  const percentA = Math.max(0, Math.min(100, (Number(dglab.strength_a || 0) / limitA) * 100));
  const percentB = Math.max(0, Math.min(100, (Number(dglab.strength_b || 0) / limitB) * 100));
  $("ringA").style.setProperty("--percent", `${percentA}%`);
  $("ringB").style.setProperty("--percent", `${percentB}%`);
  $("ringALimit").textContent = `/ ${dglab.safety_limit_a}`;
  $("ringBLimit").textContent = `/ ${dglab.safety_limit_b}`;
  $("strengthAInline").textContent = dglab.strength_a;
  $("strengthBInline").textContent = dglab.strength_b;
}

function switchSection(section, updateHash = true) {
  const target = sectionTitles[section] ? section : "overview";
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.section === target);
  });
  document.querySelectorAll(".section-page").forEach((page) => {
    page.classList.toggle("is-active", page.dataset.page === target);
  });
  $("sectionTitle").textContent = sectionTitles[target];
  if (updateHash && location.hash.slice(1) !== target) {
    history.replaceState(null, "", `#${target}`);
  }
  if (target === "weather" && !weatherLocationRequested) {
    requestWeatherLocation();
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderCustomOscList(items) {
  const list = $("customOscList");
  if (!items || items.length === 0) {
    list.innerHTML = '<div class="empty-row">暂无自定义参数</div>';
    return;
  }
  list.innerHTML = items
    .map(
      (item) => `
        <div class="custom-osc-item">
          <label class="checkbox-row custom-osc-toggle">
            <input class="custom-osc-enabled" type="checkbox" data-id="${item.id}" ${item.enabled === false ? "" : "checked"} />
            <span>生效</span>
          </label>
          <span>${escapeHtml(item.address)}</span>
          <strong>${escapeHtml(item.channel)}</strong>
          <button class="icon-button ghost remove-custom-osc" data-id="${item.id}" title="删除">
            <i data-lucide="trash-2"></i>
          </button>
        </div>
      `,
    )
    .join("");
  list.querySelectorAll(".remove-custom-osc").forEach((button) => {
    button.addEventListener("click", () =>
      api("/api/osc/custom/remove", { mapping_id: button.dataset.id }),
    );
  });
  list.querySelectorAll(".custom-osc-enabled").forEach((checkbox) => {
    checkbox.addEventListener("change", () =>
      api("/api/osc/custom/update", {
        mapping_id: checkbox.dataset.id,
        enabled: checkbox.checked,
      }),
    );
  });
}

function renderHeartRateDevices(heartRate) {
  const select = $("heartDeviceSelect");
  const devices = heartRate.devices || [];
  const selectedAddress = heartRate.address || "";
  if (!devices.length) {
    const savedLabel = selectedAddress
      ? `${heartRate.device_name || "已保存设备"} (${selectedAddress})`
      : "请先扫描心率设备";
    select.innerHTML = `<option value="${escapeHtml(selectedAddress)}" data-name="${escapeHtml(heartRate.device_name || "")}">${escapeHtml(savedLabel)}</option>`;
    select.disabled = !selectedAddress;
    return;
  }
  select.disabled = false;
  select.innerHTML = devices
    .map((device) => {
      const support = device.heart_rate_supported ? "心率" : "未知";
      const rssi = device.rssi === null || device.rssi === undefined ? "" : ` ${device.rssi}dBm`;
      const label = `${device.name || "未知设备"} | ${support}${rssi}`;
      return `<option value="${escapeHtml(device.address)}" data-name="${escapeHtml(device.name || "")}">${escapeHtml(label)}</option>`;
    })
    .join("");
  if (devices.some((device) => device.address === selectedAddress)) {
    select.value = selectedAddress;
  }
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024 * 1024) return `${Math.max(0, bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderUpdateState(update) {
  const status = update.status || "idle";
  const progress = Math.max(0, Math.min(100, Number(update.progress || 0)));
  const card = $("updateCard");
  const checkButton = $("checkUpdate");
  const actionButton = $("updateAction");
  const progressTrack = $("updateProgress");

  $("currentVersion").textContent = `v${update.current_version || "-"}`;
  card.classList.toggle("is-error", status === "error");
  card.classList.toggle("is-ready", status === "ready");
  progressTrack.hidden = !["downloading", "ready"].includes(status);
  progressTrack.setAttribute("aria-valuenow", String(progress));
  $("updateProgressBar").style.width = `${progress}%`;

  const display = {
    idle: ["等待检查", "当前版本已就绪"],
    checking: ["正在检查", "连接 GitHub Releases"],
    up_to_date: ["已是最新版本", `v${update.current_version || "-"}`],
    available: [
      `发现 v${update.latest_version || "-"}`,
      update.release_name || formatBytes(update.asset_size),
    ],
    downloading: [
      `正在下载 ${progress}%`,
      `${formatBytes(update.downloaded_bytes)} / ${formatBytes(update.asset_size)}`,
    ],
    ready: [`v${update.latest_version || ""} 已就绪`, "安装包校验通过"],
    installing: ["正在安装更新", "应用即将重新启动"],
    error: ["更新失败", update.error || "请稍后重试"],
  };
  const [title, detail] = display[status] || display.idle;
  $("updateTitle").textContent = title;
  $("updateStatus").textContent = detail;

  const busy = ["checking", "downloading", "installing"].includes(status);
  checkButton.disabled = busy;
  checkButton.innerHTML = status === "checking"
    ? '<i data-lucide="loader-circle"></i>检查中'
    : '<i data-lucide="refresh-cw"></i>检查更新';

  actionButton.hidden = !["available", "downloading", "ready", "installing"].includes(status);
  actionButton.disabled = ["downloading", "installing"].includes(status);
  if (status === "available") {
    actionButton.innerHTML = update.can_install
      ? '<i data-lucide="download"></i>下载更新'
      : '<i data-lucide="external-link"></i>查看发布页';
  } else if (status === "downloading") {
    actionButton.innerHTML = `<i data-lucide="loader-circle"></i>下载 ${progress}%`;
  } else if (status === "ready") {
    actionButton.innerHTML = '<i data-lucide="refresh-cw"></i>安装并重启';
  } else if (status === "installing") {
    actionButton.innerHTML = '<i data-lucide="loader-circle"></i>正在重启';
  }
}

function performanceValue(value) {
  const number = Number(value || 0);
  return number > 0 && Number.isFinite(number) ? number.toFixed(1) : "--";
}

function renderPerformanceState(performance) {
  const fps = Number(performance.fps || 0);
  const hasSample = Boolean(performance.sampling && fps > 0);
  const failed = ["采样失败", "监控失败", "性能采集不可用"].includes(performance.status);
  const lowFps = Boolean(performance.low_fps && hasSample);
  const card = $("performanceCard");
  const status = $("performanceStatus");
  const broadcast = $("performanceBroadcast");

  $("performanceFps").textContent = performanceValue(performance.fps);
  $("performanceAvgFps").textContent = performanceValue(performance.avg_fps);
  $("performanceFrameMs").textContent = performanceValue(performance.frame_ms);
  status.textContent = performance.status || "等待启动";
  status.classList.toggle("is-good", hasSample && !lowFps);
  status.classList.toggle("is-warn", !hasSample && !failed);
  status.classList.toggle("is-danger", failed || lowFps);
  card.classList.toggle("is-low-fps", lowFps);
  card.classList.toggle("is-error", failed);

  $("performanceWarning").hidden = !lowFps;
  $("performanceWarningText").textContent = lowFps
    ? `低于 ${Number(performance.low_fps_threshold || 45).toFixed(1)} FPS`
    : "低 FPS";
  $("performanceProcess").textContent = performance.vrchat_running
    ? `VRChat.exe · PID ${performance.process_id || "-"}`
    : "VRChat.exe 未运行";
  $("performanceLastSample").textContent = `最近采样 ${performance.last_sample || "-"}`;
  $("performanceReason").textContent = performance.reason || "PresentMon 正在采样";
  $("performanceLastSent").textContent = performance.last_sent
    ? `最近发送 ${performance.last_sent}`
    : "尚未发送";

  broadcast.classList.toggle("is-on", Boolean(performance.broadcast_enabled));
  broadcast.setAttribute("aria-pressed", String(Boolean(performance.broadcast_enabled)));
  broadcast.disabled = !performance.available;
  setValueUnlessFocused("performanceInterval", performance.interval || 3);
  setValueUnlessFocused("performanceThreshold", performance.low_fps_threshold || 45);

  const setMetricToggle = (id, on) => {
    const button = $(id);
    button.classList.toggle("is-on", Boolean(on));
    button.setAttribute("aria-pressed", String(Boolean(on)));
  };
  setMetricToggle("performanceShowFps", true);
  setMetricToggle("performanceShowAvgFps", performance.show_avg_fps);
  setMetricToggle("performanceShowFrameMs", performance.show_frame_ms);
  $("performanceShowAvgFps").disabled = !performance.available;
  $("performanceShowFrameMs").disabled = !performance.available;

  const preview = ["FPS: {fps}"];
  if (performance.show_avg_fps) preview.push("AVG: {avg_fps}");
  if (performance.show_frame_ms) preview.push("Frame: {frame_ms}ms");
  $("performancePreview").textContent = preview.join(" | ");

  const permissionPanel = $("performancePermission");
  const grantButton = $("grantPerformancePermission");
  const permissionText = $("performancePermissionText");
  if (performanceGrantPending) {
    // A grant request is in flight; leave the panel as the click handler set it.
  } else if (performance.relogin_required) {
    permissionPanel.hidden = false;
    grantButton.hidden = true;
    permissionText.textContent =
      "已加入 Performance Log Users 组，请注销并重新登录（或重启）后开始采样。";
  } else if (performance.needs_permission) {
    permissionPanel.hidden = false;
    grantButton.hidden = false;
    grantButton.disabled = false;
    permissionText.textContent =
      "PresentMon 需要 ETW 权限。点此授权会弹出一次 UAC，把当前账户加入 Performance Log Users 组，之后无需以管理员身份运行。";
  } else {
    permissionPanel.hidden = true;
  }
}

function weatherMetric(value, suffix, digits = 1) {
  if (value === null || value === undefined || value === "") return `--${suffix}`;
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}${suffix}` : `--${suffix}`;
}

function playbackTime(seconds) {
  const numeric = Number(seconds);
  const totalSeconds = Number.isFinite(numeric) ? Math.max(0, Math.floor(numeric)) : 0;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function nowPlayingProgressLine(positionSeconds, durationSeconds) {
  const duration = Number(durationSeconds);
  const rawPosition = Number(positionSeconds);
  if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(rawPosition)) return "";
  const position = Math.max(0, Math.min(rawPosition, duration));
  const segments = 6;
  const marker = Math.min(segments, Math.floor((position / duration) * segments));
  const bar = `${"-".repeat(marker)}>${"-".repeat(segments - marker)}`;
  return `${playbackTime(position)} ${bar} ${playbackTime(duration)}`;
}

function renderNowPlayingState(nowPlaying) {
  const available = Boolean(nowPlaying.available);
  const ready = Boolean(nowPlaying.ready && nowPlaying.title);
  const playing = Boolean(nowPlaying.playing && ready);
  const failed = Boolean(nowPlaying.error);
  const card = $("nowPlayingCard");
  const status = $("nowPlayingStatus");
  const broadcast = $("nowPlayingBroadcast");

  status.textContent = nowPlaying.status || (playing ? "正在播放" : "等待播放");
  status.classList.toggle("is-good", playing);
  status.classList.toggle("is-warn", !playing && !failed);
  status.classList.toggle("is-danger", failed);
  card.classList.toggle("is-playing", playing);
  card.classList.toggle("is-error", failed);
  $("nowPlayingDisc").classList.toggle("is-spinning", playing);

  $("nowPlayingPlayer").textContent = nowPlaying.player_name
    || "QQ 音乐 / 网易云音乐 / 汽水音乐 / 酷狗音乐";
  $("nowPlayingTitle").textContent = ready ? nowPlaying.title : "还没有检测到歌曲";
  $("nowPlayingArtist").textContent = ready
    ? nowPlaying.artist || "未知歌手"
    : "启动播放器并开始播放即可自动识别";
  $("nowPlayingAlbum").textContent = nowPlaying.album || "-";
  $("nowPlayingSession").textContent = nowPlaying.source_id || "-";
  $("nowPlayingSession").title = nowPlaying.source_id || "";
  const progressLine = nowPlayingProgressLine(
    nowPlaying.position_seconds,
    nowPlaying.duration_seconds,
  );
  const progressUnavailable = nowPlaying.player === "netease"
    ? "网易云音乐官方客户端不支持返回进度；QQ 音乐与汽水音乐可以显示"
    : nowPlaying.player === "kugou"
      ? "当前酷狗音乐客户端暂未通过系统媒体会话返回进度"
      : "播放器暂未提供进度";
  $("nowPlayingProgress").textContent = progressLine || (ready ? progressUnavailable : "等待播放器进度");
  $("nowPlayingProgress").classList.toggle("is-unavailable", !progressLine);
  $("nowPlayingLastUpdate").textContent = `最近检测 ${nowPlaying.last_update || "-"}`;
  $("nowPlayingLastSent").textContent = nowPlaying.last_sent
    ? `最近发送 ${nowPlaying.last_sent}`
    : "尚未发送";
  $("nowPlayingReason").textContent = nowPlaying.reason || "等待 Windows 媒体会话";

  broadcast.classList.toggle("is-on", Boolean(nowPlaying.broadcast_enabled));
  broadcast.setAttribute("aria-pressed", String(Boolean(nowPlaying.broadcast_enabled)));
  broadcast.disabled = !available;
  setValueUnlessFocused("nowPlayingPreferredPlayer", nowPlaying.preferred_player || "auto");
  setValueUnlessFocused("nowPlayingInterval", nowPlaying.interval || 5);

  const setContentToggle = (id, enabled) => {
    const button = $(id);
    button.classList.toggle("is-on", Boolean(enabled));
    button.setAttribute("aria-pressed", String(Boolean(enabled)));
  };
  const showTitle = nowPlaying.show_title !== false;
  const showArtist = nowPlaying.show_artist !== false;
  const showAlbum = Boolean(nowPlaying.show_album);
  const showPlayer = Boolean(nowPlaying.show_player);
  const showProgress = nowPlaying.show_progress !== false;
  setContentToggle("nowPlayingShowTitle", showTitle);
  setContentToggle("nowPlayingShowArtist", showArtist);
  setContentToggle("nowPlayingShowAlbum", showAlbum);
  setContentToggle("nowPlayingShowPlayer", showPlayer);
  setContentToggle("nowPlayingShowProgress", showProgress);

  const previewParts = [];
  if (showTitle) previewParts.push(`♪ ${nowPlaying.title || "歌名"}`);
  if (showArtist && (!ready || nowPlaying.artist)) {
    previewParts.push(`歌手: ${nowPlaying.artist || "歌手"}`);
  }
  if (showAlbum && (!ready || nowPlaying.album)) {
    previewParts.push(`专辑: ${nowPlaying.album || "专辑"}`);
  }
  if (showPlayer && (!ready || nowPlaying.player_name)) {
    previewParts.push(`播放器: ${nowPlaying.player_name || "播放器"}`);
  }
  const previewProgress = showProgress ? progressLine : "";
  const firstLine = previewParts.length ? `正在播放: ${previewParts.join(" | ")}` : "正在播放:";
  $("nowPlayingPreview").textContent = previewParts.length || previewProgress
    ? `${firstLine}${previewProgress ? `\n${previewProgress}` : ""}`
    : showTitle || showArtist || showAlbum || showPlayer || showProgress
      ? "所选广播内容暂无可用信息"
      : "请至少选择一项广播内容";
}

function renderWeatherState(weather) {
  const ready = Boolean(weather.ready);
  const updating = Boolean(weather.updating);
  const failed = Boolean(weather.error) && !updating;
  const status = $("weatherStatus");
  const card = $("weatherCard");
  const sourceLabels = {
    browser: "浏览器定位",
    ip: "IP 估算定位",
    manual: "手动选择城市",
  };

  status.textContent = updating ? "正在更新" : weather.status || (ready ? "已更新" : "等待定位");
  status.classList.toggle("is-good", ready && !updating && !failed);
  status.classList.toggle("is-warn", updating || (!ready && !failed));
  status.classList.toggle("is-danger", failed);
  card.classList.toggle("is-error", failed);

  $("weatherTemperature").textContent = ready
    ? Number(weather.temperature || 0).toFixed(1)
    : "--";
  $("weatherCondition").textContent = ready ? weather.condition || "" : "";
  $("weatherLocation").textContent = weather.location_name || "";
  const source = weather.location_name ? sourceLabels[weather.location_source] || "" : "";
  const accuracy = weather.location_source === "browser" && Number(weather.location_accuracy) > 0
    ? ` · 约 ${Math.round(Number(weather.location_accuracy))} 米`
    : "";
  $("weatherLocationSource").textContent = `${source}${accuracy}`;
  $("weatherFeelsLike").textContent = weatherMetric(weather.feels_like, "°C");
  $("weatherHumidity").textContent = weatherMetric(weather.humidity, "%", 0);
  $("weatherWind").textContent = weatherMetric(weather.wind_speed, " km/h");
  $("weatherPrecipitation").textContent = weatherMetric(weather.precipitation, " mm");
  $("weatherLastUpdate").textContent = `最近更新 ${weather.last_update || "-"}`;
  $("weatherTimezone").textContent = `时区 ${weather.timezone || "-"}`;
  const provider = weather.weather_provider ? `天气源：${weather.weather_provider}。` : "";
  const locationHint = weather.location_source === "ip"
    ? "当前使用 IP 估算位置；使用代理时可能不准确，可点“自动定位”重新授权。"
    : "定位成功，天气数据会按设置的间隔更新。";
  $("weatherReason").textContent = weather.error
    || `${provider}${locationHint}`;
  $("weatherLastSent").textContent = weather.last_sent
    ? `最近发送 ${weather.last_sent}`
    : "尚未发送";

  const broadcast = $("weatherBroadcast");
  broadcast.classList.toggle("is-on", Boolean(weather.broadcast_enabled));
  broadcast.setAttribute("aria-pressed", String(Boolean(weather.broadcast_enabled)));
  broadcast.disabled = !weather.available;
  setValueUnlessFocused("weatherInterval", Number(weather.interval || 600) / 60);
  $("weatherAutoLocate").disabled = updating;
  $("weatherRefresh").disabled = updating || !ready;
  $("weatherSearchCity").disabled = updating;
  $("weatherPreview").textContent = weather.last_message
    ? weather.last_message.replaceAll("\n", " · ")
    : "定位成功后将发送地点、天气、温度、湿度、风速和降水。";
}

async function requestWeatherLocation(force = false) {
  if (weatherLocationRequested && !force) return;
  weatherLocationRequested = true;
  const status = $("weatherStatus");
  const reason = $("weatherReason");
  status.textContent = "正在定位";
  status.classList.add("is-warn");
  reason.textContent = "正在请求浏览器位置权限…";

  const useIpFallback = async () => {
    reason.textContent = "浏览器定位不可用，正在使用 IP 估算位置…";
    try {
      await api("/api/weather/auto-location", {});
    } catch (error) {
      status.textContent = "定位失败";
      status.classList.add("is-danger");
      reason.textContent = error.message || String(error);
    }
  };

  if (!navigator.geolocation) {
    await useIpFallback();
    return;
  }
  navigator.geolocation.getCurrentPosition(
    async (position) => {
      try {
        await api("/api/weather/location", {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
        });
      } catch (_error) {
        await useIpFallback();
      }
    },
    () => useIpFallback(),
    { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 },
  );
}

function renderChatboxBatch(chatbox) {
  const enabled = Boolean(chatbox.batch_enabled);
  const running = Boolean(chatbox.batch_running);
  const active = Array.isArray(chatbox.batch_active_sources)
    ? chatbox.batch_active_sources
    : [];
  const order = Array.isArray(chatbox.batch_order)
    ? chatbox.batch_order
    : Object.keys(batchSourceLabels);
  const current = chatbox.batch_current_source || "";
  const next = chatbox.batch_next_source || "";
  const toggle = $("batchEnabled");
  toggle.classList.toggle("is-on", enabled);
  toggle.setAttribute("aria-pressed", String(enabled));
  setValueUnlessFocused("batchInterval", chatbox.batch_interval || 3);
  $("batchCurrentSource").value = batchSourceLabels[current] || "等待发送";
  $("batchNextSource").value = batchSourceLabels[next] || "-";

  const status = $("batchStatus");
  status.textContent = !enabled
    ? "已关闭"
    : running
      ? `轮播中 · ${active.length} 项`
      : "等待广播项目";
  status.classList.toggle("is-good", running);
  status.classList.toggle("is-warn", enabled && !running);

  $("batchSequence").innerHTML = order
    .map((source, index) => {
      const classes = ["batch-source"];
      if (active.includes(source)) classes.push("is-active");
      if (source === current) classes.push("is-current");
      return `<span class="${classes.join(" ")}"><b>${index + 1}</b><span>${batchSourceLabels[source] || source}</span></span>`;
    })
    .join("");
}

function render(state) {
  if (!state) return;
  currentState = state;
  const { chatbox, device, afk, dglab, osc, logs } = state;
  const appState = state.app || {};
  const heartRate = state.heart_rate || {};
  const performance = state.performance || {};
  const nowPlaying = state.now_playing || {};
  const weather = state.weather || {};
  const update = state.update || {};

  setPill($("oscState"), osc.running, "OSC 运行", "OSC 停止");
  setPill($("dglabState"), dglab.running, "DG-LAB 组件运行", "DG-LAB 组件停止");
  setPill($("bindState"), dglab.bound, "已连接", "未连接");

  const currentWebPort = appState.web_port || 8765;
  const configuredWebPort = appState.configured_web_port || currentWebPort;
  setValueUnlessFocused("webPort", configuredWebPort);
  $("webPortSummary").textContent = configuredWebPort;
  $("currentWebPort").textContent = currentWebPort;
  $("configuredWebPort").textContent = configuredWebPort;
  $("settingsPortState").textContent = appState.port_temporary
    ? "本次临时"
    : appState.restart_required
      ? "等待重启"
      : "配置端口";
  $("settingsPortState").classList.toggle("is-warn", Boolean(appState.restart_required));
  renderReleaseNotes(appState);

  setValueUnlessFocused("chatHost", chatbox.host);
  setValueUnlessFocused("chatPort", chatbox.port);
  setValueUnlessFocused("deviceInterval", chatbox.device_interval);
  setValueUnlessFocused("afkInterval", chatbox.afk_interval);
  $("toggleDevice").innerHTML = chatbox.device_enabled
    ? '<i data-lucide="square"></i>停止发送'
    : '<i data-lucide="monitor-up"></i>开始发送';
  $("toggleAfk").innerHTML = chatbox.afk_enabled
    ? '<i data-lucide="square"></i>停止挂机'
    : '<i data-lucide="timer"></i>开始挂机';
  setValueUnlessFocused("customMessage", chatbox.custom_message || "");
  setValueUnlessFocused("customMessageMirror", chatbox.custom_message || "");
  $("sendMessage").innerHTML = chatbox.custom_enabled
    ? '<i data-lucide="square"></i>停止发送'
    : '<i data-lucide="message-square-more"></i>开始发送';
  $("sendMessageMirror").innerHTML = $("sendMessage").innerHTML;
  $("toggleDeviceMirror").innerHTML = chatbox.device_enabled
    ? '<i data-lucide="square"></i>停止设备信息'
    : '<i data-lucide="monitor-up"></i>设备信息';
  $("toggleAfkMirror").innerHTML = chatbox.afk_enabled
    ? '<i data-lucide="square"></i>停止挂机'
    : '<i data-lucide="timer"></i>挂机计时';
  $("dglabChatboxStatus").checked = Boolean(chatbox.dglab_enabled);
  renderChatboxBatch(chatbox);

  if (device.cpu) {
    $("cpuUsage").textContent = `${Math.round(device.cpu.usage)}%`;
    $("cpuName").textContent = device.cpu.name;
    $("gpuUsage").textContent = `${Math.round(device.gpu.usage)}%`;
    $("gpuName").textContent = device.gpu.name;
    $("ramUsage").textContent = `${Math.round(device.ram.usage)}%`;
    $("ramText").textContent = `${device.ram.used.toFixed(1)} / ${device.ram.total.toFixed(1)} GB`;
  }
  $("afkClock").textContent = formatClock(afk.elapsed_seconds || 0);

  setValueUnlessFocused("dglabPort", dglab.port);
  $("qrImage").src = dglab.qr_image || "";
  setDglabConnectButton(dglab);
  $("pulseSwitch").classList.toggle("is-on", dglab.pulse_enabled);
  $("pulseSwitch").setAttribute("aria-pressed", String(dglab.pulse_enabled));
  pulseEnabled = dglab.pulse_enabled;
  setModeButtons("A", dglab.mode_a);
  setModeButtons("B", dglab.mode_b);
  $("panelEnabled").checked = Boolean(dglab.panel_enabled);
  setValueUnlessFocused("fireStep", dglab.fire_step);
  setValueUnlessFocused("adjustStep", dglab.adjust_step);

  $("strengthA").max = dglab.safety_limit_a;
  $("strengthB").max = dglab.safety_limit_b;
  $("strengthA").value = dglab.strength_a;
  $("strengthB").value = dglab.strength_b;
  $("strengthAValue").textContent = dglab.strength_a;
  $("strengthBValue").textContent = dglab.strength_b;
  updateStrengthVisuals(dglab);
  $("limitA").max = dglab.limit_a;
  $("limitB").max = dglab.limit_b;
  setValueUnlessFocused("limitA", Math.min(dglab.safety_limit_a, dglab.limit_a));
  setValueUnlessFocused("limitB", Math.min(dglab.safety_limit_b, dglab.limit_b));
  fillWaveforms($("waveformA"), dglab.waveforms, dglab.waveform_a);
  fillWaveforms($("waveformB"), dglab.waveforms, dglab.waveform_b);

  setValueUnlessFocused("oscHost", osc.listen_host);
  setValueUnlessFocused("oscPort", osc.listen_port);
  setValueUnlessFocused("oscThreshold", osc.threshold);
  setValueUnlessFocused("addressA", osc.address_a);
  setValueUnlessFocused("addressB", osc.address_b);
  setValueUnlessFocused("addressAChannel", osc.channel_a || "A");
  setValueUnlessFocused("addressBChannel", osc.channel_b || "B");
  $("lastOsc").textContent = osc.last_address
    ? `${osc.last_channel || "-"} ${osc.last_value} -> ${osc.last_strength}`
    : "-";
  renderCustomOscList(osc.custom_mappings);
  renderHeartRateDevices(heartRate);
  renderPerformanceState(performance);
  renderNowPlayingState(nowPlaying);
  renderWeatherState(weather);
  renderUpdateState(update);

  $("heartStatus").textContent = heartRate.status || "未连接";
  $("heartStatus").classList.toggle("is-good", Boolean(heartRate.connected));
  $("heartStatus").classList.toggle("is-warn", !heartRate.connected);
  $("heartBpm").textContent = heartRate.bpm ? heartRate.bpm : "--";
  $("heartDeviceName").textContent = heartRate.device_name || heartRate.address || "未选择设备";
  $("heartLastSeen").value = heartRate.last_seen || "-";
  setValueUnlessFocused("heartInterval", heartRate.interval || 1);
  $("heartError").textContent = heartRate.error ? heartRate.error.slice(0, 42) : "";
  $("scanHeartRate").disabled = Boolean(heartRate.scanning);
  $("scanHeartRate").innerHTML = heartRate.scanning
    ? '<i data-lucide="loader-circle"></i>扫描中'
    : '<i data-lucide="radar"></i>扫描设备';
  $("connectHeartRate").disabled = Boolean(
    heartRate.connecting || heartRate.connected || !$("heartDeviceSelect").value,
  );
  $("connectHeartRate").innerHTML = heartRate.connected
    ? '<i data-lucide="bluetooth-connected"></i>已连接'
    : heartRate.connecting
      ? '<i data-lucide="loader-circle"></i>连接中'
      : '<i data-lucide="bluetooth-connected"></i>连接设备';
  $("toggleHeartChatbox").innerHTML = heartRate.send_enabled
    ? '<i data-lucide="square"></i>停止发送'
    : '<i data-lucide="message-square-heart"></i>发送到 ChatBox';
  $("disconnectHeartRate").disabled = !heartRate.connected;

  $("lastMessage").textContent = chatbox.last_message ? chatbox.last_message.slice(0, 18) : "-";
  $("logList").innerHTML = (logs || [])
    .slice(0, 80)
    .map(
      (item) =>
        `<div class="log-item"><span>${item.time}</span><strong class="${item.level}">${item.level}</strong><span>${item.message}</span></div>`,
    )
    .join("");

  if (window.lucide) window.lucide.createIcons();
}

async function loadNetwork() {
  const data = await fetch("/api/network").then((response) => response.json());
  $("netSelect").innerHTML = data.interfaces
    .map((item) => `<option value="${item.ip}">${item.label}</option>`)
    .join("");
  $("netSelect").value = data.default_ip;
}

function bindEvents() {
  const syncBatchSettings = () =>
    postDebounced("chatbox-batch", "/api/chatbox/batch", () => ({
      enabled: Boolean(currentState?.chatbox?.batch_enabled),
      interval: numericInputValue("batchInterval") || 3,
    }));

  const syncHeartRateInterval = () =>
    postDebounced("heart-rate-interval", "/api/heartrate/chatbox", () => {
      const interval = numericInputValue("heartInterval");
      if (!interval) return null;
      return {
        enabled: Boolean(currentState?.heart_rate?.send_enabled),
        interval,
      };
    });

  const syncPanelSettings = (delay = 180) =>
    postDebounced(
      "panel-settings",
      "/api/dglab/panel-settings",
      () => {
        const fireStep = numericInputValue("fireStep");
        const adjustStep = numericInputValue("adjustStep");
        if (fireStep === null || adjustStep === null) return null;
        return {
          fire_step: Math.trunc(fireStep),
          adjust_step: Math.trunc(adjustStep),
          panel_enabled: $("panelEnabled").checked,
        };
      },
      delay,
    );

  const syncLimits = () =>
    postDebounced("dglab-limits", "/api/dglab/limits", () => {
      const a = numericInputValue("limitA");
      const b = numericInputValue("limitB");
      if (a === null || b === null) return null;
      return { a: Math.trunc(a), b: Math.trunc(b) };
    });

  const syncOscListener = () =>
    postDebounced("osc-listener", "/api/osc/start", () => {
      const port = portInputValue("oscPort");
      if (!port) return null;
      return {
        host: $("oscHost").value.trim() || "127.0.0.1",
        port,
      };
    }, 360);

  const syncOscConfig = () =>
    postDebounced("osc-config", "/api/osc/config", () => {
      const threshold = numericInputValue("oscThreshold");
      if (threshold === null) return null;
      return {
        enabled: true,
        address_a: $("addressA").value,
        address_b: $("addressB").value,
        channel_a: $("addressAChannel").value,
        channel_b: $("addressBChannel").value,
        threshold,
      };
    });

  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => switchSection(button.dataset.section));
  });
  window.addEventListener("hashchange", () =>
    switchSection(location.hash.slice(1) || "overview", false),
  );
  $("themeToggle").addEventListener("click", () =>
    setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"),
  );

  $("openSettings").addEventListener("click", openSettingsModal);
  $("closeSettingsModal").addEventListener("click", closeSettingsModal);
  $("dismissSettingsModal").addEventListener("click", closeSettingsModal);
  $("cancelSettings").addEventListener("click", closeSettingsModal);
  $("settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const webPort = portInputValue("webPort");
    const chatboxPort = portInputValue("chatPort");
    const deviceInterval = numericInputValue("deviceInterval");
    const afkInterval = numericInputValue("afkInterval");
    if (!webPort || !chatboxPort || !deviceInterval || !afkInterval) {
      $("settingsFeedback").textContent = "请检查端口和发送间隔。";
      return;
    }
    const button = $("saveSettings");
    button.disabled = true;
    $("settingsFeedback").textContent = "正在保存…";
    try {
      const state = await api("/api/app/settings", {
        web_port: webPort,
        chatbox_host: $("chatHost").value.trim() || "127.0.0.1",
        chatbox_port: chatboxPort,
        device_interval: deviceInterval,
        afk_interval: afkInterval,
      });
      $("settingsFeedback").textContent = state.app?.restart_required
        ? "已保存，网页端口将在下次启动时切换。"
        : "设置已保存。";
      window.setTimeout(closeSettingsModal, 520);
    } catch (error) {
      $("settingsFeedback").textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  });

  $("closeReleaseNotesModal").addEventListener("click", closeReleaseNotesModal);
  $("dismissReleaseNotesModal").addEventListener("click", closeReleaseNotesModal);
  $("acknowledgeReleaseNotes").addEventListener("click", closeReleaseNotesModal);

  $("heartInterval").addEventListener("input", syncHeartRateInterval);
  $("batchInterval").addEventListener("input", syncBatchSettings);
  $("batchEnabled").addEventListener("click", () =>
    api("/api/chatbox/batch", {
      enabled: !currentState?.chatbox?.batch_enabled,
      interval: numericInputValue("batchInterval") || 3,
    }),
  );
  const syncCustomMessage = (sourceId, mirrorId) => {
    const value = $(sourceId).value;
    if (document.activeElement !== $(mirrorId)) {
      $(mirrorId).value = value;
    }
    postDebounced("custom-message", "/api/chatbox/custom", () => ({
      enabled: Boolean(currentState?.chatbox?.custom_enabled),
      interval: 3,
      message: value,
    }));
  };
  $("customMessage").addEventListener("input", () =>
    syncCustomMessage("customMessage", "customMessageMirror"),
  );
  $("customMessageMirror").addEventListener("input", () =>
    syncCustomMessage("customMessageMirror", "customMessage"),
  );

  $("shutdownApp").addEventListener("click", async () => {
    $("shutdownApp").disabled = true;
    $("shutdownApp").innerHTML = '<i data-lucide="loader-circle"></i>';
    if (window.lucide) window.lucide.createIcons();
    await fetch("/api/app/shutdown", { method: "POST" }).catch(() => {});
  });

  const showUpdateError = (error) => {
    $("updateCard").classList.add("is-error");
    $("updateTitle").textContent = "更新失败";
    $("updateStatus").textContent = error.message || String(error);
  };
  $("checkUpdate").addEventListener("click", () => {
    api("/api/update/check").catch(showUpdateError);
  });
  $("updateAction").addEventListener("click", () => {
    const update = currentState?.update || {};
    if (update.status === "available" && !update.can_install) {
      if (update.release_url) window.open(update.release_url, "_blank", "noopener");
      return;
    }
    if (update.status === "available") {
      api("/api/update/download", {}).catch(showUpdateError);
    } else if (update.status === "ready") {
      api("/api/update/install", {}).catch(showUpdateError);
    }
  });

  const toggleCustomMessage = () => {
    const message =
      document.activeElement === $("customMessageMirror")
        ? $("customMessageMirror").value
        : $("customMessage").value;
    if (!currentState?.chatbox?.custom_enabled && !message.trim()) return;
    api("/api/chatbox/custom", {
      enabled: !currentState?.chatbox?.custom_enabled,
      interval: 3,
      message,
    });
  };
  $("sendMessage").addEventListener("click", toggleCustomMessage);
  $("sendMessageMirror").addEventListener("click", toggleCustomMessage);

  $("toggleDevice").addEventListener("click", () =>
    api("/api/chatbox/device", {
      enabled: !currentState?.chatbox?.device_enabled,
      interval: Number($("deviceInterval").value),
    }),
  );
  $("toggleDeviceMirror").addEventListener("click", () => $("toggleDevice").click());

  $("toggleAfk").addEventListener("click", () =>
    api("/api/chatbox/afk", {
      enabled: !currentState?.chatbox?.afk_enabled,
      interval: Number($("afkInterval").value),
    }),
  );
  $("toggleAfkMirror").addEventListener("click", () => $("toggleAfk").click());

  $("resetAfk").addEventListener("click", () => api("/api/chatbox/afk/reset", {}));
  $("refreshDevice").addEventListener("click", () => api("/api/device/refresh", {}));

  $("scanHeartRate").addEventListener("click", () => api("/api/heartrate/scan", { timeout: 5 }));
  $("connectHeartRate").addEventListener("click", () => {
    const option = $("heartDeviceSelect").selectedOptions[0];
    const address = $("heartDeviceSelect").value;
    if (!address) return;
    api("/api/heartrate/connect", {
      address,
      name: option?.dataset?.name || option?.textContent || "",
    });
  });
  $("disconnectHeartRate").addEventListener("click", () => api("/api/heartrate/disconnect", {}));
  $("toggleHeartChatbox").addEventListener("click", () => {
    const interval = numericInputValue("heartInterval") || 1;
    api("/api/heartrate/chatbox", {
      enabled: !currentState?.heart_rate?.send_enabled,
      interval,
    });
  });

  const metricEnabled = (id) => $(id).classList.contains("is-on");
  const performancePayload = (enabled) => ({
    enabled,
    interval: numericInputValue("performanceInterval") || 3,
    low_fps_threshold: numericInputValue("performanceThreshold") || 45,
    show_avg_fps: metricEnabled("performanceShowAvgFps"),
    show_frame_ms: metricEnabled("performanceShowFrameMs"),
  });
  const savePerformance = (enabled) =>
    api("/api/performance/config", performancePayload(enabled)).catch((error) => {
      $("performanceStatus").textContent = "设置失败";
      $("performanceStatus").classList.add("is-danger");
      $("performanceReason").textContent = error.message || String(error);
    });
  const toggleMetric = (id) => {
    const button = $(id);
    button.classList.toggle("is-on");
    button.setAttribute("aria-pressed", String(button.classList.contains("is-on")));
    savePerformance(Boolean(currentState?.performance?.broadcast_enabled));
  };
  $("performanceBroadcast").addEventListener("click", () =>
    savePerformance(!currentState?.performance?.broadcast_enabled),
  );
  $("performanceShowAvgFps").addEventListener("click", () =>
    toggleMetric("performanceShowAvgFps"),
  );
  $("performanceShowFrameMs").addEventListener("click", () =>
    toggleMetric("performanceShowFrameMs"),
  );
  $("savePerformanceSettings").addEventListener("click", () =>
    savePerformance(Boolean(currentState?.performance?.broadcast_enabled)),
  );
  $("grantPerformancePermission").addEventListener("click", async () => {
    const button = $("grantPerformancePermission");
    const hint = $("performancePermissionText");
    performanceGrantPending = true;
    button.disabled = true;
    hint.textContent = "正在请求授权，请在弹出的 UAC 窗口中点“是”…";
    try {
      await api("/api/performance/grant-capture", {});
    } catch (error) {
      hint.textContent = error.message || String(error);
    } finally {
      performanceGrantPending = false;
      button.disabled = false;
      render(currentState);
    }
  });

  const showNowPlayingError = (error) => {
    $("nowPlayingStatus").textContent = "设置失败";
    $("nowPlayingStatus").classList.add("is-danger");
    $("nowPlayingReason").textContent = error.message || String(error);
  };
  const nowPlayingPayload = (enabled) => ({
    enabled,
    interval: numericInputValue("nowPlayingInterval") || 5,
    preferred_player: $("nowPlayingPreferredPlayer").value || "auto",
    show_title: metricEnabled("nowPlayingShowTitle"),
    show_artist: metricEnabled("nowPlayingShowArtist"),
    show_album: metricEnabled("nowPlayingShowAlbum"),
    show_player: metricEnabled("nowPlayingShowPlayer"),
    show_progress: metricEnabled("nowPlayingShowProgress"),
  });
  const saveNowPlaying = (enabled) =>
    api("/api/now-playing/config", nowPlayingPayload(enabled)).catch(showNowPlayingError);
  $("nowPlayingBroadcast").addEventListener("click", () =>
    saveNowPlaying(!currentState?.now_playing?.broadcast_enabled),
  );
  $("saveNowPlayingSettings").addEventListener("click", () =>
    saveNowPlaying(Boolean(currentState?.now_playing?.broadcast_enabled)),
  );
  $("refreshNowPlaying").addEventListener("click", () =>
    api("/api/now-playing/refresh", {}).catch(showNowPlayingError),
  );
  const nowPlayingContentIds = [
    "nowPlayingShowTitle",
    "nowPlayingShowArtist",
    "nowPlayingShowAlbum",
    "nowPlayingShowPlayer",
    "nowPlayingShowProgress",
  ];
  nowPlayingContentIds.forEach((id) => {
    $(id).addEventListener("click", () => {
      const button = $(id);
      const nextEnabled = !button.classList.contains("is-on");
      button.classList.toggle("is-on", nextEnabled);
      button.setAttribute("aria-pressed", String(nextEnabled));
      if (!nowPlayingContentIds.some((toggleId) => metricEnabled(toggleId))) {
        button.classList.add("is-on");
        button.setAttribute("aria-pressed", "true");
        $("nowPlayingReason").textContent = "请至少保留一项广播内容";
        return;
      }
      saveNowPlaying(Boolean(currentState?.now_playing?.broadcast_enabled));
    });
  });

  const showWeatherError = (error) => {
    $("weatherStatus").textContent = "操作失败";
    $("weatherStatus").classList.add("is-danger");
    $("weatherReason").textContent = error.message || String(error);
  };
  const weatherIntervalSeconds = () => {
    const minutes = numericInputValue("weatherInterval") || 10;
    return minutes * 60;
  };
  const saveWeather = (enabled) =>
    api("/api/weather/config", {
      enabled,
      interval: weatherIntervalSeconds(),
    }).catch(showWeatherError);
  const searchWeatherCity = () => {
    const city = $("weatherCity").value.trim();
    if (!city) return;
    api("/api/weather/city", { city })
      .then(() => {
        $("weatherCity").value = "";
      })
      .catch(showWeatherError);
  };
  $("weatherBroadcast").addEventListener("click", () =>
    saveWeather(!currentState?.weather?.broadcast_enabled),
  );
  $("saveWeatherSettings").addEventListener("click", () =>
    saveWeather(Boolean(currentState?.weather?.broadcast_enabled)),
  );
  $("weatherAutoLocate").addEventListener("click", () => requestWeatherLocation(true));
  $("weatherRefresh").addEventListener("click", () =>
    api("/api/weather/refresh", {}).catch(showWeatherError),
  );
  $("weatherSearchCity").addEventListener("click", searchWeatherCity);
  $("weatherCity").addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchWeatherCity();
  });

  $("toggleDglab").addEventListener("click", () => {
    if (currentState?.dglab?.bound) {
      api("/api/dglab/stop", {}).then(closeQrModal);
      return;
    }
    const port = portInputValue("dglabPort");
    if (!port) return;
    api("/api/dglab/start", {
      listen_host: "0.0.0.0",
      advertise_host: $("netSelect").value,
      port,
    }).then(openQrModal);
  });

  $("closeQrModal").addEventListener("click", closeQrModal);
  $("dismissQrModal").addEventListener("click", closeQrModal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (releaseNotesModalOpen) closeReleaseNotesModal();
      else if (settingsModalOpen) closeSettingsModal();
      else if (qrModalOpen) closeQrModal();
    }
  });

  $("emergencyStop").addEventListener("click", () => api("/api/dglab/emergency-stop", {}));

  $("pulseSwitch").addEventListener("click", () =>
    api("/api/dglab/pulse", { enabled: !pulseEnabled }),
  );

  $("dglabChatboxStatus").addEventListener("change", (event) =>
    api("/api/chatbox/dglab", {
      enabled: event.target.checked,
      interval: 1,
    }),
  );

  $("modeAInteraction").addEventListener("click", () =>
    api("/api/dglab/mode", { channel: "A", mode: "interaction" }),
  );
  $("modeAPanel").addEventListener("click", () =>
    api("/api/dglab/mode", { channel: "A", mode: "panel" }),
  );
  $("modeBInteraction").addEventListener("click", () =>
    api("/api/dglab/mode", { channel: "B", mode: "interaction" }),
  );
  $("modeBPanel").addEventListener("click", () =>
    api("/api/dglab/mode", { channel: "B", mode: "panel" }),
  );
  $("panelEnabled").addEventListener("change", () => syncPanelSettings(0));
  $("fireStep").addEventListener("input", () => syncPanelSettings());
  $("adjustStep").addEventListener("input", () => syncPanelSettings());
  $("fireStep").addEventListener("blur", (event) => {
    if (event.target.value === "" && currentState?.dglab) {
      event.target.value = currentState.dglab.fire_step;
    }
  });
  $("adjustStep").addEventListener("blur", (event) => {
    if (event.target.value === "" && currentState?.dglab) {
      event.target.value = currentState.dglab.adjust_step;
    }
  });
  $("limitA").addEventListener("input", syncLimits);
  $("limitB").addEventListener("input", syncLimits);
  $("limitA").addEventListener("blur", (event) => {
    if (event.target.value === "" && currentState?.dglab) {
      event.target.value = currentState.dglab.safety_limit_a;
    }
  });
  $("limitB").addEventListener("blur", (event) => {
    if (event.target.value === "" && currentState?.dglab) {
      event.target.value = currentState.dglab.safety_limit_b;
    }
  });

  $("strengthA").addEventListener("input", (event) => {
    $("strengthAValue").textContent = event.target.value;
  });
  $("strengthB").addEventListener("input", (event) => {
    $("strengthBValue").textContent = event.target.value;
  });
  $("strengthA").addEventListener("change", (event) =>
    api("/api/dglab/strength", { channel: "A", value: Number(event.target.value) }),
  );
  $("strengthB").addEventListener("change", (event) =>
    api("/api/dglab/strength", { channel: "B", value: Number(event.target.value) }),
  );

  $("waveformA").addEventListener("change", (event) =>
    api("/api/dglab/waveform", { channel: "A", waveform: event.target.value }),
  );
  $("waveformB").addEventListener("change", (event) =>
    api("/api/dglab/waveform", { channel: "B", waveform: event.target.value }),
  );

  $("oscHost").addEventListener("input", syncOscListener);
  $("oscPort").addEventListener("input", syncOscListener);
  $("addressA").addEventListener("input", syncOscConfig);
  $("addressB").addEventListener("input", syncOscConfig);
  $("addressAChannel").addEventListener("change", syncOscConfig);
  $("addressBChannel").addEventListener("change", syncOscConfig);
  $("oscThreshold").addEventListener("input", syncOscConfig);
  $("addCustomOsc").addEventListener("click", () => {
    const address = $("customOscAddress").value.trim();
    if (!address) return;
    api("/api/osc/custom", {
      address,
      channel: $("customOscChannel").value,
      enabled: $("customOscEnabled").checked,
    }).then(() => {
      $("customOscAddress").value = "";
    });
  });
}

function connectStatusSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/ws/status`);
  socket.addEventListener("message", (event) => render(JSON.parse(event.data)));
  socket.addEventListener("close", () => setTimeout(connectStatusSocket, 1200));
}

async function boot() {
  const themeFromUrl = new URLSearchParams(location.search).get("theme");
  setTheme(themeFromUrl || localStorage.getItem("vrctool-theme") || "dark");
  bindEvents();
  switchSection(location.hash.slice(1) || "overview", false);
  await loadNetwork();
  await api("/api/status");
  maybeOpenReleaseNotes();
  connectStatusSocket();
}

boot().catch((error) => {
  console.error(error);
});
