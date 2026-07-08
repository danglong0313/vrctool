const $ = (id) => document.getElementById(id);

let currentState = null;
let pulseEnabled = true;
let qrModalOpen = false;
const debounceTimers = new Map();
const sectionTitles = {
  overview: "总览",
  chatbox: "ChatBox",
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
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
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

function openQrModal() {
  qrModalOpen = true;
  $("qrModal").classList.add("is-open");
  $("qrModal").setAttribute("aria-hidden", "false");
  if (window.lucide) window.lucide.createIcons();
}

function closeQrModal() {
  qrModalOpen = false;
  $("qrModal").classList.remove("is-open");
  $("qrModal").setAttribute("aria-hidden", "true");
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

function render(state) {
  if (!state) return;
  currentState = state;
  const { chatbox, device, afk, dglab, osc, logs } = state;

  setPill($("oscState"), osc.running, "OSC 运行", "OSC 停止");
  setPill($("dglabState"), dglab.running, "DG-LAB 组件运行", "DG-LAB 组件停止");
  setPill($("bindState"), dglab.bound, "已连接", "未连接");

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
  const syncChatboxConfig = () =>
    postDebounced("chatbox-config", "/api/chatbox/config", () => {
      const port = portInputValue("chatPort");
      if (!port) return null;
      return {
        host: $("chatHost").value.trim() || "127.0.0.1",
        port,
      };
    });

  const syncDeviceInterval = () =>
    postDebounced("device-interval", "/api/chatbox/device", () => {
      const interval = numericInputValue("deviceInterval");
      if (!interval) return null;
      return {
        enabled: Boolean(currentState?.chatbox?.device_enabled),
        interval,
      };
    });

  const syncAfkInterval = () =>
    postDebounced("afk-interval", "/api/chatbox/afk", () => {
      const interval = numericInputValue("afkInterval");
      if (!interval) return null;
      return {
        enabled: Boolean(currentState?.chatbox?.afk_enabled),
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

  $("chatHost").addEventListener("input", syncChatboxConfig);
  $("chatPort").addEventListener("input", syncChatboxConfig);
  $("deviceInterval").addEventListener("input", syncDeviceInterval);
  $("afkInterval").addEventListener("input", syncAfkInterval);
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
    if (event.key === "Escape" && qrModalOpen) {
      closeQrModal();
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
  connectStatusSocket();
}

boot().catch((error) => {
  console.error(error);
});
