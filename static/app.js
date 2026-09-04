"use strict";

const byId = (id) => document.getElementById(id);
const number = new Intl.NumberFormat("zh-CN");
const passwordKey = "ourdays-access-password";
let summary;

const notePositions = [
  [4, 4, -2], [53, 5, 1.5], [18, 22, 1], [63, 27, -1.5],
  [1, 48, 2], [51, 51, -1], [16, 70, -1.5], [61, 75, 2]
];

function shortDate(value) {
  const [year, month, day] = value.slice(0, 10).split("-");
  return `${year}年${Number(month)}月${Number(day)}日`;
}

async function getJSON(url, options) {
  const headers = new Headers(options?.headers);
  const password = sessionStorage.getItem(passwordKey);
  if (password) headers.set("X-Ourdays-Password", password);
  const response = await fetch(url, {...options, headers});
  if (response.status === 401) {
    sessionStorage.removeItem(passwordKey);
    showAccessDialog();
    const error = new Error("访问密码不正确");
    error.status = 401;
    throw error;
  }
  if (!response.ok) throw new Error((await response.text()) || "请求没有成功");
  return response.json();
}

function setText(id, value) {
  byId(id).textContent = value;
}

function shuffled(items) {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function renderShowcase(messages) {
  const field = byId("message-field");
  const fragment = document.createDocumentFragment();
  shuffled(messages).slice(0, notePositions.length).forEach((message, index) => {
    const note = document.createElement("article");
    const text = document.createElement("p");
    const meta = document.createElement("small");
    const [x, y, rotation] = notePositions[index];
    note.className = `memory-note ${message.sender === "partner" ? "partner" : "self"}`;
    note.style.setProperty("--x", `${x}%`);
    note.style.setProperty("--y", `${y}%`);
    note.style.setProperty("--rotate", `${rotation}deg`);
    note.style.setProperty("--delay", `${-index * .73}s`);
    text.textContent = message.text;
    meta.textContent = `${message.sender_name} · ${message.time.slice(5, 16).replace("T", " ")}`;
    note.append(text, meta);
    fragment.append(note);
  });
  field.replaceChildren(fragment);
}

function setSplitBar(prefix, selfValue, partnerValue) {
  const total = selfValue + partnerValue;
  const selfShare = total ? selfValue / total * 100 : 50;
  byId(`${prefix}-self-bar`).style.width = `${selfShare}%`;
  byId(`${prefix}-partner-bar`).style.width = `${100 - selfShare}%`;
  setText(`${prefix === "message" ? "message" : "character"}-ratio`, `${selfShare.toFixed(0)}% · ${(100 - selfShare).toFixed(0)}%`);
}

function renderOverview(data) {
  const self = data.by_sender.self;
  const partner = data.by_sender.partner;
  setText("total-messages", number.format(data.total_messages));
  setText("active-days", `${data.active_days}/${data.calendar_days}`);
  setText("longest-streak", number.format(data.longest_streak));
  setText("peak-total", number.format(data.peak_day.total));
  setText("peak-caption", `${shortDate(data.peak_day.date)} 最热闹`);
  setText("self-messages", number.format(self.messages));
  setText("partner-messages", number.format(partner.messages));
  setText("self-characters", number.format(self.characters));
  setText("partner-characters", number.format(partner.characters));
  setSplitBar("message", self.messages, partner.messages);
  setSplitBar("character", self.characters, partner.characters);

  const chattyName = self.messages === partner.messages ? "你们" : self.messages > partner.messages ? data.names.self : data.names.partner;
  const wordyName = self.characters === partner.characters ? "你们" : self.characters > partner.characters ? data.names.self : data.names.partner;
  setText("couple-insight", self.messages === partner.messages && self.characters === partner.characters
    ? "连消息和字数都刚好心有灵犀。"
    : `${chattyName} 发得更多，${wordyName} 写得更多，每一条都有回应。`);
}

function linePath(days, role, width, height, padding, maximum) {
  return days.map((day, index) => {
    const x = padding + index / Math.max(days.length - 1, 1) * (width - padding * 1.5);
    const y = padding + (1 - day[role] / maximum) * (height - padding * 2);
    return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function renderTrend(days, names) {
  const width = 760;
  const height = 280;
  const padding = 42;
  const maximum = Math.max(1, ...days.flatMap((day) => [day.self, day.partner]));
  ["self", "partner"].forEach((role) => {
    const path = linePath(days, role, width, height, padding, maximum);
    byId(`${role}-line`).setAttribute("d", path);
    const lastX = width - padding / 2;
    byId(`${role}-area`).setAttribute("d", `${path} L${lastX},${height - padding} L${padding},${height - padding} Z`);
  });
  setText("trend-max", number.format(maximum));
  setText("trend-start", days[0].date.slice(5));
  setText("trend-end", days.at(-1).date.slice(5));
  setText("trend-description", `${shortDate(days[0].date)}至${shortDate(days.at(-1).date)}的每日聊天数量趋势，浅金色代表${names.self}，粉色代表${names.partner}。`);
}

function renderPeriods(periods, names) {
  const container = byId("period-chart");
  const order = ["凌晨", "清晨", "白天", "夜晚"];
  const maximum = Math.max(1, ...order.flatMap((period) => [periods.self[period], periods.partner[period]]));
  const fragment = document.createDocumentFragment();
  order.forEach((period) => {
    const row = document.createElement("div");
    const label = document.createElement("span");
    const bars = document.createElement("div");
    row.className = "period-row";
    bars.className = "period-bars";
    label.textContent = period;
    ["self", "partner"].forEach((role) => {
      const bar = document.createElement("div");
      const fill = document.createElement("i");
      const value = document.createElement("small");
      bar.className = `period-bar ${role}`;
      fill.style.width = `${periods[role][period] / maximum * 100}%`;
      value.textContent = number.format(periods[role][period]);
      bar.setAttribute("aria-label", `${names[role]}在${period}发送${periods[role][period]}条消息`);
      bar.append(fill, value);
      bars.append(bar);
    });
    row.append(label, bars);
    fragment.append(row);
  });
  container.replaceChildren(fragment);

  const combined = order.map((period) => [period, periods.self[period] + periods.partner[period]]);
  combined.sort((a, b) => b[1] - a[1]);
  setText("period-note", `你们最常在${combined[0][0]}碰面，一共留下 ${number.format(combined[0][1])} 条消息。`);
}

function renderLoveWords(loveWords) {
  const fragment = document.createDocumentFragment();
  Object.keys(loveWords.occurrences.self).forEach((word) => {
    const selfCount = loveWords.occurrences.self[word];
    const partnerCount = loveWords.occurrences.partner[word];
    const maximum = Math.max(1, selfCount, partnerCount);
    const row = document.createElement("div");
    const selfSide = document.createElement("div");
    const partnerSide = document.createElement("div");
    const label = document.createElement("strong");
    row.className = "love-row";
    selfSide.className = partnerSide.className = "love-side";
    label.textContent = word;
    [selfSide, partnerSide].forEach((side, index) => {
      const count = index ? partnerCount : selfCount;
      const value = document.createElement("span");
      const bar = document.createElement("div");
      const fill = document.createElement("i");
      value.textContent = `${number.format(count)} 次`;
      bar.className = "love-bar";
      fill.style.width = `${count / maximum * 100}%`;
      bar.append(fill);
      side.append(value, bar);
    });
    row.append(selfSide, label, partnerSide);
    fragment.append(row);
  });
  byId("love-list").replaceChildren(fragment);
}

function renderSummary(data) {
  summary = data;
  const names = data.names;
  setText("date-range", `${shortDate(data.range.start)} — ${shortDate(data.range.end)}`);
  setText("pair-names", `${names.self} × ${names.partner}`);
  setText("archive-status", `${number.format(data.total_messages)} 条回忆已点亮`);
  ["self-name", "self-legend", "love-self-name", "search-self-name"].forEach((id) => setText(id, names.self));
  ["partner-name", "partner-legend", "love-partner-name", "search-partner-name"].forEach((id) => setText(id, names.partner));
  setText("self-avatar", names.self.trim().slice(0, 1) || "我");
  setText("partner-avatar", names.partner.trim().slice(0, 1) || "你");
  renderShowcase(data.showcase);
  renderOverview(data);
  renderTrend(data.daily, names);
  renderPeriods(data.periods, names);
  renderLoveWords(data.love_words);
  byId("open-love").disabled = false;
  requestAnimationFrame(() => document.body.classList.add("loaded"));
}

async function loadSummary() {
  try {
    renderSummary(await getJSON("/api/summary"));
  } catch (error) {
    if (error.status === 401) return;
    setText("archive-status", "回忆暂时没有打开");
    const message = document.createElement("p");
    message.className = "message-placeholder";
    message.textContent = "晚霞还在，回忆稍后再见。";
    byId("message-field").replaceChildren(message);
    console.error(error);
  }
}

function searchNote(word, selfCount, partnerCount) {
  if (selfCount + partnerCount === 0) return `“${word}”还没有在这段回忆里出现。换个小暗号试试吧。`;
  if (selfCount === partnerCount) return `刚刚好！你们都说了 ${number.format(selfCount)} 次，默契悄悄满格。`;
  const winner = selfCount > partnerCount ? summary.names.self : summary.names.partner;
  return `${winner} 多说了 ${number.format(Math.abs(selfCount - partnerCount))} 次，原来是更爱把这句话挂在嘴边的人。`;
}

async function runSearch(word) {
  const button = byId("search-button");
  const status = byId("search-status");
  button.disabled = true;
  button.textContent = "正在寻找…";
  status.textContent = "正在数一数这个词出现过多少次…";
  try {
    const result = await getJSON(`/api/search?q=${encodeURIComponent(word)}`);
    setText("searched-word", result.query);
    setText("search-self-count", number.format(result.occurrences.self));
    setText("search-partner-count", number.format(result.occurrences.partner));
    setText("search-self-messages", number.format(result.messages.self));
    setText("search-partner-messages", number.format(result.messages.partner));
    setText("search-note", searchNote(result.query, result.occurrences.self, result.occurrences.partner));
    byId("search-result").hidden = false;
    status.textContent = `找到了「${result.query}」的统计结果。`;
  } catch (error) {
    status.textContent = error.status === 401 ? "先输入访问密码，再继续寻找吧。" : "这次没有找到，稍后再试一次吧。";
    console.error(error);
  } finally {
    button.disabled = false;
    button.textContent = "开始寻找";
  }
}

function bindSearch() {
  const form = byId("search-form");
  const input = byId("search-input");
  input.addEventListener("input", () => input.setCustomValidity(""));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const word = input.value.trim();
    if (!word) {
      input.setCustomValidity("写一个想寻找的词吧");
      input.reportValidity();
      return;
    }
    runSearch(word);
  });
  document.querySelectorAll("[data-word]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.word;
      form.requestSubmit();
    });
  });
}

