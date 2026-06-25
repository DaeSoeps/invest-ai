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
    signal: stock.signal || "-",
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

function formatDate(value) {
  if (!value) return "분석 대기 중";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toLocaleString("ko-KR")} 생성`;
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
              <p>${stock.note}</p>
              <span class="risk">${stock.risk}</span>
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
          <td class="${signedClass(stock.foreign)}">${formatSigned(stock.foreign)}</td>
          <td class="${signedClass(stock.foreign_streak)}">${stock.foreign_streak}일</td>
          <td>${stock.ownership.toFixed(2)}%</td>
          <td class="${signedClass(stock.institution)}">${formatSigned(stock.institution)}</td>
          <td class="${signedClass(stock.institution_streak)}">${stock.institution_streak}일</td>
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
          <td class="num-neg">${stock.drawdown.toFixed(1)}%</td>
          <td>${stock.market_cap}</td>
          <td>${stock.per}</td>
        </tr>
      `;
        })
        .join("")
    : `<tr><td colspan="5" class="empty-cell">AI 분석 실행 후 가격 위치가 표시됩니다.</td></tr>`;
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
              <span class="news-time">${item.time || "-"}</span>
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
