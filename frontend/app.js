// ============================================================================
// RotaHub - frontend (vanilla JS + Leaflet, sem build step)
// ============================================================================
const API = ""; // mesmo host (backend serve o frontend estático também)
const TOKEN_KEY = "rotahub_token";
const USER_KEY = "rotahub_user";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || null,
  displayName: localStorage.getItem(USER_KEY) || null,
  currentRoute: null,   // objeto rota completo (com stops) da tela ativa
  map: null,
  markers: {},          // stopId -> L.Marker
  polyline: null,
  panelCollapsed: false,
};

// ---------------------------------------------------------------- API -----
async function api(path, options = {}) {
  const headers = options.headers || {};
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const resp = await fetch(API + path, { ...options, headers });
  if (resp.status === 401) {
    logout();
    throw new Error("Sessão expirada. Faça login novamente.");
  }
  if (!resp.ok) {
    let detail = "Erro inesperado";
    try { detail = (await resp.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("application/json") ? resp.json() : null;
}

function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), 3200);
}

// ------------------------------------------------------------- SCREENS ----
function showScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => (s.hidden = true));
  document.getElementById(id).hidden = false;
}

// ================================================================= LOGIN ==
document.querySelectorAll(".user-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".user-chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    document.getElementById("login-username").value = chip.dataset.user;
    document.getElementById("login-password").focus();
  });
});
document.querySelector('.user-chip[data-user="matheus"]').classList.add("active");

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("login-username").value;
  const password = document.getElementById("login-password").value;
  const errorEl = document.getElementById("login-error");
  errorEl.hidden = true;
  try {
    const resp = await fetch(API + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username, password }),
    });
    if (!resp.ok) throw new Error("Usuário ou senha inválidos");
    const data = await resp.json();
    state.token = data.access_token;
    state.displayName = data.display_name;
    localStorage.setItem(TOKEN_KEY, state.token);
    localStorage.setItem(USER_KEY, state.displayName);
    enterApp();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  }
});

function logout() {
  state.token = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  showScreen("screen-login");
}
document.getElementById("btn-logout").addEventListener("click", logout);

function enterApp() {
  document.getElementById("current-user-label").textContent = state.displayName;
  showScreen("screen-routes");
  loadRoutes();
}

// ============================================================ ROUTE LIST ==
async function loadRoutes() {
  const list = document.getElementById("route-list");
  const empty = document.getElementById("routes-empty");
  list.innerHTML = "";
  try {
    const routes = await api("/routes");
    empty.hidden = routes.length > 0;
    const statusLabel = {
      draft: "rascunho", optimized: "otimizada", in_progress: "em andamento", finished: "concluída",
    };
    routes.forEach((r) => {
      const delivered = r.stops.filter((s) => s.status === "delivered").length;
      const div = document.createElement("div");
      div.className = "route-item";
      div.innerHTML = `
        <div class="route-item-main">
          <div class="route-item-name">${escapeHtml(r.name)}</div>
          <div class="route-item-meta">${r.stops.length} paradas ${r.total_distance_km ? "· " + r.total_distance_km + " km" : ""} ${r.status === "in_progress" || r.status === "finished" ? "· " + delivered + "/" + r.stops.length + " entregues" : ""}</div>
        </div>
        <span class="badge badge-${r.status}">${statusLabel[r.status] || r.status}</span>
        <button class="btn-delete-route" title="Excluir rota" data-id="${r.id}" data-name="${escapeHtml(r.name)}">&times;</button>
      `;
      div.querySelector(".route-item-main").addEventListener("click", () => openRoute(r));
      div.querySelector(".badge").addEventListener("click", () => openRoute(r));
      div.querySelector(".btn-delete-route").addEventListener("click", (e) => {
        e.stopPropagation();
        confirmDeleteRoute(r.id, r.name);
      });
      list.appendChild(div);
    });
  } catch (err) {
    toast(err.message, true);
  }
}

async function confirmDeleteRoute(routeId, routeName) {
  // Qualquer um dos 3 usuários pode excluir - time pequeno e de confiança,
  // a confirmação aqui é a proteção contra clique acidental (não é um
  // controle de permissão por papel, que seria complexidade desnecessária
  // pra 3 pessoas).
  const ok = confirm(`Excluir a rota "${routeName}"? Essa ação não pode ser desfeita.`);
  if (!ok) return;
  try {
    await api(`/routes/${routeId}`, { method: "DELETE" });
    toast("Rota excluída.");
    loadRoutes();
  } catch (err) {
    toast(err.message, true);
  }
}

