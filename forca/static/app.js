"use strict";
// Sem framework e sem etapa de build: o app é este arquivo.

const root = document.getElementById("root");
const sheet = document.getElementById("sheet");
const toastEl = document.getElementById("toast");

let S = null;              // último estado vindo do servidor
let view = "hoje";
let lastResult = null;     // resposta da caixa de registro
let txQuery = "";
let txMonth = "";
let txRows = null;
let report = null;         // relatório do mês aberto na aba Mês
let reportMonth = "";
let installEvent = null;

const ICONS = {
  hoje: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
  mes: '<path d="M4 19V5M4 19h16M8.5 15.5l3.5-4 3 2.5 4-6"/>',
  contas: '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M3.5 10h17M7 15h3"/>',
  extrato: '<path d="M5 6h14M5 12h14M5 18h9"/>',
  metas: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="0.8"/>',
  gear: '<circle cx="12" cy="12" r="1.2"/><circle cx="5.5" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/>',
  send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
};
// Ícones das categorias: traço único, mesma família dos ícones da navegação.
const CATEGORY_ICONS = {
  cart: '<circle cx="9.5" cy="19.5" r="1.3"/><circle cx="17" cy="19.5" r="1.3"/><path d="M3 4h2.2l2.3 11h10.2l2-8H6.2"/>',
  plate: '<path d="M7 3v7a2 2 0 0 0 2 2v9M5 3v5M9 3v5M16 3c-1.7 1.2-2.5 3.6-2.5 6.5 0 2 .9 3 2.5 3V21"/>',
  car: '<path d="M4 16v-3.5l2-5.2A2 2 0 0 1 7.9 6h8.2a2 2 0 0 1 1.9 1.3l2 5.2V16M4 12.5h16M4 16h16v2.5h-3V16M7 16v2.5H4V16"/><circle cx="7.5" cy="14.3" r=".4"/><circle cx="16.5" cy="14.3" r=".4"/>',
  home: '<path d="m4 11 8-6.5 8 6.5M6 9.5V20h12V9.5M10 20v-5.5h4V20"/>',
  tool: '<path d="M14.5 6.5a4 4 0 0 1 5-1.2l-3 3 1.7 1.7 3-3a4 4 0 0 1-5.4 5L8 19.8a2.2 2.2 0 0 1-3.1-3.1l7.8-7.8a4 4 0 0 1 1.8-2.4Z"/>',
  bulb: '<path d="M9.5 18h5M10.5 21h3M12 3a6 6 0 0 0-3.7 10.7c.7.6 1.2 1.4 1.2 2.3v2h5v-2c0-.9.5-1.7 1.2-2.3A6 6 0 0 0 12 3Z"/>',
  repeat: '<path d="M4 11V9.5A3.5 3.5 0 0 1 7.5 6H19M16 3l3 3-3 3M20 13v1.5a3.5 3.5 0 0 1-3.5 3.5H5M8 21l-3-3 3-3"/>',
  health: '<path d="M12 20.5S4 15.7 4 9.8A4.3 4.3 0 0 1 12 7.6a4.3 4.3 0 0 1 8 2.2c0 5.9-8 10.7-8 10.7Z"/><path d="M8 12h2l1.3-2.3 1.7 4 1.2-1.7H16"/>',
  ticket: '<path d="M4 7h16v3.2a2 2 0 0 0 0 3.6V17H4v-3.2a2 2 0 0 0 0-3.6V7ZM14 7v2M14 11v2M14 15v2"/>',
  plane: '<path d="M21 4.3c-.8-.8-2.3-.6-3.2.3L14 8.4 5.5 6 4 7.5l6.9 4-3.2 3.2-2.7-.5L4 15.200l3.5 1.300L8.8 20l1-1-.5-2.7 3.2-3.2 4 6.9 1.5-1.5-2.4-8.5 3.8-3.800c.9-.9 1.1-2.4.6-2.900Z"/>',
  bag: '<path d="M6 8h12l1 12.500H5L6 8ZM9 10.500V7a3 3 0 0 1 6 0v3.5"/>',
  shirt: '<path d="m8.5 4-5 3 1.8 4 2.2-1V20h9V10l2.2 1 1.8-4-5-3a3.5 3.5 0 0 1-7 0Z"/>',
  scissors: '<circle cx="6.5" cy="6.5" r="2.5"/><circle cx="6.5" cy="17.5" r="2.5"/><path d="m8.5 8 11.5 9.500M8.5 16 20 6.5"/>',
  book: '<path d="M12 6.500C10.5 5 8 4.5 4 4.500V18c4 0 6.5.5 8 2 1.5-1.5 4-2 8-2V4.500c-4 0-6.5.5-8 2ZM12 6.500V20"/>',
  people: '<circle cx="9" cy="8" r="3"/><path d="M3.5 20c0-3.4 2.4-6 5.5-6s5.5 2.6 5.5 6M15.5 5.300a3 3 0 0 1 0 5.400M17.5 14.400c1.9.8 3 2.9 3 5.6"/>',
  paw: '<ellipse cx="6" cy="11.5" rx="1.7" ry="2.2"/><ellipse cx="10" cy="7" rx="1.7" ry="2.3"/><ellipse cx="14.5" cy="7" rx="1.7" ry="2.3"/><ellipse cx="18.5" cy="11.5" rx="1.7" ry="2.2"/><path d="M12.2 12c-2.5 0-5 3-5 5.3 0 1.7 1.3 2.7 2.7 2.2 1.5-.5 3-.5 4.5 0 1.4.5 2.8-.5 2.8-2.2 0-2.3-2.5-5.3-5-5.300Z"/>',
  gift: '<path d="M4 9h16v3.500H4V9ZM5.5 12.500V20h13v-7.500M12 9v11M12 9S10.8 4.5 8.3 4.500A2.2 2.2 0 0 0 8 9M12 9s1.2-4.5 3.7-4.500A2.2 2.2 0 0 1 16 9"/>',
  receipt: '<path d="M6 3.500v17l2-1.3 2 1.3 2-1.3 2 1.3 2-1.3 2 1.300v-17l-2 1.3-2-1.3-2 1.3-2-1.3-2 1.3-2-1.300ZM9.5 9h5M9.5 13h5"/>',
  dot: '<circle cx="12" cy="12" r="7.5"/>',
  card: '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M3.5 10h17"/>',
  coin: '<circle cx="12" cy="12" r="8.5"/><path d="M14.5 9.300c-.5-.9-1.4-1.3-2.5-1.3-1.5 0-2.7.8-2.7 2 0 2.7 5.5 1.3 5.5 4 0 1.2-1.2 2-2.8 2-1.2 0-2.2-.5-2.7-1.400M12 6.500V8M12 16v1.5"/>',
  dumbbell: '<path d="M3 9.500v5M6 7v10M18 7v10M21 9.500v5M6 12h12"/>',
  game: '<path d="M7.5 7h9a4.5 4.5 0 0 1 4.3 3.300l.9 3.500a2.8 2.8 0 0 1-4.8 2.500L15.5 15h-7l-1.4 1.300a2.8 2.8 0 0 1-4.8-2.500l.9-3.500A4.5 4.5 0 0 1 7.5 7ZM8 9.500v3M6.5 11h3M15.5 10.500h.01M17.5 12.500h.01"/>',
  coffee: '<path d="M5 9h12v6a5 5 0 0 1-5 5h-2a5 5 0 0 1-5-5V9ZM17 10.500h1.500a2.5 2.5 0 0 1 0 5H17M8.5 3.500v2.500M12.5 3.500v2.5"/>',
  fuel: '<path d="M5 20.500V5a1.5 1.5 0 0 1 1.5-1.500h6A1.5 1.5 0 0 1 14 5v15.500M3.5 20.500h12M7.5 7h4v3.500h-4V7ZM14 12h1.500a1.5 1.5 0 0 1 1.5 1.500v3a1.5 1.5 0 0 0 3 0V9l-3-3"/>',
  briefcase: '<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M9 7.500V6a1.5 1.5 0 0 1 1.5-1.500h3A1.5 1.5 0 0 1 15 6v1.500M3.5 13h17"/>',
  phone: '<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/>',
  leaf: '<path d="M5 19c0-8 5-14 15-14 0 10-6 15-13 13.500M5 21c1-5 4-8 8.5-10"/>',
  star: '<path d="m12 4 2.4 5.3 5.6.6-4.2 3.8 1.2 5.600L12 16.500l-5 2.8 1.2-5.600L4 9.900l5.6-.6L12 4Z"/>',
};
const catIcon = (name) => `<svg class="cat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${CATEGORY_ICONS[name] || CATEGORY_ICONS.dot}</svg>`;

const icon = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function brl(cents, opts = {}) {
  const neg = cents < 0;
  const abs = Math.abs(cents);
  const whole = (opts.noCents ? Math.round(abs / 100) : Math.floor(abs / 100)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const frac = abs % 100;
  const showFrac = frac !== 0 && !opts.noCents;
  return `${neg ? "−" : ""}R$ ${whole}${showFrac ? "," + String(frac).padStart(2, "0") : ""}`;
}

function toCents(text) {
  let t = String(text || "").trim().replace(/[R$\s]/g, "");
  if (!t) return null;
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "");
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : null;
}
const fromCents = (c) => (c == null ? "" : (c / 100).toFixed(2).replace(".", ",").replace(",00", ""));

