const state = {
  tab: "picks",
  search: "",
  minScore: 60,
  onlyTwinBuy: false,
  report: null,
  isAnalyzing: false,
  cooldownUntil: 0,
  cooldownTimer: null,
};

const els = {
  tabs: document.querySelectorAll(".tab"),
  panels: document.querySelectorAll(".panel"),
  pickCards: document.querySelector("#pickCards"),
  flowRows: document.querySelector("#flowRows"),
  valuationRows: document.querySelector("#valuationRows"),
  themeCards: document.querySelector("#themeCards"),
  newsList: document.querySelector("#newsList"),
  searchInput: document.querySelector("#searchInput"),
  scoreRange: document.querySelector("#scoreRange"),
  scoreValue: document.querySelector("#scoreValue"),
  onlyTwinBuy: document.querySelector("#onlyTwinBuy"),
  watchCount: document.querySelector("#watchCount"),
  marketNote: document.querySelector(".market-note p"),
  generatedAt: document.querySelector(".eyebrow"),
  analyzeButton: document.querySelector("#analyzeButton"),
  analyzeStatus: document.querySelector("#analyzeStatus"),
};

function normalizeStock(stock) {
  return {
    ...stock,
    score: Number(stock.score ?? 0),
    foreign: Number(stock.foreign ?? 0),
    foreign_streak: Number(stock.foreign_streak ?? 0),
    ownership: Number(stock.ownership ?? 0),
    institution: Number(stock.institution ?? 0),
    institution_streak: Number(stock.institution_streak ?? 0),
    position_52: Number(stock.position_52 ?? 0),
    drawdown: Number(stock.drawdown ?? 0),
    current_price: stock.current_price == null ? null : Number(stock.current_price),
    change_percent: stock.change_percent == null ? null : Number(stock.change_percent),
    ma20: stock.ma20 == null ? null : Number(stock.ma20),
    ma60: stock.ma60 == null ? null : Number(stock.ma60),
    rsi14: stock.rsi14 == null ? null : Number(stock.rsi14),
    flow_data_available: Boolean(stock.flow_data_available),
    signal: stock.signal || "-",
    impact_news: stock.impact_news || null,
  };
}

async function loadReport() {
  let response = await fetch("./api/report", { cache: "no-store" }).catch(() => null);
  if (!response || !response.ok) {
    response = await fetch("./data/report.json", { cache: "no-store" });
  }
  if (!response.ok) {
    throw new Error(`report.json load failed: ${response.status}`);
  }
  const report = await response.json();
  return {
    ...report,
    stocks: (report.stocks || []).map(normalizeStock),
    themes: report.themes || [],
    news: report.news || [],
  };
}

function setAnalyzeState(isLoading, message) {
  state.isAnalyzing = isLoading;
  updateAnalyzeButton();
  els.analyzeStatus.textContent = message;
}

function remainingCooldownSeconds() {
  return Math.max(0, Math.ceil((state.cooldownUntil - Date.now()) / 1000));
}

function startCooldown(seconds = 30) {
  state.cooldownUntil = Date.now() + seconds * 1000;
  if (state.cooldownTimer) clearInterval(state.cooldownTimer);
  state.cooldownTimer = setInterval(updateAnalyzeButton, 250);
  updateAnalyzeButton();
}

function updateAnalyzeButton() {
  const remaining = remainingCooldownSeconds();
  if (state.isAnalyzing) {
    els.analyzeButton.disabled = true;
    els.analyzeButton.textContent = "분석 중...";
    return;
  }
  if (remaining > 0) {
    els.analyzeButton.disabled = true;
    els.analyzeButton.textContent = `${remaining}초 후 가능`;
    return;
  }
  if (state.cooldownTimer) {
    clearInterval(state.cooldownTimer);
    state.cooldownTimer = null;
  }
  els.analyzeButton.disabled = false;
  els.analyzeButton.textContent = "AI 분석 실행";
}