function bindDialog() {
  const dialog = byId("love-dialog");
  byId("open-love").addEventListener("click", () => dialog.showModal());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

function showAccessDialog() {
  const dialog = byId("access-dialog");
  setText("archive-status", "等待访问密码");
  if (dialog.open) return;
  dialog.showModal();
  requestAnimationFrame(() => byId("access-password").focus());
}

function bindAccess() {
  const dialog = byId("access-dialog");
  const form = byId("access-form");
  const input = byId("access-password");
  const button = byId("access-button");
  const status = byId("access-status");
  dialog.addEventListener("cancel", (event) => event.preventDefault());
  input.addEventListener("input", () => { status.textContent = ""; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    button.textContent = "正在确认暗号…";
    status.textContent = "正在打开属于你们的晚霞…";
    sessionStorage.setItem(passwordKey, input.value);
    try {
      renderSummary(await getJSON("/api/summary"));
      dialog.close();
      input.value = "";
    } catch (error) {
      status.textContent = error.status === 401 ? "这个暗号不太对，再想一想吧 ♡" : "暂时没能打开，请稍后再试。";
      if (error.status === 401) input.select();
      console.error(error);
    } finally {
      button.disabled = false;
      button.textContent = "走进我们的回忆";
    }
  });
}

function bindAI() {
  const form = byId("ai-form");
  const question = byId("ai-question");
  const button = byId("ask-button");
  const label = byId("ask-label");
  const thinking = byId("ai-thinking");
  const thinkingStatus = byId("thinking-status");
  const answer = byId("ai-answer");
  const status = byId("ai-status");
  const stages = ["正在翻开聊天回忆…", "正在寻找你们的小暗号…", "正在读懂那些心动瞬间…", "正在把答案写成一封小信…"];
  question.addEventListener("input", () => {
    question.setCustomValidity("");
    setText("question-count", question.value.length);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = question.value.trim();
    if (!prompt) {
      question.setCustomValidity("写下一个想问回忆的问题吧");
      question.reportValidity();
      return;
    }
    button.disabled = true;
    label.textContent = "回忆正在回答";
    question.setAttribute("aria-busy", "true");
    answer.hidden = true;
    thinking.hidden = false;
    status.textContent = "AI 正在依据真实聊天记录寻找答案。";
    let stage = 0;
    const timer = window.setInterval(() => {
      stage = (stage + 1) % stages.length;
      thinkingStatus.textContent = stages[stage];
    }, 1800);
    try {
      const result = await getJSON("/api/ask", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question: prompt})
      });
      setText("answer-text", result.answer);
      setText("answer-model", `由 ${result.model} 阅读真实记录后生成`);
      answer.hidden = false;
      status.textContent = "答案写好了，并附上了聊天原话。";
      answer.focus({preventScroll: true});
      answer.scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest"});
    } catch (error) {
      status.textContent = error.status === 401 ? "先输入访问密码，再来问问回忆吧。" : "回忆回答到一半走神了，请稍后再问一次。";
      console.error(error);
    } finally {
      window.clearInterval(timer);
      thinkingStatus.textContent = stages[0];
      thinking.hidden = true;
      question.removeAttribute("aria-busy");
      button.disabled = false;
      label.textContent = "交给回忆回答";
    }
  });
}

function revealOnScroll() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      }
    });
  }, {threshold: .12});
  document.querySelectorAll(".reveal").forEach((element) => observer.observe(element));
}

bindDialog();
bindAccess();
bindSearch();
bindAI();
revealOnScroll();
loadSummary();