const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const monthName = (m) => MONTHS[+m.slice(5, 7) - 1];
const monthFull = (m) => `${monthName(m)} de ${m.slice(0, 4)}`;
const monthShort = (m) => SHORT[+m.slice(5, 7) - 1];
const parseDate = (iso) => new Date(`${iso}T12:00:00`);
const dayLabel = (iso) => {
  const d = parseDate(iso);
  const today = parseDate(S.today);
  const diff = Math.round((today - d) / 86400000);
  if (diff === 0) return "Hoje";
  if (diff === 1) return "Ontem";
  return `${d.getDate()} de ${MONTHS[d.getMonth()]}`;
};
function dueLabel(i) {
  if (i.days < 0) return { text: `Atrasada há ${-i.days} ${-i.days === 1 ? "dia" : "dias"}`, cls: "crit" };
  if (i.days === 0) return { text: "Vence hoje", cls: "warn" };
  if (i.days === 1) return { text: "Vence amanhã", cls: "warn" };
  const d = parseDate(i.due);
  return { text: `Vence ${d.getDate()} de ${SHORT[d.getMonth()]}`, cls: "" };
}
const catMeta = (key) => (S.category_list || []).find((c) => c.key === key);
const catLabel = (key) => catMeta(key)?.label || (key ? key[0].toUpperCase() + key.slice(1) : "");
const pickable = () => S.category_list.filter((c) => !["renda", "dividas"].includes(c.key));
const capital = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const pct = (n) => String(n).replace(".", ",");

// ---------- rede ----------

async function api(path, options = {}) {
  const init = { credentials: "same-origin", ...options };
  if (options.json !== undefined) {
    init.method = options.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.json);
  }
  const response = await fetch(path, init);
  if (response.status === 401 && path !== "/api/login") {
    renderLogin();
    throw new Error("auth");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok && response.status !== 409) {
    const detail = typeof data.detail === "string" ? data.detail : "Algo deu errado. Tente de novo.";
    throw new Error(detail);
  }
  return data;
}

async function refresh() {
  try {
    S = await api("/api/state");
    txRows = null;
    if (view === "mes") report = await api(`/api/report?month=${reportMonth}`);
    render();
  } catch (e) {
    if (e.message === "auth") return;
    if (!S) renderOffline();
  }
}

function toast(text) {
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { toastEl.hidden = true; }, 3200);
}

// ---------- telas de entrada ----------

function renderLogin() {
  root.innerHTML = `
    <form class="login" data-form="login">
      <h1>Força</h1>
      <p>Quanto você pode gastar hoje, sem surpresa no fim do mês.</p>
      <div class="form-error" id="login-error" hidden></div>
      <label class="field"><span>Senha</span><input type="password" name="password" autocomplete="current-password" required autofocus></label>
      <button class="btn full" type="submit">Entrar</button>
    </form>`;
}

function renderOffline() {
  root.innerHTML = `
    <div class="login">
      <h1>Sem conexão</h1>
      <p>Seus dados ficam no seu servidor, e não consegui falar com ele agora.</p>
      <button class="btn full" data-act="retry">Tentar de novo</button>
    </div>`;
}

// ---------- estrutura ----------

function render() {
  const active = document.activeElement;
  const keepFocus = active && active.id === "search" ? { start: active.selectionStart } : null;
  const screens = { hoje: viewToday, mes: viewMonth, contas: viewCommitments, metas: viewGoals, extrato: viewLedger };
  const tabs = [["hoje", "Hoje"], ["mes", "Mês"], ["contas", "Pagar"], ["metas", "Metas"]];
  const d = parseDate(S.today);
  const weekday = d.toLocaleDateString("pt-BR", { weekday: "long" });
  root.innerHTML = `
    <main class="app">
      <div class="topbar">
        <span class="date">${esc(capital(weekday))}, ${d.getDate()} de ${MONTHS[d.getMonth()]}</span>
        <button class="icon-btn" data-act="settings" aria-label="Ajustes">${icon("gear")}</button>
      </div>
      ${screens[view]()}
    </main>
    <nav class="nav" aria-label="Principal">
      ${tabs.map(([id, label]) => `<button data-act="tab" data-tab="${id}" ${view === id || (view === "extrato" && id === "mes") ? 'aria-current="page"' : ""}>${icon(id)}${label}</button>`).join("")}
    </nav>`;
  afterRender();
  if (keepFocus) {
    const el = document.getElementById("search");
    if (el) { el.focus(); el.setSelectionRange(keepFocus.start, keepFocus.start); }
  }
}

function afterRender() {
  document.querySelectorAll("[data-chart]").forEach((el) => drawChart(el));
  if (view === "extrato" && txRows === null) loadTx();
  if (view === "mes" && report === null) loadReport();
}

// ---------- hoje ----------

function setupSteps() {
  const income = S.recurring.filter((r) => r.kind === "income");
  const bills = S.recurring.filter((r) => r.kind === "expense");
  const skipped = (k) => { try { return localStorage.getItem(`skip-${k}`) === "1"; } catch { return false; } };
  return [
    { key: "income", name: "Quanto entra", sub: income.length ? income.map((r) => `${r.name}, ${brl(r.amount_cents)}`).join(" · ") : "Salário, bicos, o que for regular", done: income.length > 0, act: "new-income" },
    { key: "bills", name: "Contas fixas", sub: bills.length ? `${bills.length} ${bills.length === 1 ? "cadastrada" : "cadastradas"}, ${brl(bills.reduce((a, b) => a + b.amount_cents, 0))} por mês` : "Aluguel, luz, internet, assinaturas", done: bills.length >= 1 || skipped("bills"), act: "new-bill" },
    { key: "cards", name: "Cartões", sub: S.cards.length ? S.cards.map((c) => c.name).join(", ") : "Com o que a fatura já tem hoje", done: S.cards.length > 0 || skipped("cards"), act: "new-card" },
    { key: "debts", name: "Dívidas", sub: S.debts.debts.length ? `${brl(S.debts.total_cents)} no total` : "Mesmo as atrasadas. Aqui ninguém julga", done: S.debts.debts.length > 0 || skipped("debts"), act: "new-debt" },
  ];
}

function stepsList(steps) {
  return `<div class="steps">${steps.map((s) => `
    <button class="step ${s.done ? "done" : ""}" data-act="${s.act}">
      <span class="dot">${s.done ? icon("check") : ""}</span>
      <span class="main"><span class="name">${esc(s.name)}</span><span class="sub">${esc(s.sub)}</span></span>
      <span class="go">${s.done ? "Adicionar" : "Preencher"}</span>
    </button>`).join("")}</div>`;
}