function openRoute(route) {
  if (route.status === "draft") {
    openPrepareScreen(route);
  } else {
    openActiveScreen(route.id);
  }
}

document.getElementById("btn-new-route").addEventListener("click", async () => {
  const name = prompt("Nome da rota (ex: Rota 12/07 - Manhã):", `Rota ${new Date().toLocaleDateString("pt-BR")}`);
  if (!name) return;
  try {
    const route = await api("/routes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    openPrepareScreen(route);
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("btn-back-to-routes").addEventListener("click", () => { showScreen("screen-routes"); loadRoutes(); });
document.getElementById("btn-back-to-routes-2").addEventListener("click", () => { stopActiveScreen(); showScreen("screen-routes"); loadRoutes(); });

// ========================================================== PREPARE/IMPORT ==
let prepareRouteId = null;

function openPrepareScreen(route) {
  prepareRouteId = route.id;
  document.getElementById("prepare-route-name").textContent = route.name;
  document.getElementById("summary-card").hidden = true;
  document.getElementById("optimized-card").hidden = true;
  document.getElementById("import-status").textContent = "";
  document.getElementById("dropzone-label").textContent = "Selecionar arquivo .xlsx";
  showScreen("screen-prepare");
}

document.getElementById("file-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const statusEl = document.getElementById("import-status");
  statusEl.className = "import-status";

  // Validação no cliente: garante extensão .xlsx (iOS pode enviar com MIME genérico)
  const filename = file.name || "";
  if (!filename.toLowerCase().endsWith(".xlsx")) {
    statusEl.textContent = `Arquivo "${filename}" não é um arquivo .xlsx válido. Selecione uma planilha Excel (.xlsx).`;
    statusEl.classList.add("error");
    document.getElementById("dropzone-label").textContent = "Selecionar arquivo .xlsx";
    e.target.value = ""; // reseta o input para permitir selecionar o mesmo arquivo novamente
    return;
  }

  document.getElementById("dropzone-label").textContent = filename;
  statusEl.textContent = "Importando e agrupando paradas por proximidade real...";

  const formData = new FormData();
  formData.append("file", file);
  try {
    const route = await api(`/routes/${prepareRouteId}/import`, { method: "POST", body: formData });
    statusEl.textContent = `Formato detectado: ${route.source_format === "shopee_raw" ? "Shopee (bruto, por pacote)" : route.source_format === "circuit_processed" ? "Circuit (processado)" : route.source_format || "—"}`;
    statusEl.classList.add("ok");

    const totalPkgs = route.stops.reduce((a, s) => a + s.package_count, 0);
    const needsReview = route.stops.filter((s) => s.needs_review).length;
    document.getElementById("stat-stops").textContent = route.stops.length;
    document.getElementById("stat-packages").textContent = totalPkgs;
    document.getElementById("stat-review").textContent = needsReview;
    document.getElementById("summary-card").hidden = false;
    if (needsReview > 0) {
      toast(`${needsReview} endereço(s) precisam de revisão manual (não foram localizados).`, true);
    }
    document.getElementById("btn-verify").hidden = false;
  } catch (err) {
    statusEl.textContent = `Erro na importação: ${err.message}`;
    statusEl.classList.add("error");
    document.getElementById("dropzone-label").textContent = "Selecionar arquivo .xlsx (tentar novamente)";
    e.target.value = ""; // reseta para permitir tentar o mesmo arquivo de novo
  }
});

document.getElementById("btn-optimize").addEventListener("click", async () => {
  const btn = document.getElementById("btn-optimize");
  const statusEl = document.getElementById("optimize-status");
  btn.disabled = true;
  statusEl.textContent = "Calculando rota (matriz de distância real + TSP)... isso pode levar alguns segundos.";
  try {
    const route = await api(`/routes/${prepareRouteId}/optimize`, { method: "POST" });
    statusEl.textContent = "";
    document.getElementById("stat-distance").textContent = route.total_distance_km;
    document.getElementById("stat-duration").textContent = Math.round(route.total_duration_min);
    document.getElementById("stat-source").textContent = route.distance_source === "osrm" ? "ruas" : "linha reta";
    document.getElementById("optimized-card").hidden = false;
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.className = "import-status error";
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btn-start-route").addEventListener("click", async () => {
  try {
    await api(`/routes/${prepareRouteId}/start`, { method: "POST" });
    openActiveScreen(prepareRouteId);
  } catch (err) {
    toast(err.message, true);
  }
});

// ---- verificar enderecos (RF005 estendido) ----
document.getElementById("btn-verify").addEventListener("click", async () => {
  const modal = document.getElementById("modal-verify");
  const resultsEl = document.getElementById("verify-results");
  const summaryEl = document.getElementById("verify-summary");
  const progressEl = document.getElementById("verify-progress");
  const barEl = document.getElementById("verify-progress-bar");
  resultsEl.innerHTML = "";
  barEl.style.width = "0%";
  progressEl.hidden = false;
  summaryEl.textContent = "Verificando endereços (Nominatim reverso + ViaCEP)...";
  summaryEl.className = "muted";
  modal.hidden = false;

  try {
    let pct = 0;
    const anim = setInterval(() => {
      pct = Math.min(pct + 3, 90);
      barEl.style.width = pct + "%";
    }, 400);

    const data = await api(`/routes/${prepareRouteId}/verify-addresses`, { method: "POST" });
    clearInterval(anim);
    barEl.style.width = "100%";
    setTimeout(() => (progressEl.hidden = true), 600);

    summaryEl.textContent = `${data.checked} parada(s) · ${data.issues_found} com divergência(s) · fonte: ${data.source || "nominatim+"}`;

    if (data.results.length === 0) {
      resultsEl.innerHTML = `<p class="muted">Nenhuma parada para verificar.</p>`;
      return;
    }

    data.results.forEach((r) => {
      const row = document.createElement("div");
      row.className = "verify-row " + (r.needs_review ? "warn" : "ok");
      const diffText = r.distance_meters !== null
        ? `${r.distance_meters}m`
        : "—";
      row.innerHTML = `
        <div class="verify-status">${r.needs_review ? "⚠" : "✓"}</div>
        <div class="verify-info">
          <div class="verify-addr">${escapeHtml(r.address)} <span class="verify-diff">(${diffText})</span></div>
          <div class="verify-msg">${escapeHtml(r.message)}</div>
          ${r.geocoded_lat !== null ? `<div class="verify-coords">planilha (${r.original_lat.toFixed(5)}, ${r.original_lng.toFixed(5)}) → verif (${r.geocoded_lat.toFixed(5)}, ${r.geocoded_lng.toFixed(5)})</div>` : ""}
        </div>
        ${r.needs_review ? `<a class="verify-map-link" href="https://www.google.com/maps?q=${encodeURIComponent(r.original_lat)},${encodeURIComponent(r.original_lng)}" target="_blank" rel="noopener" title="Abrir no Google Maps">📍</a>` : ""}
      `;
      resultsEl.appendChild(row);
    });
  } catch (err) {
    summaryEl.textContent = err.message;
    summaryEl.className = "muted error";
  }
});

document.getElementById("btn-verify-close").addEventListener("click", () => {
  document.getElementById("modal-verify").hidden = true;
  document.getElementById("verify-progress").hidden = false;
});

// ============================================================ ACTIVE ROUTE ==
async function openActiveScreen(routeId) {
  showScreen("screen-active");
  await refreshActiveRoute(routeId);
  initMapIfNeeded();
  renderActiveRoute();
}

function stopActiveScreen() {
  state.currentRoute = null;
}

async function refreshActiveRoute(routeId) {
  state.currentRoute = await api(`/routes/${routeId}`);
  document.getElementById("active-route-name").textContent = state.currentRoute.name;
}

function initMapIfNeeded() {
  if (state.map) return;
  state.map = L.map("map", {
    zoomControl: true,
    tap: true,            // iOS: habilita tap rapido em marcadores
    tapTolerance: 15,     // tolerancia de toque impreciso em mobile
    touchZoom: true,     // pinch-zoom com dois dedos
    dragging: true,
    scrollWheelZoom: true,
    inertia: true,       // arrasto com momentum natural
  }).setView([-23.5613, -46.6565], 13);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; OpenStreetMap &copy; CARTO',
    subdomains: "abcd", maxZoom: 20,
  }).addTo(state.map);
}

function markerIcon(kind, label) {
  return L.divIcon({
    className: "",
    html: `<div class="rh-marker ${kind}"><span>${label}</span></div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 28],
  });
}

// separa marcadores com coordenadas quase idênticas (ex: dois endereços no
// mesmo lote) num pequeno leque, pra nao ficarem 100% sobrepostos no mapa.
function dedupeCoords(stops) {
  const groups = {};
  stops.forEach((s) => {
    const key = s.latitude.toFixed(5) + "," + s.longitude.toFixed(5);
    (groups[key] = groups[key] || []).push(s);
  });
  const offsetMap = {};
  Object.values(groups).forEach((group) => {
    if (group.length === 1) {
      offsetMap[group[0].id] = [group[0].latitude, group[0].longitude];
      return;
    }
    const R = 0.00012; // ~13m
    group.forEach((s, i) => {
      const angle = (2 * Math.PI * i) / group.length;
      offsetMap[s.id] = [s.latitude + R * Math.cos(angle), s.longitude + R * Math.sin(angle)];
    });
  });
  return offsetMap;
}

function renderActiveRoute() {
  const route = state.currentRoute;
  if (!route) return;

  const pending = route.stops.filter((s) => s.status === "pending");
  const delivered = route.stops.filter((s) => s.status === "delivered").length;
  document.getElementById("progress-pill").textContent = `${delivered} / ${route.stops.length}`;

  // ---- sidepanel (RF008) ----
  const list = document.getElementById("stop-list");
  list.innerHTML = "";
  const activeStop = pending[0] || null;

  route.stops.forEach((s) => {
    const row = document.createElement("div");
    row.className = `stop-row ${s.status}` + (activeStop && s.id === activeStop.id ? " active" : "");
    row.innerHTML = `
      <div class="stop-badge">${s.status === "delivered" ? "✓" : s.status === "skipped" ? "✕" : (s.sequence ?? "–")}</div>
      <div class="stop-info">
        <div class="stop-title">${escapeHtml(s.custom_label || s.address)}</div>
        <div class="stop-sub">${escapeHtml(s.complement || s.neighborhood || "")}</div>
      </div>
      <div class="stop-pkg">${s.package_count} pct</div>
      <button class="stop-nav-btn" title="Navegar até aqui">➤</button>
    `;
    row.querySelector(".stop-nav-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      openNavigation(s); // navega pra ESSA parada, independente de qual está "ativa" pra entrega
    });
    row.addEventListener("click", () => focusStop(s));
    list.appendChild(row);
  });

  // ---- mapa (RF007) ----
  Object.values(state.markers).forEach((m) => state.map.removeLayer(m));
  state.markers = {};
  if (state.polyline) { state.map.removeLayer(state.polyline); state.polyline = null; }

  const offsetMap = dedupeCoords(route.stops);
  const latlngs = [];

  if (route.origin_lat) latlngs.push([route.origin_lat, route.origin_lng]);

  const sortedStops = [...route.stops].sort((a, b) => (a.sequence ?? 999) - (b.sequence ?? 999));
  sortedStops.forEach((s) => {
    const pos = offsetMap[s.id] || [s.latitude, s.longitude];
    let kind = "pending";
    if (s.status === "delivered") kind = "delivered";
    else if (s.status === "skipped") kind = "skipped";
    else if (activeStop && s.id === activeStop.id) kind = "active";

    const marker = L.marker(pos, { icon: markerIcon(kind, s.sequence ?? "?"), draggable: true }).addTo(state.map);
    marker.bindPopup(`<strong>#${s.sequence ?? "-"} ${escapeHtml(s.address)}</strong><br>${escapeHtml(s.complement || "")}<br>${s.package_count} pacote(s)<br><em>Arraste o pino se o endereço estiver no lugar errado.</em>`);
    marker.on("click", () => focusStop(s));
    marker.on("dragend", () => correctStopLocation(s.id, marker.getLatLng()));
    state.markers[s.id] = marker;
    if (s.status !== "skipped") latlngs.push(pos);
  });

  if (latlngs.length > 1) {
    state.polyline = L.polyline(latlngs, { color: "#F2A93B", weight: 3, opacity: 0.55, dashArray: "1,8" }).addTo(state.map);
    upgradePolylineWithRealRoute(latlngs, route.id);
  }
  if (latlngs.length > 0) {
    state.map.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40] });
  }

  // ---- barra de ação (RF009/RF010/RF011) ----
  const actionBar = document.getElementById("action-bar");
  if (activeStop) {
    actionBar.hidden = false;
    document.getElementById("action-seq").textContent = "#" + (activeStop.sequence ?? "?");
    document.getElementById("action-address").textContent = activeStop.custom_label || activeStop.address;
    document.getElementById("action-complement").textContent = activeStop.complement || "";

    // Clona os botoes para remover listeners antigos (evita handlers acumulados a cada render)
    const btnDeliver = document.getElementById("btn-deliver");
    const btnSkip = document.getElementById("btn-skip");
    const btnNavigate = document.getElementById("btn-navigate");
    btnDeliver.replaceWith(btnDeliver.cloneNode(true));
    btnSkip.replaceWith(btnSkip.cloneNode(true));
    btnNavigate.replaceWith(btnNavigate.cloneNode(true));

    // Re-anexa listeners limpos
    document.getElementById("btn-deliver").addEventListener("click", () => deliverStop(activeStop.id));
    document.getElementById("btn-skip").addEventListener("click", () => openSkipModal(activeStop.id));
    document.getElementById("btn-navigate").addEventListener("click", () => openNavigation(activeStop));

    // Garante que os botoes estao habilitados e sem estado de loading
    setActionButtonsLoading(false);
  } else {
    actionBar.hidden = true;
    if (route.status !== "finished" && route.stops.length > 0) {
      finishRoute(route.id);
    }
  }
}