async function runAnalysis() {
  if (state.isAnalyzing || remainingCooldownSeconds() > 0) return;
  setAnalyzeState(true, "뉴스와 가격 데이터를 수집하고 AI 분석을 요청하는 중");
  startCooldown(30);
  try {
    const response = await fetch("./api/analyze", { method: "POST" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      if (response.status === 429 && payload.retry_after) {
        startCooldown(Number(payload.retry_after));
      }
      throw new Error(payload.message || "AI 분석 실패");
    }
    state.report = {
      ...payload.report,
      stocks: (payload.report.stocks || []).map(normalizeStock),
      themes: payload.report.themes || [],
      news: payload.report.news || [],
    };
    render();
    setAnalyzeState(false, payload.message || "새 분석 결과 표시 중");
  } catch (error) {
    console.warn(error);
    setAnalyzeState(false, `분석 실패: ${error.message}`);
  }
}

function matchesStock(stock) {
  const keyword = state.search.trim().toLowerCase();
  const haystack = `${stock.name} ${stock.code} ${stock.theme} ${stock.signal}`.toLowerCase();
  const hasKeyword = !keyword || haystack.includes(keyword);
  const hasScore = stock.score >= state.minScore;
  const hasSignal = !state.onlyTwinBuy || stock.signal === "쌍끌이매수";
  return hasKeyword && hasScore && hasSignal;
}

function filteredStocks() {
  return (state.report?.stocks || []).filter(matchesStock).sort((a, b) => b.score - a.score);
}

function confidenceClass(value) {
  if (value === "상") return "high";
  if (value === "중") return "mid";
  return "low";
}

function signedClass(value) {
  return value > 0 ? "num-pos" : value < 0 ? "num-neg" : "";
}

function formatSigned(value) {
  return value.toLocaleString("ko-KR");
}

function formatNumber(value, suffix = "") {
  return value == null || Number.isNaN(value) ? "-" : `${value.toLocaleString("ko-KR")}${suffix}`;
}

function formatPrice(value) {
  return value == null || Number.isNaN(value) ? "-" : `${Math.round(value).toLocaleString("ko-KR")}원`;
}

function formatDate(value) {
  if (!value) return "분석 대기 중";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toLocaleString("ko-KR")} 생성`;
}

function parsePer(value) {
  if (!value || value === "-") return null;
  const parsed = Number(String(value).replace(/[^0-9.-]/g, ""));
  return Number.isNaN(parsed) ? null : parsed;
}

function metricState(type, stock) {
  if (type === "per") {
    const per = parsePer(stock.per);
    if (per == null) return { level: "neutral", icon: "-", text: "PER 없음" };
    if (per <= 0) return { level: "bad", icon: "!", text: "적자/비정상" };
    if (per <= 15) return { level: "good", icon: "+", text: "낮음" };
    if (per <= 30) return { level: "neutral", icon: "=", text: "보통" };
    return { level: "warn", icon: "!", text: "높음" };
  }
  if (type === "rsi") {
    const rsi = stock.rsi14;
    if (rsi == null) return { level: "neutral", icon: "-", text: "RSI 없음" };
    if (rsi >= 80) return { level: "bad", icon: "!", text: "과열" };
    if (rsi >= 70) return { level: "warn", icon: "!", text: "주의" };
    if (rsi >= 40) return { level: "good", icon: "+", text: "안정" };
    if (rsi >= 30) return { level: "neutral", icon: "=", text: "약세" };
    return { level: "warn", icon: "!", text: "침체" };
  }
  if (type === "ma20" || type === "ma60") {
    const ma = stock[type];
    const price = stock.current_price;
    if (ma == null || price == null) return { level: "neutral", icon: "-", text: "이평 없음" };
    const distance = ((price - ma) / ma) * 100;
    if (distance >= 0) return { level: "good", icon: "+", text: `위 ${distance.toFixed(1)}%` };
    if (distance >= -3) return { level: "warn", icon: "!", text: `근접 ${distance.toFixed(1)}%` };
    return { level: "bad", icon: "!", text: `아래 ${distance.toFixed(1)}%` };
  }
  if (type === "position52") {
    const position = stock.position_52;
    if (position == null || Number.isNaN(position)) return { level: "neutral", icon: "-", text: "없음" };
    if (position >= 85) return { level: "warn", icon: "!", text: "고점권" };
    if (position >= 35) return { level: "good", icon: "+", text: "추세권" };
    return { level: "neutral", icon: "=", text: "저점권" };
  }
  return { level: "neutral", icon: "-", text: "-" };
}

function renderMetricBadge(label, value, state) {
  return `
    <span class="metric-badge ${state.level}">
      <b>${state.icon}</b>
      <span>${label}</span>
      <strong>${value}</strong>
      <em>${state.text}</em>
    </span>
  `;
}

function renderStockMetrics(stock) {
  return `
    <div class="metric-row">
      ${renderMetricBadge("PER", stock.per || "-", metricState("per", stock))}
      ${renderMetricBadge("RSI", formatNumber(stock.rsi14), metricState("rsi", stock))}
      ${renderMetricBadge("20일선", formatPrice(stock.ma20), metricState("ma20", stock))}
      ${renderMetricBadge("60일선", formatPrice(stock.ma60), metricState("ma60", stock))}
      ${renderMetricBadge("52주", `${stock.position_52.toFixed(1)}%`, metricState("position52", stock))}
    </div>
  `;
}

function formatNewsDate(item) {
  if (item.date && item.time) return `${item.date} ${item.time}`;
  if (item.date) return item.date;
  if (item.published_at) {
    const date = new Date(item.published_at);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
    }
    return item.published_at;
  }
  return item.time || "-";
}

function findImpactNews(stock) {
  if (stock.impact_news?.title) return stock.impact_news;
  const news = state.report?.news || [];
  const direct = news.find((item) => item.tag === stock.name || item.title?.includes(stock.name));
  if (direct) return { ...direct, reason: "종목명과 직접 매칭된 기사" };
  const theme = news.find((item) => stock.theme && item.title?.includes(stock.theme));
  return theme ? { ...theme, reason: "테마와 매칭된 기사" } : null;
}

function renderImpactNews(stock) {
  const item = findImpactNews(stock);
  if (!item?.title) return "";
  const title = item.url
    ? `<a href="${item.url}" target="_blank" rel="noreferrer">${item.title}</a>`
    : `<strong>${item.title}</strong>`;
  return `
    <div class="impact-news">
      <span>영향 뉴스</span>
      ${title}
      <small>${formatNewsDate(item)} · ${item.source || "출처 미상"}${item.reason ? ` · ${item.reason}` : ""}</small>
    </div>
  `;
}

function renderPicks(items) {
  els.pickCards.innerHTML = items.length
    ? items
        .map(
          (stock) => `
            <article class="stock-card">
              <div class="stock-head">
                <div class="stock-name">
                  <h3>${stock.name}</h3>
                  <span>${stock.code}</span>
                </div>
                <span class="badge ${confidenceClass(stock.conviction)}">확신도 ${stock.conviction}</span>
              </div>
              <div class="score-line" aria-label="기대점수 ${stock.score}">
                <span style="width:${stock.score}%"></span>
              </div>
              ${renderStockMetrics(stock)}
              <p>${stock.note}</p>
              <span class="risk">${stock.risk}</span>
              ${renderImpactNews(stock)}
              <div class="meta-row">
                <span class="chip">기대점수 ${stock.score}</span>
                <span class="chip">${stock.theme}</span>
                <span class="chip">${stock.signal}</span>
              </div>
            </article>
          `
        )
        .join("")
    : `<p class="empty">아직 표시할 종목이 없습니다. AI 분석 실행 후 결과가 여기에 표시됩니다.</p>`;
}

function renderFlow(items) {
  els.flowRows.innerHTML = items.length
    ? items
        .map(
          (stock) => `
        <tr>
          <td>${stock.name}</td>
          <td class="${signedClass(stock.foreign)}">${stock.flow_data_available ? formatSigned(stock.foreign) : "-"}</td>
          <td class="${signedClass(stock.foreign_streak)}">${stock.flow_data_available ? `${stock.foreign_streak}일` : "-"}</td>
          <td>${stock.flow_data_available ? `${stock.ownership.toFixed(2)}%` : "-"}</td>
          <td class="${signedClass(stock.institution)}">${stock.flow_data_available ? formatSigned(stock.institution) : "-"}</td>
          <td class="${signedClass(stock.institution_streak)}">${stock.flow_data_available ? `${stock.institution_streak}일` : "-"}</td>
          <td class="${stock.signal === "쌍끌이매수" ? "num-pos" : stock.signal === "쌍끌이매도" ? "num-neg" : ""}">${stock.signal}</td>
        </tr>
      `
        )
        .join("")
    : `<tr><td colspan="7" class="empty-cell">AI 분석 실행 후 수급 결과가 표시됩니다.</td></tr>`;
}

function renderValuation(items) {
  els.valuationRows.innerHTML = items.length
    ? items
        .slice()
        .sort((a, b) => b.position_52 - a.position_52)
        .map((stock) => {
          const hot = stock.position_52 >= 80 ? "hot" : "";
          return `
        <tr>
          <td>${stock.name}${stock.position_52 >= 80 ? " · 고점권" : ""}</td>
          <td>
            <div class="meter">
              <span class="meter-track"><span class="meter-fill ${hot}" style="width:${stock.position_52}%"></span></span>
              <b>${stock.position_52.toFixed(1)}%</b>
            </div>
          </td>
          <td>${renderMetricBadge("RSI", formatNumber(stock.rsi14), metricState("rsi", stock))}</td>
          <td>${renderMetricBadge("20일선", formatPrice(stock.ma20), metricState("ma20", stock))}</td>
          <td>${renderMetricBadge("60일선", formatPrice(stock.ma60), metricState("ma60", stock))}</td>
          <td class="num-neg">${stock.drawdown.toFixed(1)}%</td>
          <td>${stock.market_cap}</td>
          <td>${renderMetricBadge("PER", stock.per || "-", metricState("per", stock))}</td>
        </tr>
      `;
        })
        .join("")
    : `<tr><td colspan="8" class="empty-cell">AI 분석 실행 후 가격 위치가 표시됩니다.</td></tr>`;
}

function renderThemes() {
  els.themeCards.innerHTML = state.report.themes.length
    ? state.report.themes
        .map(
          (theme) => `
            <article class="theme-card">
              <header>
                <h3>${theme.rank}. ${theme.name}</h3>
                <span class="chip">${theme.status} · ${Number(theme.score).toFixed(4)}</span>
              </header>
              <p>${theme.reason}</p>
              <div class="meta-row">
                ${(theme.names || []).map((name) => `<span class="chip">${name}</span>`).join("")}
              </div>
            </article>
          `
        )
        .join("")
    : `<p class="empty">AI 분석 실행 후 테마 순위와 근거가 표시됩니다.</p>`;
}

function renderNews() {
  const keyword = state.search.trim().toLowerCase();
  const items = state.report.news.filter(
    (item) => !keyword || `${item.tag} ${item.title} ${item.source}`.toLowerCase().includes(keyword)
  );
  els.newsList.innerHTML = items.length
    ? items
        .map((item) => {
          const title = item.url ? `<a class="news-title" href="${item.url}" target="_blank" rel="noreferrer">${item.title}</a>` : `<strong class="news-title">${item.title}</strong>`;
          return `
            <article class="news-item">
              <span class="news-time">${formatNewsDate(item)}</span>
              <span class="chip">${item.tag}</span>
              ${title}
              <span class="news-source">${item.source}</span>
            </article>
          `;
        })
        .join("")
    : `<p class="empty">AI 분석 실행 후 수집 뉴스가 표시됩니다.</p>`;
}

function render() {
  if (!state.report) return;
  const items = filteredStocks();
  els.watchCount.textContent = items.length.toString();
  els.scoreValue.textContent = state.minScore.toString();
  els.marketNote.textContent = state.report.market_summary;
  els.generatedAt.textContent = formatDate(state.report.generated_at);
  renderPicks(items);
  renderFlow(items);
  renderValuation(items);
  renderThemes();
  renderNews();
}

els.tabs.forEach((button) => {
  button.addEventListener("click", () => {
    state.tab = button.dataset.tab;
    els.tabs.forEach((tab) => tab.classList.toggle("is-active", tab === button));
    els.panels.forEach((panel) => panel.classList.toggle("is-active", panel.id === state.tab));
  });
});

els.searchInput.addEventListener("input", (event) => {
  state.search = event.target.value;
  render();
});

els.scoreRange.addEventListener("input", (event) => {
  state.minScore = Number(event.target.value);
  render();
});

els.onlyTwinBuy.addEventListener("change", (event) => {
  state.onlyTwinBuy = event.target.checked;
  render();
});

els.analyzeButton.addEventListener("click", runAnalysis);

loadReport()
  .then((report) => {
    state.report = report;
    render();
    setAnalyzeState(false, report.source?.mode === "empty" ? "아직 분석을 실행하지 않았습니다." : "기존 분석 결과 표시 중");
  })
  .catch((error) => {
    console.error(error);
    els.pickCards.innerHTML = `<p class="empty">분석 결과를 불러오지 못했습니다. Python 생성기를 먼저 실행하세요.</p>`;
  });