function heroFigure(cents) {
  // Para baixo: o número do dia nunca promete centavos que não cabem.
  const whole = Math.floor(Math.abs(cents) / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `<small>R$</small>${whole}`;
}

function hero() {
  const { daily: t, month: m } = S;
  if (t.status === "starting") {
    const nextMonth = MONTHS[+m.month.slice(5, 7) % 12];
    return `<section class="hero">
      <div class="label">Tudo pronto para começar</div>
      <h1 class="start-title">Seu limite diário começa em 1º de ${nextMonth}.</h1>
      <p class="say">Este mês já está no fim, então um limite agora não diria nada de útil. Até lá, vá registrando o que gastar e cadastrando suas contas.</p>
    </section>`;
  }
  if (t.status === "broken") {
    return `<section class="hero broken">
      <div class="label">As contas do mês passam da sua renda em</div>
      <div class="figure" data-testid="figure">${heroFigure(-m.available_cents)}</div>
      <p class="say">Confira se os valores estão certos. Se algo estiver errado, toque no item para corrigir ou excluir.</p>
      <button class="btn quiet" style="margin-top:14px" data-act="tab" data-tab="contas">Ver o que pagar</button>
    </section>`;
  }
  const over = t.left_cents < 0;
  const spentShare = t.allowance_cents > 0 ? Math.min(100, (t.spent_cents / t.allowance_cents) * 100) : (t.spent_cents > 0 ? 100 : 0);
  let label = "Hoje você pode gastar";
  let say = `Com isso, você chega ao fim de ${monthName(m.month)} com as contas pagas. ${t.days_left === 1 ? "É o último dia do mês." : `Faltam ${t.days_left} dias.`}`;
  if (over) {
    label = "Hoje você passou";
    say = `Tudo bem, acontece. Para o mês fechar, seu limite de amanhã é ${brl(t.tomorrow_cents, { noCents: true })}.`;
  } else if (t.spent_cents > 0) {
    label = "Ainda cabe hoje";
    say = `Dos ${brl(t.allowance_cents, { noCents: true })} de hoje, já foi ${brl(t.spent_cents, { noCents: true })}. Amanhã, no ritmo atual: ${brl(t.tomorrow_cents, { noCents: true })}.`;
  } else if (t.status === "tight") {
    say = `O limite está apertado porque o mês foi mais pesado até aqui. Faltam ${t.days_left} dias.`;
  }
  const cls = over ? "over" : (t.status === "tight" ? "tight" : "");
  return `<section class="hero ${cls}">
    <div class="label">${label}</div>
    <div class="figure" data-testid="figure">${heroFigure(over ? -t.left_cents : t.left_cents)}</div>
    <p class="say">${esc(say)}</p>
    <div class="day-track" role="img" aria-label="${Math.round(spentShare)}% do limite de hoje usado"><i style="width:${spentShare}%"></i></div>
  </section>`;
}

function captureBox(placeholder = "mercado 87") {
  return `<form class="capture" data-form="quick">
      <input name="text" autocomplete="off" enterkeyhint="send" placeholder="${placeholder}" aria-label="Registrar gasto ou perguntar">
      <button type="submit" aria-label="Enviar">${icon("send")}</button>
    </form>
    <div id="result">${resultBlock()}</div>`;
}

function resultBlock() {
  if (!lastResult) return "";
  const r = lastResult;
  if (r.type === "assessment") {
    return `<div class="result" role="status">${esc(r.message)}
      <div class="row-actions">
        <button class="btn" data-act="purchase" data-choice="wait">Esperar 24h</button>
        <button class="btn quiet" data-act="purchase" data-choice="skip">Desisti</button>
        <button class="btn quiet" data-act="purchase" data-choice="buy">Comprei</button>
      </div></div>`;
  }
  if (r.type === "check") {
    return `<div class="result" role="status">${esc(r.message)}
      <div class="row-actions">
        <button class="btn" data-act="confirm-quick">Sim, registrar</button>
        <button class="btn quiet" data-act="cancel-quick">Não, errei</button>
      </div></div>`;
  }
  const head = r.type === "expense" ? `${esc(r.description)} · ${brl(r.amount_cents)} · ${esc(catLabel(r.category).toLowerCase())}\n`
    : r.type === "income" ? `Entrou ${brl(r.amount_cents)}\n` : "";
  const cards = r.needs_card ? `<div class="row-actions">${S.cards.map((c) => `<button class="btn quiet" data-act="assign-card" data-card="${c.id}">${esc(c.name)}</button>`).join("")}</div>` : "";
  const undo = r.id ? `<div class="row-actions"><button class="btn quiet" data-act="undo-last">Desfazer</button><button class="btn quiet" data-act="edit-last">Ajustar</button></div>` : "";
  return `<div class="result" role="status">${head}${esc(r.message)}${cards}${undo}</div>`;
}

function upcomingList(items) {
  return `<div class="list">${items.map((i) => {
    const d = dueLabel(i);
    return `<div class="item">
      <span class="main"><span class="name">${esc(i.name)}</span><span class="sub ${d.cls}">${d.text}</span></span>
      <span class="value">${brl(i.amount_cents)}</span>
      <button class="pay" data-act="paid" data-type="${i.type}" data-id="${i.id}" data-month="${i.month}">Paguei</button>
    </div>`;
  }).join("")}</div>`;
}

function txItem(t) {
  const parts = [];
  if (t.category && t.kind === "expense") parts.push(catLabel(t.category));
  if (t.card_name) parts.push(t.card_name);
  if (t.installment_total) parts.push(`${t.installment_no}/${t.installment_total}`);
  return `<button class="item" data-act="edit-tx" data-id="${t.id}">
    <span class="main"><span class="name">${esc(t.description)}</span><span class="sub">${esc(parts.join(" · "))}</span></span>
    <span class="value ${t.kind === "income" ? "in" : ""}">${t.kind === "income" ? "+" : ""}${brl(t.amount_cents)}</span>
  </button>`;
}

function viewToday() {
  const steps = setupSteps();
  const pending = steps.filter((s) => !s.done);
  if (S.daily.status === "setup") {
    return `<section class="welcome">
        <h1>Vamos pôr isso em ordem.</h1>
        <p class="muted">Comece só pelo primeiro item. Valores aproximados servem: dá para mudar depois.${S.settings.paired ? " Prefere conversando? Mande /comecar no Telegram." : ""}</p>
      </section>
      ${stepsList(steps)}
      ${telegramNotice()}`;
  }
  const next = S.upcoming.filter((i) => i.days <= 7).slice(0, 3);
  const f = S.focus && S.focus.tone !== "neutral" ? S.focus : null;  // Hoje só mostra o urgente
  const missing = pending.length ? pending[0] : null;
  return `${hero()}
    ${captureBox()}
    <p class="tiny hint">Escreva como falaria: mercado 87, ou "posso comprar um tênis de 400?"</p>
    ${f ? `<aside class="focus ${f.tone}"><h3>${esc(f.title)}</h3><p>${esc(f.body)}</p></aside>` : ""}
    ${missing ? `<button class="notice wide" data-act="${missing.act}"><span><b>Próximo passo: ${esc(missing.name.toLowerCase())}</b><br><span class="small muted">${esc(missing.sub)}</span></span><span class="go">Preencher</span></button>` : (telegramNotice() || installNotice())}
    ${next.length ? `<section class="section"><div class="section-head"><h2>Vence em breve</h2></div>${upcomingList(next)}</section>` : ""}
    ${S.pauses.length ? `<section class="section"><div class="section-head"><h2>Esperando 24 horas</h2></div>
      <div class="list">${S.pauses.map((p) => `<div class="item">
        <span class="main"><span class="name">${esc(p.item)}</span><span class="sub">${brl(p.amount_cents)}</span></span>
        <button class="pay" data-act="pause" data-id="${p.id}" data-status="skipped">Desisti</button>
        <button class="pay" data-act="pause" data-id="${p.id}" data-status="bought">Comprei</button>
      </div>`).join("")}</div></section>` : ""}
    ${S.recent.length ? `<section class="section"><div class="section-head"><h2>Últimos gastos</h2><button class="link" data-act="tab" data-tab="extrato">Ver todos</button></div>
      <div class="list">${S.recent.slice(0, 3).map(txItem).join("")}</div></section>` : ""}`;
}

function telegramNotice() {
  const s = S.settings;
  if (!s.telegram || s.paired || !s.bot_username || !s.pair_code) return "";
  return `<div class="notice"><span>Conecte o Telegram para registrar e receber avisos.</span>
    <a class="btn" href="https://t.me/${encodeURIComponent(s.bot_username)}?start=${encodeURIComponent(s.pair_code)}" target="_blank" rel="noopener">Conectar</a></div>`;
}

function installNotice() {
  if (!installEvent) return "";
  return `<div class="notice"><span>Instale no celular para abrir com um toque.</span><button class="btn quiet" data-act="install">Instalar</button></div>`;
}

// ---------- mês ----------

async function loadReport() {
  try {
    report = await api(`/api/report?month=${reportMonth}`);
    if (view === "mes") render();
  } catch (e) {
    if (e.message !== "auth") toast(e.message);
  }
}

function shiftMonth(month, n) {
  const [y, m] = month.split("-").map(Number);
  const t = y * 12 + (m - 1) + n;
  return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
}

function viewMonth() {
  if (!report) return `<div class="empty">Carregando…</div>`;
  const m = report;
  const line = (label, cents, sign = "−") => (cents ? `<div class="line"><span>${label}</span><span>${sign} ${brl(cents)}</span></div>` : "");
  const past = m.is_current ? S.pace.filter((p) => p.spent_cents !== null) : [];
  return `<div class="month-nav">
      <button class="icon-btn" data-act="month-nav" data-month="${shiftMonth(m.month, -1)}" aria-label="Mês anterior">‹</button>
      <h1 class="page-title">${monthName(m.month)}</h1>
      ${m.can_go_next ? `<button class="icon-btn" data-act="month-nav" data-month="${shiftMonth(m.month, 1)}" aria-label="Próximo mês">›</button>` : `<span class="icon-btn"></span>`}
    </div>
    <section class="ledger">
      <div class="line"><span>Entra${m.income_is_estimate ? " (previsto)" : ""}</span><span>${brl(m.income_cents)}</span></div>
      ${line("Contas fixas", m.fixed_cents)}
      ${line("Dívidas", m.debts_cents)}
      ${line("Metas", m.goals_cents)}
      ${line("Parcelas antigas", m.committed_cents)}
      ${line("Passou do limite no mês anterior", m.carry_cents)}
      <div class="line total"><span>Sobra para gastar no mês</span><span>${brl(m.available_cents)}</span></div>
      ${line("Já gastou", m.spent_cents)}
      <div class="line big ${m.remaining_cents < 0 ? "neg" : ""}"><span>${m.is_current ? "Ainda pode gastar" : "Sobrou"}</span><b>${brl(m.remaining_cents, { noCents: true })}</b></div>
    </section>
    ${m.insights.length ? `<section class="insights">${m.insights.map((i) => `<p class="insight ${i.tone}">${esc(i.text)}</p>`).join("")}</section>` : ""}
    <section class="section">
      <div class="section-head"><h2>Onde você gastou</h2>${m.is_current ? `<button class="link" data-act="budgets">Limites</button>` : ""}</div>
      ${categoryBars(m)}
      ${m.spent_cents ? `<p class="tiny" style="margin-top:6px">Média de ${brl(m.daily_average_cents, { noCents: true })} por dia. Contas fixas e dívidas ficam de fora desta lista.</p>` : ""}
    </section>
    ${m.top_expenses.length ? `<section class="section"><div class="section-head"><h2>Maiores gastos</h2><button class="link" data-act="tab" data-tab="extrato">Ver todos</button></div>
      <div class="list">${m.top_expenses.map((t) => `<div class="item"><span class="main"><span class="name">${esc(t.description)}</span><span class="sub">${esc(catLabel(t.category))} · ${parseDate(t.date).getDate()} de ${SHORT[parseDate(t.date).getMonth()]}</span></span><span class="value">${brl(t.amount_cents)}</span></div>`).join("")}</div></section>` : ""}
    ${!m.top_expenses.length ? `<button class="btn quiet full section" data-act="tab" data-tab="extrato">Ver lançamentos e importar extrato</button>` : ""}
    ${m.history.length > 1 ? `<section class="section"><div class="section-head"><h2>Mês a mês</h2></div>${historyBars(m.history, m.month)}</section>` : ""}
    ${past.some((p) => p.spent_cents > 0) ? `<details class="table-view section" data-keep><summary>Ver gráfico do mês</summary>
        <div class="legend"><span><i></i>Seu gasto</span><span><i class="ref"></i>Limite até aquele dia</span></div>
        <div class="chart" data-chart="pace"></div>
        <table><thead><tr><th>Dia</th><th>Gasto</th><th>Limite</th></tr></thead><tbody>
          ${past.map((p) => `<tr><td>${p.day}</td><td>${brl(p.spent_cents, { noCents: true })}</td><td>${brl(p.ideal_cents, { noCents: true })}</td></tr>`).join("")}
        </tbody></table></details>` : ""}`;
}

function historyBars(history, current) {
  const max = Math.max(1, ...history.map((h) => h.spent_cents));
  return `<div class="bars" role="img" aria-label="${history.map((h) => `${monthName(h.month)}: ${brl(h.spent_cents, { noCents: true })}`).join(", ")}">
    ${history.map((h) => `<div class="col ${h.month === current ? "open" : ""}" title="${monthFull(h.month)}: ${brl(h.spent_cents)}">
      <em>${brl(h.spent_cents, { noCents: true }).replace("R$ ", "")}</em>
      <i style="height:${Math.max(2, (h.spent_cents / max) * 56)}px"></i>
      <span>${monthShort(h.month)}</span>
    </div>`).join("")}</div>`;
}

function categoryBars(m) {
  const rows = m.categories.filter((c) => c.spent_cents > 0 || c.limit_cents);
  if (!rows.length) return `<div class="empty">Nenhum gasto neste mês ainda.</div>`;
  const max = Math.max(...rows.map((r) => Math.max(r.spent_cents, r.limit_cents || 0)));
  return rows.map((r) => {
    const base = r.limit_cents || max;
    const share = Math.min(100, (r.spent_cents / base) * 100);
    const ratio = r.limit_cents ? r.spent_cents / r.limit_cents : 0;
    const cls = ratio >= 1 ? "past" : ratio >= 0.8 ? "near" : "";
    const parts = [];
    if (r.limit_cents) parts.push(ratio >= 1 ? `Passou ${brl(r.spent_cents - r.limit_cents, { noCents: true })} do limite` : `Restam ${brl(r.limit_cents - r.spent_cents, { noCents: true })}`);
    // Mês em andamento não dá para comparar com um mês inteiro: mostra só a referência.
    if (m.is_current && r.previous_cents) parts.push(`Mês passado: ${brl(r.previous_cents, { noCents: true })}`);
    else if (!m.is_current && r.delta_cents) parts.push(`${brl(Math.abs(r.delta_cents), { noCents: true })} ${r.delta_cents > 0 ? "a mais" : "a menos"} que no mês anterior`);
    return `<button class="cat ${cls}" data-act="new-budget" data-category="${esc(r.category)}">
      <span class="top"><span class="name with-icon">${catIcon(r.icon)}${esc(r.label)}</span><span class="amount">${brl(r.spent_cents, { noCents: true })}${r.limit_cents ? ` <span>de ${brl(r.limit_cents, { noCents: true })}</span>` : ""}</span></span>
      <div class="bar"><i style="width:${share}%"></i></div>
      ${parts.length ? `<div class="state">${parts.join(" · ")}</div>` : ""}
    </button>`;
  }).join("");
}

// ---------- metas ----------

function viewGoals() {
  const expensive = S.debts.debts.some((d) => d.monthly_rate >= 3);
  if (!S.goals.length) {
    return `<h1 class="page-title">Metas</h1>
      <div class="empty"><strong>Guarde com um motivo.</strong>Comece por uma reserva para imprevistos: é ela que evita voltar para o cartão quando algo dá errado.</div>
      <button class="btn full" data-act="new-reserve">Criar reserva de emergência</button>
      <button class="btn quiet full" style="margin-top:10px" data-act="new-goal">Outra meta</button>`;
  }
  return `<div class="toolbar"><h1 class="page-title">Metas</h1><button class="btn quiet" data-act="new-goal">Nova meta</button></div>
    ${expensive ? `<p class="note warn">Você tem dívida com juros altos. Uma reserva pequena ajuda, mas o resto rende mais quitando a dívida.</p>` : ""}
    <div class="goals">${S.goals.map(goalCard).join("")}</div>`;
}

function goalCard(g) {
  const share = Math.min(100, (g.saved_cents / g.target_cents) * 100);
  let status = "Defina quanto guardar por mês para ver quando termina.";
  if (g.done) status = "Meta concluída.";
  else if (g.finish_month) status = `${brl(g.monthly_cents, { noCents: true })} por mês, termina em ${monthFull(g.finish_month)}.`;
  const late = g.on_time === false;
  return `<article class="goal ${g.done ? "done" : ""}">
    <button class="goal-head" data-act="edit-goal" data-id="${g.id}">
      <span class="goal-name">${esc(g.name)}</span>
      <span class="goal-amount">${brl(g.saved_cents, { noCents: true })} <span>de ${brl(g.target_cents, { noCents: true })}</span></span>
    </button>
    <div class="bar" role="img" aria-label="${Math.round(share)}% guardado"><i style="width:${share}%"></i></div>
    <p class="small muted" style="margin-top:8px">${esc(status)}</p>
    ${late ? `<p class="small" style="color:var(--warn);font-weight:500">Nesse ritmo, passa do prazo de ${esc(monthFull(g.due_month))}.</p>` : ""}
    ${!g.done && g.due_this_month_cents ? `<p class="small muted">Falta guardar ${brl(g.due_this_month_cents, { noCents: true })} este mês.</p>` : ""}
    <div class="row-actions" style="margin-top:12px"><button class="btn quiet" data-act="goal-deposit" data-id="${g.id}">${g.done ? "Retirar" : "Guardar"}</button></div>
  </article>`;
}

function sheetGoal(goal, preset = {}) {
  const v = goal || preset;
  const hint = !goal && preset.target_cents ? "Sugestão: 3 meses de contas fixas e parcelas. Mude à vontade." : "";
  openSheet(goal ? "Editar meta" : "Nova meta", "Guardar não conta como gasto, mas o valor por mês é reservado no seu orçamento.", `
    <form data-form="goal" data-id="${goal ? goal.id : ""}">
      ${field("Nome", "name", v.name, 'required maxlength="80" placeholder="Viagem"')}
      ${moneyField("Quanto quer juntar", "target", v.target_cents, "required", hint)}
      <div class="field-row">
        ${field("Até quando (opcional)", "due_month", v.due_month || "", 'type="month"')}
        ${moneyField("Por mês (opcional)", "monthly", v.monthly_cents || null, "", "")}
      </div>
      <p class="tiny" style="margin:-6px 0 14px">Com prazo e sem valor por mês, eu calculo quanto guardar.</p>
      ${formActions(goal ? "remove-goal" : "")}
    </form>
    ${goal && goal.deposits.length ? `<h3 class="sheet-sub">Últimos registros</h3><div class="list">${goal.deposits.map((d) => `<div class="item">
      <span class="main"><span class="name">${d.amount_cents > 0 ? "Guardou" : "Retirou"} ${brl(Math.abs(d.amount_cents))}</span><span class="sub">${parseDate(d.date).getDate()} de ${SHORT[parseDate(d.date).getMonth()]}</span></span>
      <button class="pay" data-act="remove-deposit" data-id="${d.id}">Remover</button></div>`).join("")}</div>` : ""}`);
}

function sheetDeposit(g) {
  openSheet(g.name, `Já são ${brl(g.saved_cents)} de ${brl(g.target_cents)}.`, `
    <form data-form="deposit" data-id="${g.id}">
      ${moneyField("Valor", "amount", g.due_this_month_cents || null)}
      <label class="check"><input type="checkbox" name="withdraw" ${g.done ? "checked" : ""}>Estou retirando dessa meta</label>
      ${formActions("")}
    </form>`);
}

// ---------- limites e categorias ----------

function sheetBudgets() {
  const spentOf = (key) => S.categories.find((c) => c.category === key) || {};
  const total = S.categories.reduce((a, c) => a + (c.limit_cents || 0), 0);
  const room = S.month.available_cents;
  const note = !total ? "Escolha as categorias que mais pesam. Não precisa definir todas."
    : total > room ? `Seus limites somam ${brl(total, { noCents: true })}, mais que os ${brl(room, { noCents: true })} que sobram no mês.`
    : `Seus limites somam ${brl(total, { noCents: true })} dos ${brl(room, { noCents: true })} que sobram no mês.`;
  openSheet("Limites por categoria", note, `
    <div class="list">${pickable().map((c) => {
      const r = spentOf(c.key);
      return `<button class="item" data-act="new-budget" data-category="${esc(c.key)}">
        <span class="main"><span class="name with-icon">${catIcon(c.icon)}${esc(c.label)}</span><span class="sub">${r.spent_cents ? `Gastou ${brl(r.spent_cents, { noCents: true })} este mês` : "Sem gastos este mês"}</span></span>
        <span class="${r.limit_cents ? "value" : "go"}">${r.limit_cents ? brl(r.limit_cents, { noCents: true }) : "Definir"}</span>
      </button>`;
    }).join("")}</div>
    <button class="btn quiet full" style="margin-top:18px" data-act="categories">Gerenciar categorias</button>`);
}

function sheetCategories() {
  openSheet("Categorias", "Toque em uma para mudar o nome ou remover.", `
    <div class="list">${pickable().map((c) => `<button class="item" data-act="${c.key === "outros" ? "noop" : "edit-category"}" data-key="${esc(c.key)}">
      <span class="main"><span class="name with-icon">${catIcon(c.icon)}${esc(c.label)}</span></span>
    </button>`).join("")}</div>
    <button class="btn full" style="margin-top:18px" data-act="new-category">Nova categoria</button>`);
}

const ICON_CHOICES = ["cart", "plate", "coffee", "car", "fuel", "home", "tool", "bulb", "phone", "repeat", "health", "dumbbell", "ticket", "game", "plane", "bag", "shirt", "scissors", "book", "people", "paw", "gift", "briefcase", "receipt", "coin", "card", "leaf", "star", "dot"];

function sheetCategory(cat) {
  const current = CATEGORY_ICONS[cat?.icon] ? cat.icon : "dot";
  openSheet(cat ? "Editar categoria" : "Nova categoria", cat ? "" : "Com o nome, eu já reconheço: \"pilates 90\" cai em Pilates.", `
    <form data-form="category" data-key="${cat ? esc(cat.key) : ""}">
      ${field("Nome", "label", cat?.label, 'required maxlength="30" placeholder="Pilates"')}
      <input type="hidden" name="icon" value="${esc(current)}">
      <div class="field"><span>Ícone</span><div class="icon-grid">${ICON_CHOICES.map((i) => `<button type="button" class="icon-pick" data-act="pick-icon" data-icon="${i}" aria-pressed="${i === current}" aria-label="Ícone ${i}">${catIcon(i)}</button>`).join("")}</div>
      ${cat ? `<em>Ao remover, os gastos dela passam para Outros.</em>` : ""}</div>
      ${formActions(cat ? "remove-category" : "")}
    </form>`);
}

// ---------- contas, cartões e dívidas ----------

function viewCommitments() {
  const bills = S.recurring.filter((r) => r.kind === "expense");
  const incomes = S.recurring.filter((r) => r.kind === "income");
  const sum = (list) => list.reduce((a, b) => a + b.amount_cents, 0);
  const rows = [
    ["list-income", "Renda", incomes.length ? `${brl(sum(incomes), { noCents: true })} por mês` : "Nada cadastrado"],
    ["list-bills", "Contas fixas", bills.length ? `${bills.length} ${bills.length === 1 ? "conta" : "contas"}, ${brl(sum(bills), { noCents: true })} por mês` : "Nada cadastrado"],
    ["list-cards", "Cartões", S.cards.length ? S.cards.map((c) => c.name).join(", ") : "Nada cadastrado"],
    ["list-debts", "Dívidas", S.debts.debts.length ? `${brl(S.debts.total_cents, { noCents: true })} no total` : "Nada cadastrado"],
  ];
  return `<h1 class="page-title">Pagar</h1>
    <section class="section" style="margin-top:12px">
      <div class="section-head"><h2>O que vence</h2></div>
      ${S.upcoming.length ? upcomingList(S.upcoming.filter((i) => i.days <= 31)) : `<div class="empty">Nada a pagar nos próximos 30 dias.</div>`}
    </section>
    <section class="section">
      <div class="section-head"><h2>Meus cadastros</h2></div>
      <div class="list">${rows.map(([act, name, sub]) => `<button class="item" data-act="${act}">
        <span class="main"><span class="name">${name}</span><span class="sub">${esc(sub)}</span></span><span class="go">Abrir</span>
      </button>`).join("")}</div>
    </section>`;
}

function sheetList(title, addAct, addLabel, body) {
  openSheet(title, "Toque em um item para editar ou excluir.", `${body}
    <button class="btn full" style="margin-top:18px" data-act="${addAct}">${addLabel}</button>`);
}

function recurringItem(r) {
  return `<button class="item" data-act="edit-recurring" data-id="${r.id}">
    <span class="main"><span class="name">${esc(r.name)}</span><span class="sub">Todo dia ${r.day}${r.paid_this_month ? (r.kind === "income" ? " · recebido" : " · pago") : ""}</span></span>
    <span class="value">${brl(r.amount_cents)}</span>
  </button>`;
}

function cardBlock(c) {
  const max = Math.max(1, ...c.invoices.map((i) => i.total_cents));
  const bars = c.invoices.slice(0, 6).map((i) => `
    <div class="col ${i.open ? "open" : ""}" title="${monthFull(i.month)}: ${brl(i.total_cents)}">
      ${i.open || i.total_cents === max ? `<em>${brl(i.total_cents, { noCents: true }).replace("R$ ", "")}</em>` : ""}
      <i style="height:${Math.max(2, (i.total_cents / max) * 56)}px"></i>
      <span>${monthShort(i.month)}</span>
    </div>`).join("");
  return `<div class="card-box">
    <button style="width:100%;text-align:left" data-act="edit-card" data-id="${c.id}">
      <span class="top" style="display:flex"><span class="title">${esc(c.name)}</span><span class="amount">${brl(c.current_invoice_cents, { noCents: true })}</span></span>
      <span class="tiny" style="display:block">Fatura aberta · fecha em ${c.days_to_closing} ${c.days_to_closing === 1 ? "dia" : "dias"} · melhor dia para comprar: ${c.best_day}</span>
    </button>
    <div class="bars" role="img" aria-label="Faturas dos próximos meses: ${c.invoices.slice(0, 6).map((i) => `${monthName(i.month)} ${brl(i.total_cents, { noCents: true })}`).join(", ")}">${bars}</div>
    ${c.future_committed_cents ? `<p class="note">${brl(c.future_committed_cents, { noCents: true })} já comprometidos nas próximas faturas.</p>` : ""}
  </div>`;
}

let debtPreview = null;

function sheetDebts() {
  sheetList("Dívidas", "new-debt", "Adicionar dívida", debtsBody());
  sheet.querySelectorAll("[data-chart]").forEach((el) => drawChart(el));
}

function debtsBody() {
  const d = S.debts;
  if (!d.debts.length) return `<div class="empty">Nenhuma dívida cadastrada.</div>`;
  const maxExtra = Math.max(50000, Math.min(500000, Math.ceil(Math.max(0, S.month.available_cents) / 50000) * 50000 || 50000), d.extra_cents);
  return `
    <div class="debt-total">${brl(d.total_cents, { noCents: true })}</div>
    <p class="muted small">${d.monthly_interest_cents ? `Custam ${brl(d.monthly_interest_cents, { noCents: true })} de juros por mês.` : "Sem juros cadastrados."}</p>
    <div class="freedom" id="freedom">${freedomBlock(d.plan, d.free_month, d.extra_cents)}
      <input type="range" id="extra" min="0" max="${maxExtra}" step="1000" value="${d.extra_cents}" aria-label="Quanto a mais pagar por mês">
      <div class="tiny">Arraste para ver quanto pagar a mais por mês muda a data.</div>
      <div class="chart" data-chart="debt" id="debt-chart"></div>
      <div class="segmented" role="group" aria-label="Estratégia">
        <button data-act="strategy" data-value="avalanche" aria-pressed="${d.strategy === "avalanche"}">Pagar maior juro antes</button>
        <button data-act="strategy" data-value="snowball" aria-pressed="${d.strategy === "snowball"}">Menor dívida antes</button>
      </div>
      <p class="note">${strategyNote(d)}</p>
    </div>
    <div class="list" style="margin-top:16px">${d.debts.map((x, i) => `<button class="item" data-act="edit-debt" data-id="${x.id}">
      <span class="main"><span class="name">${esc(x.name)}</span>
        <span class="sub ${x.overdue || x.never_ends ? "crit" : ""}">${i === 0 ? '<span class="target-tag">Próximo alvo</span> · ' : ""}${pct(x.monthly_rate)}% ao mês${x.overdue ? " · em atraso" : ""}${x.never_ends && !x.overdue ? " · o mínimo não abate" : ""}</span></span>
      <span class="value">${brl(x.balance_cents, { noCents: true })}</span>
    </button>`).join("")}</div>`;
}

function strategyNote(d) {
  const other = d.other_strategy;
  if (!d.plan.feasible || !other.months) return "O maior juro ataca o que mais custa. O menor saldo dá vitórias mais rápidas.";
  const diff = other.total_interest_cents - d.plan.total_interest_cents;
  if (diff > 0) return `Esta ordem economiza ${brl(diff, { noCents: true })} de juros em relação à outra.`;
  if (diff < 0) return `A outra ordem economizaria ${brl(-diff, { noCents: true })} de juros. Esta dá vitórias mais rápidas.`;
  return "As duas ordens custam o mesmo aqui.";
}

function freedomBlock(plan, freeMonth, extra) {
  if (!plan.feasible) {
    return `<div class="tiny">Com ${extra ? `${brl(extra, { noCents: true })} a mais por mês` : "os pagamentos atuais"}</div>
      <div class="when" style="color:var(--crit)">Não termina nunca</div>
      <p class="small muted">Os juros crescem mais rápido do que você paga. Aumente o extra ou renegocie a dívida mais cara.</p>`;
  }
  return `<div class="tiny">${extra ? `Com ${brl(extra, { noCents: true })} a mais por mês` : "Pagando só os mínimos"}, você fica livre em</div>
    <div class="when">${esc(monthFull(freeMonth))}</div>
    <p class="small muted">${plan.months} ${plan.months === 1 ? "mês" : "meses"}, ${brl(plan.total_interest_cents, { noCents: true })} de juros no caminho.</p>`;
}

// ---------- extrato ----------

function viewLedger() {
  const options = monthOptions();
  return `<button class="link back" data-act="tab" data-tab="mes">‹ Mês</button>
    <div class="toolbar"><h1 class="page-title">Lançamentos</h1><button class="btn quiet" data-act="import">Importar extrato</button></div>
    <input class="search" id="search" type="search" placeholder="Buscar" value="${esc(txQuery)}" aria-label="Buscar lançamentos">
    <label class="field" style="margin:10px 0 0"><span hidden>Mês</span><select id="month-filter" aria-label="Mês">
      <option value="">Todos</option>${options.map((m) => `<option value="${m}" ${m === txMonth ? "selected" : ""}>${capital(monthFull(m))}</option>`).join("")}
    </select></label>
    <input type="file" id="file" accept=".ofx,.qfx,.csv,.txt,.pdf" hidden>
    <div id="tx-list">${txListHtml()}</div>`;
}

function monthOptions() {
  const out = [];
  let [y, m] = S.month.month.split("-").map(Number);
  for (let i = 0; i < 12; i++) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m -= 1;
    if (m === 0) { m = 12; y -= 1; }
  }
  return out;
}