// Estado de loading dos botoes da action-bar: desabilita durante requisicao
// para evitar cliques duplicados e dar feedback visual claro ao usuario.
function setActionButtonsLoading(loading) {
  const buttons = ["btn-deliver", "btn-skip", "btn-navigate"];
  buttons.forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.disabled = loading;
    btn.classList.toggle("btn-loading", loading);
  });
}

// Busca a geometria REAL de rua pro traçado do mapa (RF007). A ordem das
// paradas já é otimizada por distância real (backend, via OSRM Table API),
// mas o TRAÇADO desenhado até aqui era sempre linha reta - o Table API só
// devolve distância/tempo, não o caminho. Isso busca o caminho de verdade
// (OSRM Route API) direto do navegador, que tem internet normal (diferente
// do ambiente de desenvolvimento). Se falhar por qualquer motivo, mantém a
// linha reta tracejada como fallback - nunca quebra o mapa.
async function upgradePolylineWithRealRoute(latlngs, routeIdAtCallTime) {
  if (latlngs.length < 2 || latlngs.length > 100) return; // API publica tem limite pratico de coordenadas
  const coordStr = latlngs.map(([lat, lng]) => `${lng},${lat}`).join(";");
  try {
    const resp = await fetch(
      `https://router.project-osrm.org/route/v1/driving/${coordStr}?overview=full&geometries=geojson`
    );
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.code !== "Ok" || !data.routes || !data.routes[0]) return;
    // se o usuario ja navegou pra outra rota enquanto a busca rodava, descarta
    if (!state.currentRoute || state.currentRoute.id !== routeIdAtCallTime) return;
    const realPath = data.routes[0].geometry.coordinates.map(([lng, lat]) => [lat, lng]);
    if (state.polyline) {
      state.polyline.setLatLngs(realPath);
      state.polyline.setStyle({ dashArray: null, opacity: 0.8, weight: 4 });
    }
  } catch (err) {
    // sem internet pro OSRM publico, ou fora do ar - fica a linha reta mesmo
  }
}

