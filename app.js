const state = {
  tab: "picks",
  search: "",
  minScore: 60,
  onlyTwinBuy: false,
  report: null,
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
  const response = await fetch("./data/report.json", { cache: "no-store" });
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
  if (!value) return "분석 결과";
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
    : `<p class="empty">조건에 맞는 종목이 없습니다.</p>`;
}

function renderFlow(items) {
  els.flowRows.innerHTML = items
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
    .join("");
}

function renderValuation(items) {
  els.valuationRows.innerHTML = items
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
    .join("");
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
    : `<p class="empty">테마 분석 결과가 없습니다.</p>`;
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
    : `<p class="empty">조건에 맞는 뉴스가 없습니다.</p>`;
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

loadReport()
  .then((report) => {
    state.report = report;
    render();
  })
  .catch((error) => {
    console.error(error);
    els.pickCards.innerHTML = `<p class="empty">분석 결과를 불러오지 못했습니다. Python 생성기를 먼저 실행하세요.</p>`;
  });