function txListHtml() {
  if (txRows === null) return `<div class="empty">Carregando…</div>`;
  if (!txRows.length) {
    if (txQuery || txMonth) return `<div class="empty">Nada encontrado.</div>`;
    return `<div class="empty"><strong>Seu extrato começa aqui.</strong>Importe o OFX ou CSV do banco e eu separo tudo, sem duplicar o que você já registrou.</div>`;
  }
  const groups = new Map();
  txRows.forEach((t) => { if (!groups.has(t.date)) groups.set(t.date, []); groups.get(t.date).push(t); });
  return [...groups.entries()].map(([d, rows]) => {
    const total = rows.filter((r) => r.kind === "expense").reduce((a, r) => a + r.amount_cents, 0);
    return `<div class="day-head"><span>${esc(dayLabel(d))}</span><span>${total ? brl(total) : ""}</span></div>${rows.map(txItem).join("")}`;
  }).join("");
}

async function loadTx() {
  const params = new URLSearchParams();
  if (txQuery) params.set("q", txQuery);
  if (txMonth) params.set("month", txMonth);
  try {
    txRows = await api(`/api/transactions?${params}`);
    const el = document.getElementById("tx-list");
    if (el) el.innerHTML = txListHtml();
  } catch (e) {
    if (e.message !== "auth") toast(e.message);
  }
}