function focusStop(stop) {
  const marker = state.markers[stop.id];
  if (marker) {
    state.map.setView(marker.getLatLng(), 17, { animate: true });
    marker.openPopup();
  }
  document.querySelectorAll(".stop-row").forEach((r) => r.classList.remove("active"));
}

// RF009/RF010 — em vez de reinventar navegação turno-a-turno (o próprio
// Circuit também delega isso pro Google Maps/Waze/Apple Maps), abrimos o
// Google Maps já com o destino da parada ATIVA, mantendo nossa ordem
// otimizada (o Circuit reotimiza tudo de novo se você reimportar lá).
// RF005 estendido: correção manual de endereço. A coordenada que vem da
// planilha (Shopee/Circuit) não tem garantia de estar certa - se o
// entregador percebe que o pino caiu no lugar errado, arrastar ele no mapa
// salva a correção pra sempre nessa parada.
async function correctStopLocation(stopId, latlng) {
  try {
    await api(`/stops/${stopId}/location`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ latitude: latlng.lat, longitude: latlng.lng }),
    });
    toast("Localização corrigida e salva.");
    await refreshActiveRoute(state.currentRoute.id);
    renderActiveRoute();
  } catch (err) {
    toast(err.message, true);
  }
}

// RF009/RF010 — em vez de reinventar navegação turno-a-turno (o próprio
// Circuit também delega isso pro Google Maps/Waze/Apple Maps), abrimos o
// Google Maps já com o destino da parada, mantendo nossa ordem otimizada.
//
// IMPORTANTE: o destino usa o ENDEREÇO EM TEXTO (rua + número), não a
// coordenada lat/lng. Testado na prática e confirmado: mandar só a
// coordenada faz o Google "arredondar" pro endereço mais próximo que ele
// conhece, o que pode cair na casa vizinha (mesma rua, número errado) -
// mesmo a coordenada sendo um ponto real da planilha. Usando o texto do
// endereço, quem geocodifica é o próprio Google, com o banco de endereços
// dele - exatamente o mesmo texto que aparece na tela do RotaHub, sem
// ambiguidade nenhuma entre o que o app mostra e pra onde ele navega.
//
// Navegação na MESMA aba (window.location.href) em vez de window.open:
// no iOS Safari/Chrome, window.open="_blank" cria uma aba about:blank
// temporária que fica "presa" quando o usuário volta ao RotaHub. Usando
// location.href, o navegador abre o Maps na mesma aba e, ao voltar
// (botão do browser), o usuário volta exatamente ao estado do RotaHub.
function openNavigation(stop) {
  const parts = [stop.address, stop.neighborhood, stop.city || "São Paulo"].filter(Boolean);
  const destination = encodeURIComponent(parts.join(", "));
  const url = `https://www.google.com/maps/dir/?api=1&destination=${destination}`;
  window.location.href = url;
}