// ---------- gráficos ----------

function drawChart(el) {
  const kind = el.dataset.chart;
  if (kind === "pace") {
    lineChart(el, {
      points: S.pace.map((p) => ({ x: p.day, y: p.spent_cents, ref: p.ideal_cents })),
      label: (p) => `Dia ${p.x}`,
      ticks: [1, 10, 20, S.pace.length],
      tickLabel: (x) => String(x),
      refName: "Limite",
      mainName: "Gasto",
    });
  } else if (kind === "debt") {
    const plan = debtPreview || S.debts.plan;
    const timeline = plan.timeline.slice(0, 121);
    const start = S.month.month;
    const monthAt = (i) => {
      let [y, m] = start.split("-").map(Number);
      const t = y * 12 + (m - 1) + i;
      return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
    };
    const n = timeline.length;
    lineChart(el, {
      points: timeline.map((v, i) => ({ x: i, y: v })),
      label: (p) => (p.x === 0 ? "Hoje" : `${capital(monthShort(monthAt(p.x)))} ${monthAt(p.x).slice(0, 4)}`),
      ticks: n > 2 ? [0, Math.round((n - 1) / 2), n - 1] : [0, n - 1],
      tickLabel: (x) => (x === 0 ? "Hoje" : `${monthShort(monthAt(x))} ${monthAt(x).slice(2, 4)}`),
      mainName: "Saldo",
      area: true,
      height: 120,
    });
  }
}

function lineChart(el, cfg) {
  const W = 600, H = cfg.height ? cfg.height + 40 : 200;
  const pad = { l: 0, r: 0, t: 12, b: 26 };
  const pts = cfg.points;
  const xMin = pts[0].x, xMax = Math.max(pts[pts.length - 1].x, xMin + 1);
  const yMax = Math.max(1, ...pts.map((p) => Math.max(p.y || 0, p.ref || 0)));
  const X = (x) => pad.l + ((x - xMin) / (xMax - xMin)) * (W - pad.l - pad.r);
  const Y = (y) => H - pad.b - (y / yMax) * (H - pad.t - pad.b);
  const known = pts.filter((p) => p.y !== null);
  const line = known.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)} ${Y(p.y).toFixed(1)}`).join("");
  const refLine = pts[0].ref !== undefined ? pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)} ${Y(p.ref).toFixed(1)}`).join("") : "";
  const area = cfg.area && known.length ? `${line}L${X(known[known.length - 1].x).toFixed(1)} ${Y(0)}L${X(known[0].x).toFixed(1)} ${Y(0)}Z` : "";
  const last = known[known.length - 1];
  const ticks = cfg.ticks.map((x, i) => {
    const anchor = i === 0 ? "start" : i === cfg.ticks.length - 1 ? "end" : "middle";
    return `<text class="axis" x="${X(x)}" y="${H - 6}" text-anchor="${anchor}">${esc(cfg.tickLabel(x))}</text>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Gráfico: valor final ${last ? brl(last.y, { noCents: true }) : ""}">
      <line class="grid" x1="0" x2="${W}" y1="${Y(0)}" y2="${Y(0)}"/>
      ${area ? `<path class="area" d="${area}"/>` : ""}
      ${refLine ? `<path class="ref-line" d="${refLine}"/>` : ""}
      <path class="main-line" d="${line}"/>
      ${last ? `<circle class="dot end" cx="${X(last.x)}" cy="${Y(last.y)}" r="4.5"/>` : ""}
      <line class="cross" x1="0" x2="0" y1="${pad.t}" y2="${H - pad.b}" visibility="hidden"/>
      <circle class="dot hover" r="4.5" visibility="hidden"/>
      ${ticks}
    </svg>
    <div class="tooltip" hidden></div>`;
  const svg = el.querySelector("svg");
  const tip = el.querySelector(".tooltip");
  const cross = el.querySelector(".cross");
  const hover = el.querySelector(".dot.hover");
  const move = (event) => {
    const rect = svg.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * W;
    const pool = known.length ? known : pts;
    let best = pool[0];
    pool.forEach((p) => { if (Math.abs(X(p.x) - px) < Math.abs(X(best.x) - px)) best = p; });
    cross.setAttribute("x1", X(best.x)); cross.setAttribute("x2", X(best.x)); cross.setAttribute("visibility", "visible");
    hover.setAttribute("cx", X(best.x)); hover.setAttribute("cy", Y(best.y)); hover.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.innerHTML = `<span>${esc(cfg.label(best))}</span>${esc(cfg.mainName)}: ${brl(best.y, { noCents: true })}${best.ref !== undefined ? `<span>${esc(cfg.refName)}: ${brl(best.ref, { noCents: true })}</span>` : ""}`;
    const left = (X(best.x) / W) * rect.width;
    const half = tip.offsetWidth / 2;
    tip.style.left = `${Math.min(rect.width - half, Math.max(half, left))}px`;
  };
  const leave = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); hover.setAttribute("visibility", "hidden"); };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerdown", move);
  el.addEventListener("pointerleave", leave);
}

// ---------- folhas ----------

function openSheet(title, sub, body) {
  sheet.innerHTML = `<div class="sheet-body">
    <div class="sheet-head"><div><h2>${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ""}</div>
      <button class="link" data-act="close-sheet">Fechar</button></div>${body}</div>`;
  if (!sheet.open) sheet.showModal();
}
const closeSheet = () => sheet.close();

const field = (label, name, value = "", attrs = "", hint = "") =>
  `<label class="field"><span>${label}</span><input name="${name}" value="${esc(value)}" ${attrs}>${hint ? `<em>${hint}</em>` : ""}</label>`;
const moneyField = (label, name, cents, attrs = "required", hint = "") => field(label, name, fromCents(cents), `inputmode="decimal" placeholder="0,00" ${attrs}`, hint);
const dayField = (label, name, value, hint = "") => field(label, name, value, 'type="number" inputmode="numeric" min="1" max="31" required', hint);
const formActions = (removeAct) => `<div class="form-error" hidden></div><div class="sheet-actions">
  ${removeAct ? `<button type="button" class="btn danger" data-act="${removeAct}">Remover</button>` : ""}
  <button class="btn" type="submit">Salvar</button></div>`;

function sheetRecurring(kind, item) {
  const income = kind === "income";
  openSheet(item ? "Editar" : income ? "Quanto entra" : "Conta fixa", income ? "Se varia, use um valor conservador." : "O que sai todo mês, em valor aproximado.", `
    <form data-form="recurring" data-kind="${kind}" data-id="${item ? item.id : ""}">
      ${field("Nome", "name", item?.name, `required maxlength="80" placeholder="${income ? "Salário" : "Aluguel"}"`)}
      <div class="field-row">${moneyField("Valor", "amount", item?.amount_cents)}${dayField(income ? "Cai no dia" : "Vence no dia", "day", item?.day)}</div>
      ${!item && !income ? `<label class="check"><input type="checkbox" name="another" checked>Adicionar outra depois de salvar</label>` : ""}
      ${formActions(item ? "remove-recurring" : "")}
      ${!item && !income ? `<button type="button" class="link" data-act="skip" data-key="bills">Por ora, já cadastrei tudo</button>` : ""}
    </form>`);
}

function sheetCard(card) {
  openSheet(card ? "Editar cartão" : "Cartão", "As datas estão no app do banco ou na fatura.", `
    <form data-form="card" data-id="${card ? card.id : ""}">
      ${field("Nome", "name", card?.name, 'required maxlength="80" placeholder="Nubank"')}
      <div class="field-row">${dayField("Fecha no dia", "closing_day", card?.closing_day)}${dayField("Vence no dia", "due_day", card?.due_day)}</div>
      ${moneyField("Quanto a fatura atual já tem", "opening", null, "", "Entra como compromisso do mês em que ela vence. Compras parceladas antigas, conte depois pelo Telegram.")}
      ${formActions(card ? "remove-card" : "")}
      ${!card ? `<button type="button" class="link" data-act="skip" data-key="cards">Não uso cartão</button>` : ""}
    </form>`);
}