document.getElementById("btn-collapse-panel").addEventListener("click", () => {
  state.panelCollapsed = !state.panelCollapsed;
  document.getElementById("sidepanel").classList.toggle("collapsed", state.panelCollapsed);
  setTimeout(() => state.map && state.map.invalidateSize(), 220);
});

async function deliverStop(stopId) {
  setActionButtonsLoading(true);
  try {
    await api(`/stops/${stopId}/deliver`, { method: "POST" }); // RF010 + RF015 (autosave)
    await refreshActiveRoute(state.currentRoute.id);            // RF011 (proxima parada assume automaticamente)
    renderActiveRoute(); // ja re-habilita os botoes via setActionButtonsLoading(false)
    toast("Entrega registrada.");
  } catch (err) {
    toast(err.message, true);
    setActionButtonsLoading(false); // re-habilita em caso de erro
  }
}

// ---- pular entrega (RF012) ----
let skipStopId = null;
function openSkipModal(stopId) {
  skipStopId = stopId;
  document.getElementById("modal-skip").hidden = false;
}
document.getElementById("btn-skip-cancel").addEventListener("click", () => (document.getElementById("modal-skip").hidden = true));
document.getElementById("btn-skip-confirm").addEventListener("click", async () => {
  const mode = document.querySelector('input[name="skip-mode"]:checked').value;
  document.getElementById("modal-skip").hidden = true;
  setActionButtonsLoading(true);
  try {
    await api(`/stops/${skipStopId}/skip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "cliente ausente", recalculate: mode === "recalculate" }),
    });
    await refreshActiveRoute(state.currentRoute.id);
    renderActiveRoute(); // re-habilita botoes via setActionButtonsLoading(false)
    toast(mode === "recalculate" ? "Entrega pulada. Rota recalculada." : "Entrega pulada.");
  } catch (err) {
    toast(err.message, true);
    setActionButtonsLoading(false); // re-habilita em caso de erro
  }
});

// ---- finalização (RF013) ----
async function finishRoute(routeId) {
  try {
    const summary = await api(`/routes/${routeId}/finish`, { method: "POST" });
    document.getElementById("finish-count").textContent = `${summary.delivered} entrega(s) realizada(s)`;
    const h = Math.floor((summary.elapsed_minutes || 0) / 60);
    const m = Math.round((summary.elapsed_minutes || 0) % 60);
    document.getElementById("finish-time").textContent = `${h}h${String(m).padStart(2, "0")}`;
    document.getElementById("finish-distance").textContent = `${summary.total_distance_km ?? "–"} km`;
    document.getElementById("finish-skipped").textContent = summary.skipped;
    document.getElementById("modal-finish").hidden = false;
  } catch (err) {
    toast(err.message, true);
  }
}
document.getElementById("btn-finish-close").addEventListener("click", () => {
  document.getElementById("modal-finish").hidden = true;
  stopActiveScreen();
  showScreen("screen-routes");
  loadRoutes();
});

// -------------------------------------------------------------- helpers ---
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------------------------------------------------------------- boot ----
(function boot() {
  if (state.token) {
    enterApp();
  } else {
    showScreen("screen-login");
  }
})();