function sheetDebt(debt) {
  openSheet(debt ? "Editar dívida" : "Dívida", "Saldo aproximado já serve. Atualize quando souber o valor exato.", `
    <form data-form="debt" data-id="${debt ? debt.id : ""}">
      ${field("Nome", "name", debt?.name, 'required maxlength="80" placeholder="Empréstimo do banco"')}
      <div class="field-row">${moneyField("Quanto deve", "balance", debt?.balance_cents)}${field("Juros ao mês (%)", "rate", debt ? pct(debt.monthly_rate) : "", 'inputmode="decimal" placeholder="Ex.: 14"')}</div>
      <div class="field-row">${moneyField("Parcela ou mínimo", "minimum", debt?.min_payment_cents, "required")}${dayField("Vence no dia", "due_day", debt?.due_day)}</div>
      <label class="check"><input type="checkbox" name="overdue" ${debt?.overdue ? "checked" : ""}>Está em atraso</label>
      ${formActions(debt ? "remove-debt" : "")}
      ${!debt ? `<button type="button" class="link" data-act="skip" data-key="debts">Não tenho dívidas</button>` : ""}
    </form>`);
}

function sheetTx(t) {
  const inst = t.installment_total ? `Parcela ${t.installment_no} de ${t.installment_total}. Remover apaga a compra inteira.` : "";
  openSheet("Lançamento", inst, `
    <form data-form="tx" data-id="${t.id}">
      ${field("Descrição", "description", t.description, 'required maxlength="120"')}
      <div class="field-row">${moneyField("Valor", "amount", t.amount_cents)}${field("Data", "date", t.date, 'type="date" required')}</div>
      <label class="field"><span>Categoria</span><select name="category">
        ${S.category_list.filter((c) => !["renda", "dividas"].includes(c.key) || c.key === t.category).map((c) => `<option value="${esc(c.key)}" ${c.key === t.category ? "selected" : ""}>${esc(c.label)}</option>`).join("")}
      </select><em>Corrigir uma vez ensina: da próxima vez, já vem certo.</em></label>
      ${formActions("remove-tx")}
    </form>`);
}

function sheetBudget(category) {
  const current = S.categories.find((c) => c.category === category);
  openSheet("Limite por categoria", "Eu aviso ao chegar em 80% e ao passar de 100%.", `
    <form data-form="budget">
      <label class="field"><span>Categoria</span><select name="category">
        ${pickable().map((c) => `<option value="${esc(c.key)}" ${c.key === category ? "selected" : ""}>${esc(c.label)}</option>`).join("")}
      </select></label>
      ${moneyField("Limite por mês", "limit", current?.limit_cents, "", "Deixe vazio para remover.")}
      ${formActions("")}
    </form>`);
}

function sheetSettings() {
  const s = S.settings;
  const tg = !s.telegram ? "Falta o token no servidor." : s.paired ? "Conectado." : "Ainda não conectado.";
  openSheet("Ajustes", "", `
    <form data-form="settings">
      <label class="check"><input type="checkbox" name="nudges_on" ${s.nudges_off ? "" : "checked"}>Receber avisos no Telegram</label>
      <div class="field-row">
        ${field("Bom dia às", "morning_time", s.morning_time, 'type="time"')}
        ${field("Lembrete da noite", "evening_time", s.evening_time, 'type="time"')}
      </div>
      <button class="btn full" type="submit">Salvar</button>
    </form>
    <div class="list" style="margin-top:24px">
      <div class="item"><span class="main"><span class="name">Telegram</span><span class="sub">${tg}</span></span></div>
      <div class="item"><span class="main"><span class="name">Agente com IA</span><span class="sub">${s.ai ? "Ligado" : "Sem chave. Registro simples funciona igual."}</span></span></div>
      <a class="item" href="/api/export" style="text-decoration:none"><span class="main"><span class="name">Baixar meus dados</span><span class="sub">Tudo em um arquivo JSON</span></span></a>
      <button class="item" data-act="categories"><span class="main"><span class="name">Categorias</span><span class="sub">Criar, renomear ou remover</span></span></button>
      <button class="item" data-act="logout"><span class="main"><span class="name">Sair</span></span></button>
    </div>`);
}

// ---------- formulários ----------

const FORMS = {
  async login(data, form) {
    try {
      await api("/api/login", { json: { password: data.get("password") } });
      await refresh();
    } catch (e) {
      const box = document.getElementById("login-error");
      box.textContent = e.message;
      box.hidden = false;
      form.querySelector("[type=submit]").disabled = false;
    }
  },
  async quick(data, form) {
    const text = data.get("text").trim();
    if (!text) return;
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      lastResult = await api("/api/quick", { json: { text } });
      lastResult.text = text;
      await refresh();
    } catch (e) {
      lastResult = { type: "error", message: e.message };
      const box = document.getElementById("result");
      if (box) box.innerHTML = resultBlock();
      if (e.message === "auth") return;
      form.querySelector("input").value = text;
    } finally {
      const again = document.querySelector('[data-form="quick"] button');
      if (again) again.disabled = false;
    }
  },
  async recurring(data, form) {
    const id = form.dataset.id;
    const kind = form.dataset.kind;
    const body = { kind, name: data.get("name"), amount_cents: toCents(data.get("amount")), day: +data.get("day") };
    if (body.amount_cents === null) throw new Error("Valor inválido.");
    if (id) await api(`/api/recurring/${id}`, { method: "PUT", json: body });
    else await api("/api/recurring", { json: body });
    if (data.get("another")) {
      toast(`${body.name} salva.`);
      await refresh();
      sheetRecurring(kind);
      return;
    }
    closeSheet();
    await refresh();
  },
  async card(data, form) {
    const id = form.dataset.id;
    const body = { name: data.get("name"), closing_day: +data.get("closing_day"), due_day: +data.get("due_day"), opening_cents: toCents(data.get("opening")) };
    if (id) await api(`/api/cards/${id}`, { method: "PUT", json: body });
    else await api("/api/cards", { json: body });
    closeSheet();
    await refresh();
  },
  async debt(data, form) {
    const id = form.dataset.id;
    const rate = Number(String(data.get("rate") || "0").replace(",", "."));
    if (!Number.isFinite(rate)) throw new Error("Juros inválidos.");
    const body = {
      name: data.get("name"), balance_cents: toCents(data.get("balance")), monthly_rate: rate,
      min_payment_cents: toCents(data.get("minimum")), due_day: +data.get("due_day"), overdue: data.get("overdue") === "on",
    };
    if (body.balance_cents === null || body.min_payment_cents === null) throw new Error("Valor inválido.");
    if (id) await api(`/api/debts/${id}`, { method: "PUT", json: body });
    else await api("/api/debts", { json: body });
    closeSheet();
    await refresh();
  },
  async tx(data, form) {
    const body = { description: data.get("description"), amount_cents: toCents(data.get("amount")), date: data.get("date"), category: data.get("category") };
    if (!body.amount_cents) throw new Error("Valor inválido.");
    await api(`/api/transactions/${form.dataset.id}`, { method: "PUT", json: body });
    closeSheet();
    await refresh();
  },
  async budget(data) {
    await api("/api/budgets", { json: { category: data.get("category"), limit_cents: toCents(data.get("limit")) || 0 } });
    closeSheet();
    await refresh();
  },
  async goal(data, form) {
    const id = form.dataset.id;
    const body = { name: data.get("name"), target_cents: toCents(data.get("target")), due_month: data.get("due_month") || null, monthly_cents: toCents(data.get("monthly")) };
    if (!body.target_cents) throw new Error("Valor inválido.");
    if (id) await api(`/api/goals/${id}`, { method: "PUT", json: body });
    else await api("/api/goals", { json: body });
    closeSheet();
    await refresh();
  },
  async deposit(data, form) {
    const cents = toCents(data.get("amount"));
    if (!cents) throw new Error("Valor inválido.");
    const withdraw = data.get("withdraw") === "on";
    await api(`/api/goals/${form.dataset.id}/deposits`, { json: { amount_cents: withdraw ? -cents : cents } });
    closeSheet();
    toast(withdraw ? "Retirada registrada." : "Guardado.");
    await refresh();
  },
  async category(data, form) {
    const key = form.dataset.key;
    const body = { label: data.get("label"), icon: data.get("icon") };
    if (key) await api(`/api/categories/${key}`, { method: "PUT", json: body });
    else await api("/api/categories", { json: body });
    closeSheet();
    await refresh();
  },
  async settings(data) {
    await api("/api/settings", { json: { nudges_off: data.get("nudges_on") !== "on", morning_time: data.get("morning_time"), evening_time: data.get("evening_time") } });
    closeSheet();
    toast("Salvo.");
    await refresh();
  },
};

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("form[data-form]");
  if (!form) return;
  event.preventDefault();
  const submit = form.querySelector("[type=submit]");
  if (submit) submit.disabled = true;
  try {
    await FORMS[form.dataset.form](new FormData(form), form);
  } catch (e) {
    if (e.message === "auth") return;
    const box = form.querySelector(".form-error");
    if (box) { box.textContent = e.message; box.hidden = false; } else toast(e.message);
    if (submit) submit.disabled = false;
  }
});

// ---------- ações ----------

const byId = (list, id) => list.find((x) => x.id === +id);

const ACTIONS = {
  "list-income": () => sheetList("Renda", "new-income", "Adicionar renda", `<div class="list">${S.recurring.filter((r) => r.kind === "income").map(recurringItem).join("")}</div>`),
  "list-bills": () => sheetList("Contas fixas", "new-bill", "Adicionar conta", `<div class="list">${S.recurring.filter((r) => r.kind === "expense").map(recurringItem).join("")}</div>`),
  "list-cards": () => sheetList("Cartões", "new-card", "Adicionar cartão", S.cards.map(cardBlock).join("")),
  "list-debts": () => sheetDebts(),
  async "confirm-quick"() {
    lastResult = await api("/api/quick", { json: { text: lastResult.text, confirmed: true } });
    await refresh();
  },
  "cancel-quick": () => { lastResult = null; render(); },
  tab: (el) => { view = el.dataset.tab; lastResult = null; report = null; reportMonth = ""; render(); scrollTo(0, 0); },
  async "month-nav"(el) { reportMonth = el.dataset.month; report = await api(`/api/report?month=${reportMonth}`); render(); },
  budgets: () => sheetBudgets(),
  categories: () => sheetCategories(),
  "new-category": () => sheetCategory(),
  "edit-category": (el) => sheetCategory(catMeta(el.dataset.key)),
  "pick-icon": (el) => {
    sheet.querySelector('[name="icon"]').value = el.dataset.icon;
    sheet.querySelectorAll(".icon-pick").forEach((b) => b.setAttribute("aria-pressed", String(b === el)));
  },
  async "remove-category"() {
    const { moved } = await api(`/api/categories/${sheet.querySelector("form").dataset.key}`, { method: "DELETE" });
    closeSheet(); toast(moved ? `${moved} gastos passaram para Outros.` : "Categoria removida."); await refresh();
  },
  "new-goal": () => sheetGoal(),
  "new-reserve": () => sheetGoal(null, { name: "Reserva de emergência", target_cents: S.reserve_suggestion_cents || null }),
  "edit-goal": (el) => sheetGoal(byId(S.goals, el.dataset.id)),
  "goal-deposit": (el) => sheetDeposit(byId(S.goals, el.dataset.id)),
  async "remove-goal"() {
    await api(`/api/goals/${sheet.querySelector("form").dataset.id}`, { method: "DELETE" });
    closeSheet(); await refresh();
  },
  async "remove-deposit"(el) {
    await api(`/api/goal-deposits/${el.dataset.id}`, { method: "DELETE" });
    closeSheet(); toast("Removido."); await refresh();
  },
  settings: () => sheetSettings(),
  "close-sheet": closeSheet,
  retry: refresh,
  "new-income": () => sheetRecurring("income"),
  "new-bill": () => sheetRecurring("expense"),
  "new-card": () => sheetCard(),
  "new-debt": () => sheetDebt(),
  "new-budget": (el) => sheetBudget(el.dataset.category),
  "edit-recurring": (el) => { const r = byId(S.recurring, el.dataset.id); sheetRecurring(r.kind, r); },
  "edit-card": (el) => sheetCard(byId(S.cards, el.dataset.id)),
  "edit-debt": (el) => sheetDebt(byId(S.debts.debts, el.dataset.id)),
  "edit-tx": (el) => { const t = byId(txRows || [], el.dataset.id) || byId(S.recent, el.dataset.id); if (t) sheetTx(t); },
  async "edit-last"() {
    const rows = await api("/api/transactions?limit=50");
    const t = rows.find((x) => x.id === lastResult.id);
    if (t) sheetTx(t);
  },
  skip: async (el) => {
    try { localStorage.setItem(`skip-${el.dataset.key}`, "1"); } catch { /* sem armazenamento, o passo só continua visível */ }
    closeSheet();
    render();
  },
  async paid(el) {
    const { name } = await api("/api/paid", { json: { type: el.dataset.type, id: +el.dataset.id, month: el.dataset.month } });
    toast(`${name}: pago.`);
    await refresh();
  },
  async pause(el) {
    await api(`/api/pauses/${el.dataset.id}`, { json: { status: el.dataset.status } });
    await refresh();
  },
  async purchase(el) {
    const r = lastResult;
    const { message } = await api("/api/purchase", { json: { item: r.item, amount_cents: r.amount_cents, installments: r.installments, choice: el.dataset.choice } });
    lastResult = null;
    toast(message);
    await refresh();
  },
  async "undo-last"() {
    await api(`/api/transactions/${lastResult.id}`, { method: "DELETE" });
    lastResult = null;
    toast("Desfeito.");
    await refresh();
  },
  async "assign-card"(el) {
    const rows = await api("/api/transactions?limit=50");
    const t = rows.find((x) => x.id === lastResult.id);
    if (t) await api("/api/assign-card", { json: { transaction_id: t.id, card_id: +el.dataset.card } });
    lastResult.needs_card = false;
    await refresh();
  },
  async "remove-recurring"() {
    await api(`/api/recurring/${sheet.querySelector("form").dataset.id}`, { method: "DELETE" });
    closeSheet(); await refresh();
  },
  async "remove-card"() {
    await api(`/api/cards/${sheet.querySelector("form").dataset.id}`, { method: "DELETE" });
    closeSheet(); await refresh();
  },
  async "remove-debt"() {
    await api(`/api/debts/${sheet.querySelector("form").dataset.id}`, { method: "DELETE" });
    closeSheet(); await refresh();
  },
  async "remove-tx"() {
    await api(`/api/transactions/${sheet.querySelector("form").dataset.id}`, { method: "DELETE" });
    closeSheet(); toast("Removido."); await refresh();
  },
  async strategy(el) {
    await api("/api/debts-plan", { json: { strategy: el.dataset.value } });
    debtPreview = null;
    await refresh();
    sheetDebts();
  },
  import: () => document.getElementById("file").click(),
  async "undo-import"(el) {
    const { removed } = await api(`/api/import/${el.dataset.batch}/undo`, { method: "POST" });
    closeSheet(); toast(`${removed} lançamentos removidos.`); await refresh();
  },
  async "import-card"(el) {
    closeSheet();
    await sendFile(pendingFile, +el.dataset.card);
  },
  async install() {
    if (!installEvent) return;
    installEvent.prompt();
    await installEvent.userChoice;
    installEvent = null;
    render();
  },
  async logout() {
    await api("/api/logout", { method: "POST" });
    closeSheet();
    renderLogin();
  },
};

document.addEventListener("click", async (event) => {
  const el = event.target.closest("[data-act]");
  if (!el) return;
  const action = ACTIONS[el.dataset.act];
  if (!action) return;
  try {
    await action(el);
  } catch (e) {
    if (e.message !== "auth") toast(e.message);
  }
});

sheet.addEventListener("click", (event) => { if (event.target === sheet) closeSheet(); });

// ---------- importar ----------

let pendingFile = null;

async function sendFile(file, cardId) {
  const body = new FormData();
  body.append("file", file);
  if (cardId) body.append("card_id", cardId);
  toast("Lendo o arquivo…");
  try {
    const r = await api("/api/import", { method: "POST", body });
    if (r.needs_card) {
      pendingFile = file;
      openSheet("De qual cartão?", `Encontrei ${r.count} lançamentos de fatura.`, r.cards.map((c) =>
        `<button class="btn quiet full" style="margin-bottom:8px" data-act="import-card" data-card="${c.id}">${esc(c.name)}</button>`).join(""));
      return;
    }
    toastEl.hidden = true;
    const rows = [
      `<div class="line big"><span>Novos</span><b>${r.added}</b></div>`,
      r.total_cents ? `<div class="line"><span>Total de gastos novos</span><span>${brl(r.total_cents)}</span></div>` : "",
      r.matched ? `<div class="line"><span>Você já tinha registrado</span><span>${r.matched}</span></div>` : "",
      r.already ? `<div class="line"><span>Já importados antes</span><span>${r.already}</span></div>` : "",
      r.ignored ? `<div class="line"><span>Ignorados (faturas, aplicações)</span><span>${r.ignored}</span></div>` : "",
      r.uncategorized ? `<div class="line"><span>Sem categoria</span><span>${r.uncategorized}</span></div>` : "",
    ].join("");
    openSheet("Importado", "Nada foi duplicado.", `<div class="ledger">${rows}</div>
      <div class="sheet-actions" style="margin-top:20px">
        ${r.added ? `<button class="btn quiet" data-act="undo-import" data-batch="${esc(r.batch_id)}">Desfazer</button>` : ""}
        <button class="btn" data-act="close-sheet">Pronto</button>
      </div>`);
    await refresh();
  } catch (e) {
    if (e.message !== "auth") toast(e.message);
  }
}

document.addEventListener("change", (event) => {
  if (event.target.id === "file" && event.target.files[0]) {
    sendFile(event.target.files[0]);
  } else if (event.target.id === "month-filter") {
    txMonth = event.target.value;
    loadTx();
  } else if (event.target.id === "extra") {
    const extra = +event.target.value;
    api("/api/debts-plan", { json: { extra_cents: extra } }).then(refresh).catch((e) => { if (e.message !== "auth") toast(e.message); });
  }
});

let inputTimer = null;
document.addEventListener("input", (event) => {
  if (event.target.id === "search") {
    txQuery = event.target.value;
    clearTimeout(inputTimer);
    inputTimer = setTimeout(loadTx, 200);
  } else if (event.target.id === "extra") {
    const extra = +event.target.value;
    clearTimeout(inputTimer);
    inputTimer = setTimeout(async () => {
      try {
        const plan = await api(`/api/debts-simulate?extra_cents=${extra}&strategy=${S.debts.strategy}`);
        debtPreview = plan;
        const box = document.getElementById("freedom");
        if (!box) return;
        const range = box.querySelector("#extra");
        let node = box.firstChild;
        while (node && node !== range) { const next = node.nextSibling; node.remove(); node = next; }
        range.insertAdjacentHTML("beforebegin", freedomBlock(plan, plan.free_month, extra));
        drawChart(document.getElementById("debt-chart"));
      } catch (e) {
        if (e.message !== "auth") toast(e.message);
      }
    }, 120);
  }
});

// ---------- ciclo de vida ----------

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installEvent = event;
  if (S) render();
});

document.addEventListener("visibilitychange", () => {
  // Abrir o app no dia seguinte precisa mostrar o número de hoje.
  if (document.visibilityState === "visible" && S && !sheet.open) refresh();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

refresh();
