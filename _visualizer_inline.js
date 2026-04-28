
    const COLORS = ['#00ff9d', '#00d1ff', '#ff4757', '#ffa502', '#cc44ff', '#eccc68', '#7bed9f', '#ff6b81', '#1e90ff', '#ffffff'];
    let currentFilters = { source: 'backtest', round: 5, day: 2 };
    let selectedIds = [];
    let activeTab = 'performance';
    let sortMetric = 'pnl';
    let sortDirection = 'desc';
    let assetSortMetric = 'spread';
    let assetSortDirection = 'desc';
    let stabilitySortMetric = 'consistency';
    let stabilitySortDirection = 'desc';
    let heatmapSortMetric = 'spread';
    let heatmapSortDirection = 'desc';
    let managerState = { groups: [], selectedDeleteIds: new Set() };
    let compareSources = { a: 'backtest', b: 'live' };
    let charts = {};
    const LIVE_DATA_STORE = typeof LIVE_LOG_DATA !== 'undefined' ? LIVE_LOG_DATA : {};
    const I4BT_DATA_STORE = typeof I4BT_DATA !== 'undefined' ? I4BT_DATA : {};
    const SOURCE_LABELS = { backtest: 'BACKTEST', i4bt: 'I4BT', live: 'LIVE LOGS' };
    function colorForTraderName(name) {
        const s = String(name || '');
        let h = 0;
        for (let i = 0; i < s.length; i += 1) h = ((h * 31) + s.charCodeAt(i)) >>> 0;
        // Wider deterministic palette than fixed preset; stable per trader name.
        const hue = h % 360;
        const sat = 68 + (h % 18);   // 68-85
        const lit = 52 + (h % 8);    // 52-59
        return `hsl(${hue} ${sat}% ${lit}%)`;
    }
    function getDataStore() {
        if (currentFilters.source === 'live') return LIVE_DATA_STORE;
        if (currentFilters.source === 'i4bt') return I4BT_DATA_STORE;
        return BACKTEST_DATA;
    }
    function getSourceStore(source) {
        if (source === 'live') return LIVE_DATA_STORE;
        if (source === 'i4bt') return I4BT_DATA_STORE;
        return BACKTEST_DATA;
    }
    function getSourceFilteredIds(source, round, day) {
        const store = getSourceStore(source);
        return Object.keys(store).filter(id => {
            const r = store[id];
            return r.round === round && r.day === day;
        });
    }
    function chooseSourceDay(source, round, preferredDay) {
        const store = getSourceStore(source);
        const days = [...new Set(Object.values(store).filter(r => r.round === round).map(r => r.day))].sort((a, b) => a - b);
        if (!days.length) return null;
        if (days.includes(preferredDay)) return preferredDay;
        return days[0];
    }
    function getAvailableRounds() {
        if (currentFilters.source === 'live') return [3, 4, 5];
        return [...new Set(Object.values(getDataStore()).map(r => r.round))].sort((a, b) => a - b);
    }
    function updateSourcePills() {
        document.getElementById('source-backtest-btn')?.classList.toggle('active', currentFilters.source === 'backtest');
        document.getElementById('source-i4bt-btn')?.classList.toggle('active', currentFilters.source === 'i4bt');
        document.getElementById('source-live-btn')?.classList.toggle('active', currentFilters.source === 'live');
    }
    function updateCompareSourcePills() {
        ['backtest', 'i4bt', 'live'].forEach(src => {
            document.getElementById(`compare-source-a-${src}`)?.classList.toggle('active', compareSources.a === src);
            document.getElementById(`compare-source-b-${src}`)?.classList.toggle('active', compareSources.b === src);
        });
        const colA = document.getElementById('compare-col-a');
        const colB = document.getElementById('compare-col-b');
        const colD = document.getElementById('compare-col-delta');
        if (colA) colA.textContent = `${SOURCE_LABELS[compareSources.a] || 'A'} PNL`;
        if (colB) colB.textContent = `${SOURCE_LABELS[compareSources.b] || 'B'} PNL`;
        if (colD) colD.textContent = `DELTA (${SOURCE_LABELS[compareSources.b] || 'B'}-${SOURCE_LABELS[compareSources.a] || 'A'})`;
    }
    function updateContextBadge() {
        const el = document.getElementById('contextBadge');
        if (!el) return;
        const sourceLabel = SOURCE_LABELS[currentFilters.source] || 'BACKTEST';
        const dayLabel = currentFilters.day === 'total' ? 'TOTAL' : `D${currentFilters.day}`;
        el.textContent = `Viewing: ${sourceLabel} | R${currentFilters.round} ${dayLabel}`;
    }
    function updateRefreshButton() {
        const btn = document.getElementById('refreshBtn');
        if (!btn) return;
        btn.textContent = 'REFETCH';
    }
    function getCurrentFilteredIds() {
        const dataStore = getDataStore();
        return Object.keys(dataStore).filter(id => {
            const r = dataStore[id];
            if (currentFilters.day === 'total') return r.round === currentFilters.round;
            return r.round === currentFilters.round && r.day === currentFilters.day;
        });
    }
    function updateManagerModeUI() {
        const isLive = currentFilters.source === 'live';
        const removeBtn = document.getElementById('managerRemoveBtn');
        const selectAllBtn = document.getElementById('managerSelectAllBtn');
        if (removeBtn) removeBtn.textContent = isLive ? 'CLEAN SELECTED FILES' : 'REMOVE SELECTED';
        if (selectAllBtn) selectAllBtn.textContent = isLive ? 'SELECT ALL CLEAN CANDIDATES' : 'SELECT ALL DELETE CANDIDATES';
    }
    function setSourceFilter(source) {
        if (!['backtest', 'i4bt', 'live'].includes(source)) return;
        currentFilters.source = source;
        const availableDays = getAvailableDays(currentFilters.round);
        const totalBtn = document.getElementById('dtotal-btn');
        if (totalBtn) totalBtn.style.display = source === 'live' ? 'none' : 'block';
        if (source === 'live' && currentFilters.day === 'total') {
            currentFilters.day = availableDays.length ? availableDays[0] : 0;
        }
        if (currentFilters.day !== 'total' && !availableDays.includes(currentFilters.day)) currentFilters.day = availableDays.length ? availableDays[0] : 0;
        selectedIds = [];
        updateSourcePills();
        updateRefreshButton();
        updateManagerModeUI();
        setFilter('round', currentFilters.round);
        updateContextBadge();
        renderSidebar();
        renderActiveTab();
        refreshDuplicateManager();
    }
    function setCompareSources(a, b) {
        if (!['backtest', 'i4bt', 'live'].includes(a) || !['backtest', 'i4bt', 'live'].includes(b) || a === b) return;
        compareSources = { a, b };
        updateCompareSourcePills();
        if (activeTab === 'compare') renderCompare();
    }

    function init() {
        try {
            const saved = sessionStorage.getItem('visualizer_refresh_state');
            if (saved) {
                const parsed = JSON.parse(saved);
                if (parsed && parsed.currentFilters) currentFilters = parsed.currentFilters;
                if (parsed && parsed.activeTab) activeTab = parsed.activeTab;
                sessionStorage.removeItem('visualizer_refresh_state');
            }
        } catch (e) {}
        updateSortIndicators();
        updateAssetSortIndicators();
        updateStabilitySortIndicators();
        updateHeatmapSortIndicators();
        updateSourcePills();
        updateCompareSourcePills();
        updateRefreshButton();
        updateManagerModeUI();
        setSourceFilter(currentFilters.source || 'backtest');
        if (activeTab !== 'performance') switchTab(activeTab);
        renderSidebar();
        renderActiveTab();
        refreshDuplicateManager();
        document.addEventListener('click', event => {
            const dd = document.getElementById('managerRoundDropdown');
            if (!dd || !dd.contains(event.target)) dd.classList.remove('open');
        });
        // Clean temporary refresh query params for file:// usage.
        if (window.location.search.includes('refresh=')) {
            const cleanUrl = `${window.location.pathname}${window.location.hash || ''}`;
            window.history.replaceState({}, '', cleanUrl);
        }
    }
    function switchTab(t) { 
        activeTab = t; 
        document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
        document.querySelector(`.tab[onclick*="${t}"]`).classList.add('active');
        document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
        document.getElementById(`tab-${t}`).classList.remove('hidden');
        const dayRow = document.getElementById('dayFilterRow');
        if (dayRow) dayRow.style.display = t === 'compare' ? 'none' : 'flex';
        renderSidebar();
        renderActiveTab();
    }
    function getAvailableDays(round) {
        const dataStore = getDataStore();
        return [...new Set(
            Object.values(dataStore)
                .filter(r => r.round === round)
                .map(r => r.day)
        )].sort((a, b) => a - b);
    }
    function setFilter(type, val) {
        const dataStore = getDataStore();
        const prevRound = currentFilters.round;
        const prevDay = currentFilters.day;
        const prevSelectedTraderNames = new Set(selectedIds.map(id => dataStore[id]?.trader).filter(Boolean));
        currentFilters[type] = val;
        const availableDays = getAvailableDays(currentFilters.round);
        if (type === 'round') {
            const prevDays = getAvailableDays(prevRound);
            if (prevDay !== 'total') {
                const oldIdx = Math.max(0, prevDays.indexOf(prevDay));
                const newIdx = Math.min(oldIdx, Math.max(0, availableDays.length - 1));
                currentFilters.day = availableDays.length ? availableDays[newIdx] : 0;
            }
        } else if (currentFilters.day !== 'total' && !availableDays.includes(currentFilters.day)) {
            currentFilters.day = availableDays.length ? availableDays[0] : 0;
        }
        document.querySelectorAll('.scope-pill').forEach(p => p.classList.remove('active'));
        const roundBtn = document.getElementById(`r${currentFilters.round}-btn`);
        if (roundBtn) roundBtn.classList.add('active');
        [0, 1, 2, 3, 4].forEach(day => {
            const dayBtn = document.getElementById(`d${day}-btn`);
            if (!dayBtn) return;
            dayBtn.style.display = availableDays.includes(day) ? 'block' : 'none';
        });
        const dayBtn = currentFilters.day === 'total'
            ? document.getElementById('dtotal-btn')
            : document.getElementById(`d${currentFilters.day}-btn`);
        if (dayBtn) dayBtn.classList.add('active');
        const filteredIds = getCurrentFilteredIds();
        selectedIds = filteredIds.filter(id => prevSelectedTraderNames.has(dataStore[id].trader));
        updateContextBadge();
        renderSidebar();
        renderActiveTab();
    }
    function resetSelection() { 
        selectedIds = []; 
        renderSidebar(); 
        renderActiveTab(); 
        if (selectedIds.length === 0) {
            if (charts.perf) charts.perf.destroy();
            if (charts.attr) charts.attr.destroy();
            const lb = document.querySelector('#leaderboardTable tbody'); if (lb) lb.innerHTML = '';
            const alb = document.querySelector('#assetLeaderboard tbody'); if (alb) alb.innerHTML = '';
        }
    }
    function setSortMetric(metric) {
        if (sortMetric === metric) sortDirection = sortDirection === 'desc' ? 'asc' : 'desc';
        else {
            sortMetric = metric;
            sortDirection = 'desc';
        }
        updateSortIndicators();
        renderPerformance();
    }
    function updateSortIndicators() {
        document.querySelectorAll('.sortable-th').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.sort-icon').forEach(el => { el.textContent = '-'; });
        const icon = document.querySelector(`.sort-icon[data-sort-key="${sortMetric}"]`);
        if (!icon) return;
        icon.textContent = sortDirection === 'desc' ? 'v' : '^';
        icon.parentElement.classList.add('active');
    }
    function setAssetSortMetric(metric) {
        if (assetSortMetric === metric) assetSortDirection = assetSortDirection === 'desc' ? 'asc' : 'desc';
        else {
            assetSortMetric = metric;
            assetSortDirection = 'desc';
        }
        updateAssetSortIndicators();
        renderAttribution();
    }
    function updateAssetSortIndicators() {
        document.querySelectorAll('.asset-sort-icon').forEach(el => { el.textContent = '-'; });
        const icon = document.querySelector(`.asset-sort-icon[data-sort-key="${assetSortMetric}"]`);
        if (!icon) return;
        icon.textContent = assetSortDirection === 'desc' ? 'v' : '^';
    }
    function setStabilitySortMetric(metric) {
        if (stabilitySortMetric === metric) stabilitySortDirection = stabilitySortDirection === 'desc' ? 'asc' : 'desc';
        else {
            stabilitySortMetric = metric;
            stabilitySortDirection = 'desc';
        }
        updateStabilitySortIndicators();
        renderStability();
    }
    function updateStabilitySortIndicators() {
        document.querySelectorAll('.stability-sort-icon').forEach(el => { el.textContent = '-'; });
        const icon = document.querySelector(`.stability-sort-icon[data-sort-key="${stabilitySortMetric}"]`);
        if (!icon) return;
        icon.textContent = stabilitySortDirection === 'desc' ? 'v' : '^';
    }
    function setHeatmapSortMetric(metric) {
        if (heatmapSortMetric === metric) heatmapSortDirection = heatmapSortDirection === 'desc' ? 'asc' : 'desc';
        else {
            heatmapSortMetric = metric;
            heatmapSortDirection = 'desc';
        }
        updateHeatmapSortIndicators();
        renderStability();
    }
    function updateHeatmapSortIndicators() {
        document.querySelectorAll('.heatmap-sort-icon').forEach(el => { el.textContent = '-'; });
        const icon = document.querySelector(`.heatmap-sort-icon[data-sort-key="${heatmapSortMetric}"]`);
        if (!icon) return;
        icon.textContent = heatmapSortDirection === 'desc' ? 'v' : '^';
    }
    function renderSidebar() {
        const dataStore = getDataStore();
        const container = document.getElementById('strategyList'); container.innerHTML = '';
        const isGroupedBacktestTotal = currentFilters.source === 'backtest' && currentFilters.day === 'total' && activeTab !== 'compare';
        if (isGroupedBacktestTotal) {
            const byTrader = new Map();
            Object.keys(dataStore).forEach(id => {
                const r = dataStore[id];
                if (r.round !== currentFilters.round) return;
                if (!byTrader.has(r.trader)) byTrader.set(r.trader, []);
                byTrader.get(r.trader).push({ id, run: r });
            });
            const groups = [];
            [...byTrader.entries()].forEach(([trader, items]) => {
                // Build explicit variant tracks for same trader when multiple backtests exist per day.
                const byDay = new Map();
                items.forEach(it => {
                    if (!byDay.has(it.run.day)) byDay.set(it.run.day, []);
                    byDay.get(it.run.day).push(it);
                });
                [...byDay.keys()].forEach(day => {
                    byDay.get(day).sort((a, b) => runIdScore(b.id) - runIdScore(a.id));
                });
                const variantCount = Math.max(1, ...[...byDay.values()].map(arr => arr.length));
                for (let variantIdx = 0; variantIdx < variantCount; variantIdx += 1) {
                    const member = [];
                    [...byDay.keys()].sort((a, b) => a - b).forEach(day => {
                        const pick = byDay.get(day)[variantIdx];
                        if (pick) member.push(pick);
                    });
                    if (!member.length) continue;
                    const memberIds = member.map(x => x.id);
                    const totalPnl = member.reduce((acc, x) => acc + (Number(x.run.final_pnl) || 0), 0);
                    const days = [...new Set(member.map(x => x.run.day))].sort((a, b) => a - b);
                    groups.push({
                        trader,
                        variantIdx,
                        totalPnl,
                        days,
                        memberIds
                    });
                }
            });
            groups.sort((a, b) => b.totalPnl - a.totalPnl);

            groups.forEach(group => {
                const isActive = group.memberIds.every(id => selectedIds.includes(id));
                const card = document.createElement('div'); card.className = `strategy-card ${isActive ? 'active' : ''}`;
                const color = isActive ? colorForTraderName(group.trader) : 'transparent';
                const dayLabel = group.days.map(d => `D${d}`).join(', ');
                const variantLabel = `V${group.variantIdx + 1}`;
                card.innerHTML = `<div class="card-color" style="background:${color}"></div><span class="card-name">${group.trader} ${variantLabel}</span><span class="card-stats">TOTAL: ${Math.round(group.totalPnl).toLocaleString()} | ${dayLabel}</span>`;
                card.onclick = () => toggleSelect(`grp:${group.trader}::${group.variantIdx}`);
                container.appendChild(card);
            });
            return;
        }
        let filtered = Object.keys(dataStore).filter(id => {
            const r = dataStore[id];
            if (activeTab === 'compare') return r.round === currentFilters.round && hasCompareCounterpart(r, currentFilters.source);
            if (currentFilters.day === 'total') return r.round === currentFilters.round;
            return r.round === currentFilters.round && r.day === currentFilters.day;
        });
        filtered = filtered.sort((a, b) => dataStore[b].final_pnl - dataStore[a].final_pnl);
        filtered.forEach(id => {
            const r = dataStore[id]; const isActive = selectedIds.includes(id);
            const card = document.createElement('div'); card.className = `strategy-card ${isActive ? 'active' : ''}`;
            const color = isActive ? colorForTraderName(r.trader) : 'transparent';
            card.innerHTML = `<div class="card-color" style="background:${color}"></div><span class="card-name">${r.trader}</span><span class="card-stats">PnL: ${Math.round(r.final_pnl).toLocaleString()}</span>`;
            card.onclick = () => toggleSelect(id); container.appendChild(card);
        });
    }
    function hasCompareCounterpart(run, source) {
        const otherSource = source === compareSources.a ? compareSources.b : compareSources.a;
        const otherStore = getSourceStore(otherSource || 'live');
        return Object.values(otherStore).some(r => r.round === run.round && r.trader === run.trader);
    }
    function toggleSelect(id) {
        if (typeof id === 'string' && id.startsWith('grp:')) {
            const token = id.slice(4);
            const [trader, variantRaw] = token.split('::');
            const variantIdx = Number(variantRaw || 0);
            const dataStore = getDataStore();
            const items = Object.keys(dataStore)
                .map(runId => ({ runId, run: dataStore[runId] }))
                .filter(x => x.run.round === currentFilters.round && x.run.trader === trader);
            const byDay = new Map();
            items.forEach(x => {
                if (!byDay.has(x.run.day)) byDay.set(x.run.day, []);
                byDay.get(x.run.day).push(x);
            });
            [...byDay.keys()].forEach(day => {
                byDay.get(day).sort((a, b) => runIdScore(b.runId) - runIdScore(a.runId));
            });
            const memberIds = [];
            [...byDay.keys()].sort((a, b) => a - b).forEach(day => {
                const pick = byDay.get(day)[variantIdx];
                if (pick) memberIds.push(pick.runId);
            });
            if (!memberIds.length) return;
            const fullySelected = memberIds.every(runId => selectedIds.includes(runId));
            if (fullySelected) {
                selectedIds = selectedIds.filter(runId => !memberIds.includes(runId));
            } else {
                memberIds.forEach(runId => {
                    if (!selectedIds.includes(runId)) selectedIds.push(runId);
                });
            }
            renderSidebar(); renderActiveTab();
            return;
        }
        const idx = selectedIds.indexOf(id); if (idx > -1) selectedIds.splice(idx, 1); else selectedIds.push(id);
        renderSidebar(); renderActiveTab();
    }
    function buildEquityCurve(history) {
        const byTs = new Map();
        history.forEach(point => {
            if (!byTs.has(point.ts)) byTs.set(point.ts, new Map());
            byTs.get(point.ts).set(point.symbol, point.pnl);
        });
        const symbols = new Map();
        const orderedTs = [...byTs.keys()].sort((a, b) => a - b);
        return orderedTs.map(ts => {
            byTs.get(ts).forEach((pnl, symbol) => symbols.set(symbol, pnl));
            const total = [...symbols.values()].reduce((acc, val) => acc + val, 0);
            return { ts, pnl: total };
        });
    }
    function calcMDD(curve) {
        let peak = -Infinity;
        let maxDrawdown = 0;
        curve.forEach(point => {
            if (point.pnl > peak) peak = point.pnl;
            const drawdown = point.pnl - peak;
            if (drawdown < maxDrawdown) maxDrawdown = drawdown;
        });
        return maxDrawdown;
    }
    function calcReturns(curve) {
        const returns = [];
        for (let i = 1; i < curve.length; i += 1) returns.push(curve[i].pnl - curve[i - 1].pnl);
        return returns;
    }
    function calcSharpe(returns) {
        if (returns.length < 2) return 0;
        const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
        const variance = returns.reduce((acc, val) => acc + (val - mean) ** 2, 0) / (returns.length - 1);
        const std = Math.sqrt(variance);
        if (!std) return 0;
        return (mean / std) * Math.sqrt(returns.length);
    }
    function calcConcentration(finalPnlByProduct) {
        const absValues = Object.values(finalPnlByProduct || {}).map(v => Math.abs(v));
        const total = absValues.reduce((a, b) => a + b, 0);
        if (!total) return 0;
        return Math.max(...absValues) / total;
    }
    function evaluateSelectionScore(run, mdd, sharpe, greenTicks, ratio) {
        const peerRuns = Object.values(getDataStore()).filter(r => r.round === run.round && r.trader === run.trader);
        const pnls = peerRuns.map(r => r.final_pnl);
        const avgPnl = pnls.length ? pnls.reduce((a, b) => a + b, 0) / pnls.length : run.final_pnl;
        const worstDay = pnls.length ? Math.min(...pnls) : run.final_pnl;
        const range = pnls.length ? Math.max(...pnls) - Math.min(...pnls) : 0;
        const concentration = calcConcentration(run.final_pnl_by_product);
        const reasons = [];

        // Hard gates for risk control.
        const redGate = mdd <= -45000 || worstDay <= -25000 || concentration >= 0.72 || sharpe < -0.3;
        const amberGate = mdd <= -25000 || worstDay <= -8000 || concentration >= 0.58 || sharpe < 0.1;
        if (mdd <= -25000) reasons.push(`High drawdown (${Math.round(mdd).toLocaleString()})`);
        if (worstDay <= -8000) reasons.push(`Weak worst-day (${Math.round(worstDay).toLocaleString()})`);
        if (concentration >= 0.58) reasons.push(`Concentrated PnL (${Math.round(concentration * 100)}%)`);
        if (sharpe < 0.1) reasons.push(`Low Sharpe (${sharpe.toFixed(2)})`);
        if (reasons.length === 0) reasons.push('Balanced return/risk profile');

        const score = Math.max(0, Math.min(100, Math.round(
            24
            + (Math.max(-2, Math.min(4, ratio)) * 9)
            + (Math.max(-1.5, Math.min(2.5, sharpe)) * 12)
            + (greenTicks * 0.22)
            + (avgPnl > 0 ? 8 : -8)
            - (Math.min(50000, Math.abs(worstDay)) / 5000)
            - (Math.min(90000, Math.abs(range)) / 9000)
            - (concentration * 28)
        )));
        if (redGate || score < 40) return { score, statusLabel: 'RED', statusRank: 0, reason: reasons.join(' | ') };
        if (amberGate || score < 65) return { score, statusLabel: 'AMBER', statusRank: 1, reason: reasons.join(' | ') };
        return { score, statusLabel: 'GREEN', statusRank: 2, reason: reasons.join(' | ') };
    }
    function computePerformanceRows(ids) {
        const dataStore = getDataStore();
        const rows = [];
        ids.forEach(id => {
            const r = dataStore[id];
            const equityCurve = buildEquityCurve(r.history);
            const mdd = calcMDD(equityCurve);
            const ratio = Number((r.final_pnl / (Math.abs(mdd) || 1)).toFixed(2));
            const returns = calcReturns(equityCurve);
            const sharpe = calcSharpe(returns);
            const greenTicks = returns.length ? Math.round((returns.filter(v => v > 0).length / returns.length) * 100) : 0;
            const readiness = Math.min(100, Math.max(0, Math.round(((Number(ratio) * 0.6) + (Math.max(-2, Math.min(2, sharpe)) + 2) * 10 + (greenTicks / 5)))));
            const selection = evaluateSelectionScore(r, mdd, sharpe, greenTicks, ratio);
            rows.push({
                id,
                trader: r.trader,
                round: r.round,
                day: r.day,
                dataset: r.dataset,
                pnl: r.final_pnl,
                maxDrawdown: mdd,
                calmar: ratio,
                sharpe,
                greenTicks,
                readiness,
                selectionScore: selection.score,
                status: selection.statusLabel,
                statusReason: selection.reason,
                concentration: calcConcentration(r.final_pnl_by_product),
                finalPnlByProduct: r.final_pnl_by_product || {}
            });
        });
        return rows;
    }
    function computeAttributionRows(ids) {
        const dataStore = getDataStore();
        const assets = [...new Set(ids.flatMap(id => Object.keys(dataStore[id].final_pnl_by_product || {})))].sort();
        return assets.map(asset => {
            const scores = ids.map(id => ({ id, trader: dataStore[id].trader, val: dataStore[id].final_pnl_by_product?.[asset] || 0 }));
            scores.sort((x, y) => y.val - x.val);
            return {
                asset,
                bestTrader: scores[0]?.trader || null,
                maxProfit: scores[0]?.val || 0,
                leastProfit: scores[scores.length - 1]?.val || 0,
                spread: (scores[0]?.val || 0) - (scores[scores.length - 1]?.val || 0),
                byTrader: scores
            };
        });
    }
    function computeStabilityRows(round) {
        const roundRuns = Object.values(getDataStore()).filter(r => r.round === round);
        const roundDays = [...new Set(roundRuns.map(r => r.day))].sort((a, b) => a - b);
        const displayDays = roundDays.slice(0, 3);
        const fallbackDays = [0, 1, 2];
        while (displayDays.length < 3) displayDays.push(fallbackDays[displayDays.length]);

        const traders = [...new Set(roundRuns.map(r => r.trader))];
        const stabilityRows = [];
        traders.forEach(trader => {
            const runs = roundRuns.filter(r => r.trader === trader);
            if (runs.length < 2) return;
            const d0 = runs.find(r => r.day === displayDays[0])?.final_pnl || 0;
            const d1 = runs.find(r => r.day === displayDays[1])?.final_pnl || 0;
            const d2 = runs.find(r => r.day === displayDays[2])?.final_pnl || 0;
            const avg = (d0 + d1 + d2) / 3;
            const range = Math.max(d0, d1, d2) - Math.min(d0, d1, d2);
            const consistency = Math.max(0, 100 - Math.round((Math.abs(range) / (Math.abs(avg) + 1)) * 100));
            stabilityRows.push({ trader, dayLabels: displayDays, values: [d0, d1, d2], avg, range, consistency });
        });

        const assets = [...new Set(roundRuns.flatMap(r => Object.keys(r.final_pnl_by_product || {})))].sort();
        const heatmapRows = assets.map(asset => {
            const dayVals = displayDays.map(day => {
                const vals = roundRuns.filter(r => r.day === day).map(r => r.final_pnl_by_product?.[asset] || 0);
                if (!vals.length) return 0;
                return vals.reduce((a, b) => a + b, 0) / vals.length;
            });
            return { asset, dayLabels: displayDays, values: dayVals, spread: Math.max(...dayVals) - Math.min(...dayVals) };
        });

        return { dayLabels: displayDays, crossDayRows: stabilityRows, heatmapRows };
    }
    function exportAnalytics() {
        const dataStore = getDataStore();
        const availableIds = getCurrentFilteredIds();
        const availableSet = new Set(availableIds);
        const selectedInScope = selectedIds.filter(id => availableSet.has(id));
        const chosenIds = selectedInScope.length ? selectedInScope : availableIds;
        const performance = computePerformanceRows(chosenIds);
        // Match attribution tab behavior: one selected run per trader.
        const uniqueByTrader = new Map();
        chosenIds.forEach(id => {
            const run = dataStore[id];
            if (!run) return;
            const prev = uniqueByTrader.get(run.trader);
            if (!prev || (run.final_pnl || 0) > (prev.final_pnl || 0)) uniqueByTrader.set(run.trader, id);
        });
        const attributionIds = [...uniqueByTrader.values()];
        const attribution = computeAttributionRows(attributionIds);
        const stability = computeStabilityRows(currentFilters.round);
        const compareRows = [...document.querySelectorAll('#compareTable tbody tr')].map(tr => {
            const tds = [...tr.querySelectorAll('td')].map(td => td.textContent?.trim() || '');
            return {
                trader: tds[0] || '',
                backtestPnl: tds[1] || '',
                livePnl: tds[2] || '',
                delta: tds[3] || '',
                commonTicks: tds[4] || '',
                coverage: tds[5] || ''
            };
        });
        const compareNote = document.getElementById('compareNote')?.textContent || '';
        const payload = {
            exportedAt: new Date().toISOString(),
            filters: { ...currentFilters },
            sourceMode: currentFilters.source,
            dayMode: currentFilters.day === 'total' ? 'total' : 'single_day',
            activeTab,
            selectedIds: [...selectedIds],
            includedIds: chosenIds,
            strategyCount: chosenIds.length,
            performance,
            attribution,
            stability,
            compare: {
                note: compareNote,
                rows: compareRows,
                rowCount: compareRows.length
            }
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        a.download = `visualizer_snapshot_${stamp}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }
    async function loadData() {
        const btn = document.getElementById('refreshBtn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'LOADING...';
        }

        // file:// pages cannot call local Python endpoints directly.
        if (window.location.protocol === 'file:') {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'REFETCH';
            }
            alert('Start the loader server first:\npython tools/visualizer_loader_server.py --repo-root . --port 8765\nThen open http://127.0.0.1:8765/visualizer.html');
            return;
        }
        try {
            let res = await fetch('/api/load-data', { method: 'POST' });
            if (res.status === 405) {
                // Fallback for static servers that only allow GET.
                res = await fetch('/api/load-data', { method: 'GET' });
            }
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            await res.json();
            // The parser updates local JS files. Reload to pick up fresh data.
            window.location.reload();
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'REFETCH';
            }
        } catch (e) {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'LOAD FAILED';
            }
            console.error('Load failed:', e);
            alert('Load Data failed. Ensure you started the custom server: "python tools/visualizer_loader_server.py --repo-root . --port 8765" Then use http://127.0.0.1:8765/visualizer.html');
            setTimeout(() => {
                if (btn) btn.textContent = 'REFETCH';
            }, 1800);
        }
    }
    function runIdScore(id) {
        const m = id.match(/(\d{10,})/);
        return m ? Number(m[1]) : 0;
    }
    function fingerprintRun(run) {
        return JSON.stringify({
            trader: run.trader,
            dataset: run.dataset,
            day: run.day,
            round: run.round,
            pnl: Math.round((run.final_pnl || 0) * 100) / 100,
            byProd: run.final_pnl_by_product || {}
        });
    }
    function buildDuplicateGroups() {
        const dataStore = getDataStore();
        const buckets = {};
        Object.entries(dataStore).forEach(([id, run]) => {
            const fp = fingerprintRun(run);
            if (!buckets[fp]) buckets[fp] = [];
            buckets[fp].push({ id, run });
        });
        const groups = Object.values(buckets).filter(items => items.length > 1).map(items => {
            const sorted = [...items].sort((a, b) => runIdScore(b.id) - runIdScore(a.id));
            return { keep: sorted[0].id, items: sorted };
        });
        groups.sort((a, b) => a.items[0].run.trader.localeCompare(b.items[0].run.trader));
        return groups;
    }
    function refreshDuplicateManager() {
        const groups = buildDuplicateGroups();
        const selected = new Set();
        groups.forEach(g => g.items.forEach(x => { if (x.id !== g.keep) selected.add(x.id); }));
        managerState = { groups, selectedDeleteIds: selected };
        renderManagerTable();
    }
    function toggleManagerRoundDropdown(event) {
        event.preventDefault();
        const dd = document.getElementById('managerRoundDropdown');
        if (dd) dd.classList.toggle('open');
    }
    function setManagerRoundFilter(value, label) {
        const input = document.getElementById('managerRoundFilter');
        const labelEl = document.getElementById('managerRoundLabel');
        if (input) input.value = value;
        if (labelEl) labelEl.textContent = label;
        document.querySelectorAll('.manager-dropdown-item').forEach(el => {
            el.classList.toggle('active', el.dataset.value === value);
        });
        const dd = document.getElementById('managerRoundDropdown');
        if (dd) dd.classList.remove('open');
        renderManagerTable();
    }
    function renderManagerTable() {
        const tbody = document.querySelector('#managerTable tbody');
        const summary = document.getElementById('managerSummary');
        const deselectBtn = document.getElementById('managerDeselectBtn');
        const removeBtn = document.getElementById('managerRemoveBtn');
        const traderFilter = (document.getElementById('managerTraderFilter')?.value || '').trim().toLowerCase();
        const runFilter = (document.getElementById('managerRunFilter')?.value || '').trim().toLowerCase();
        const roundFilter = (document.getElementById('managerRoundFilter')?.value || '').trim();
        if (!tbody || !summary) return;
        tbody.innerHTML = '';
        const groups = managerState.groups || [];
        let visibleRows = 0;
        let visibleGroups = 0;
        let visibleDeleteCandidates = 0;
        let visibleSelected = 0;
        groups.forEach((g, idx) => {
            let groupVisible = false;
            let groupRowPrinted = false;
            g.items.forEach((entry, itemIdx) => {
                const r = entry.run;
                const isKeep = entry.id === g.keep;
                const isSelected = managerState.selectedDeleteIds.has(entry.id);
                if (traderFilter && !String(r.trader).toLowerCase().includes(traderFilter)) return;
                if (runFilter && !String(entry.id).toLowerCase().includes(runFilter)) return;
                if (roundFilter && String(r.round) !== roundFilter) return;
                groupVisible = true;
                visibleRows += 1;
                if (!isKeep) {
                    visibleDeleteCandidates += 1;
                    if (isSelected) visibleSelected += 1;
                }
                const actionCell = isKeep
                    ? '<span style="color:var(--accent);font-weight:700;">KEEP</span>'
                    : '<span style="color:var(--danger);font-weight:700;">DELETE</span>';
                const selectCell = isKeep
                    ? ''
                    : `<input class="manager-checkbox" type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleManagerDelete('${entry.id}')" />`;
                tbody.innerHTML += `<tr>
                    <td>${!groupRowPrinted ? `G${idx + 1}` : ''}</td>
                    <td>${entry.id}</td>
                    <td>${r.trader}</td>
                    <td>${r.round}</td>
                    <td>${r.day}</td>
                    <td>${Math.round(r.final_pnl).toLocaleString()}</td>
                    <td>${actionCell}</td>
                    <td>${selectCell}</td>
                </tr>`;
                groupRowPrinted = true;
            });
            if (groupVisible) visibleGroups += 1;
        });
        summary.textContent = `Duplicate groups: ${visibleGroups} | Visible rows: ${visibleRows} | Delete candidates: ${visibleDeleteCandidates} | Selected: ${visibleSelected}`;
        if (deselectBtn) deselectBtn.disabled = managerState.selectedDeleteIds.size === 0;
        if (removeBtn) removeBtn.disabled = managerState.selectedDeleteIds.size === 0;
    }
    function toggleManagerDelete(runId) {
        if (managerState.selectedDeleteIds.has(runId)) managerState.selectedDeleteIds.delete(runId);
        else managerState.selectedDeleteIds.add(runId);
        renderManagerTable();
    }
    function selectAllManagerDeletes() {
        const selected = new Set();
        managerState.groups.forEach(g => g.items.forEach(x => { if (x.id !== g.keep) selected.add(x.id); }));
        managerState.selectedDeleteIds = selected;
        renderManagerTable();
    }
    function deselectAllManagerDeletes() {
        managerState.selectedDeleteIds = new Set();
        renderManagerTable();
    }
    async function removeSelectedManagerRuns() {
        const dataStore = getDataStore();
        const targets = [...managerState.selectedDeleteIds];
        if (!targets.length) return;
        const source = currentFilters.source;
        if (!confirm(`Remove ${targets.length} selected run(s) from ${source === 'backtest' ? 'backtest artifacts + dataset' : 'live logs + dataset'}?`)) return;
        if (window.location.protocol === 'file:') {
            alert('Persistent remove requires the loader server. Start:\\npython tools/visualizer_loader_server.py --repo-root . --port 8765');
            return;
        }
        try {
            const res = await fetch('/api/remove-runs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source, run_ids: targets })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const payload = await res.json();
            if (!payload.ok) throw new Error(payload.error || 'Remove failed');
            if (source === 'live') {
                console.log('Live cleaner stats:', payload.live_cleanup || {}, payload.live_rebuild || {});
            } else {
                console.log('Backtest cleanup stats:', payload.backtest_cleanup || {}, payload.backtest_artifacts || {});
            }
        } catch (e) {
            console.error('Remove failed:', e);
            alert('Remove failed. Ensure you are using visualizer_loader_server.py');
            return;
        }
        targets.forEach(runId => { delete dataStore[runId]; });
        selectedIds = selectedIds.filter(id => dataStore[id]);
        managerState.selectedDeleteIds = new Set();
        refreshDuplicateManager();
        renderSidebar();
        renderActiveTab();
    }
    function renderActiveTab() {
        if (activeTab === 'performance') renderPerformance();
        if (activeTab === 'compare') renderCompare();
        if (activeTab === 'attribution') renderAttribution();
        if (activeTab === 'stability') renderStability();
        if (activeTab === 'manager') renderManagerTable();
    }

    function renderCompare() {
        const compareTableBody = document.querySelector('#compareTable tbody');
        const compareNote = document.getElementById('compareNote');
        if (compareTableBody) compareTableBody.innerHTML = '';
        if (selectedIds.length === 0) {
            if (compareNote) compareNote.textContent = 'Select one or more strategies in the sidebar to compare source A vs source B.';
            if (charts.compare) charts.compare.destroy();
            return;
        }
        const sourceAStore = getSourceStore(compareSources.a);
        const sourceBStore = getSourceStore(compareSources.b);
        const round = currentFilters.round;
        const sourceARoundRuns = Object.values(sourceAStore).filter(r => r.round === round);
        const sourceBRoundRuns = Object.values(sourceBStore).filter(r => r.round === round);
        const sourceADays = [...new Set(sourceARoundRuns.map(r => r.day))].sort((a, b) => a - b).slice(0, 3);
        const sourceBDays = [...new Set(sourceBRoundRuns.map(r => r.day))].sort((a, b) => a - b);
        if (!sourceADays.length || !sourceBDays.length) {
            const missing = !sourceADays.length ? (SOURCE_LABELS[compareSources.a] || 'source A') : (SOURCE_LABELS[compareSources.b] || 'source B');
            if (compareNote) compareNote.textContent = `Missing ${missing} data for round ${round}.`;
            if (charts.compare) charts.compare.destroy();
            return;
        }

        // Build a canonical multi-day x-axis from backtest timestamps: Day1 segment | Day2 segment | Day3 segment.
        const dayTsMap = new Map();
        sourceADays.forEach(day => {
            const ts = new Set();
            Object.values(sourceAStore)
                .filter(r => r.round === round && r.day === day)
                .forEach(r => (r.history || []).forEach(h => ts.add(h.ts)));
            dayTsMap.set(day, [...ts].sort((a, b) => a - b));
        });
        const labels = [];
        const indexByDayTs = new Map();
        const dayZones = [];
        sourceADays.forEach((day, zoneIdx) => {
            const start = labels.length;
            const tsList = dayTsMap.get(day) || [];
            tsList.forEach(ts => {
                const key = `${day}:${ts}`;
                indexByDayTs.set(key, labels.length);
                labels.push(`D${day}:${ts}`);
            });
            const end = labels.length - 1;
            dayZones.push({ day, start, end, zoneIdx });
        });
        if (!labels.length) {
            if (compareNote) compareNote.textContent = `No ${SOURCE_LABELS[compareSources.a] || 'source A'} timeline data for round ${round}.`;
            if (charts.compare) charts.compare.destroy();
            return;
        }

        const selectedRuns = selectedIds
            .map(id => ({ id, run: getDataStore()[id] }))
            .filter(x => x.run && x.run.round === round);

        const datasets = [];
        const summaryRows = [];
        const interpolateLinear = series => {
            const out = [...series];
            let left = -1;
            for (let i = 0; i < out.length; i += 1) {
                if (out[i] === null) continue;
                if (left >= 0 && i - left > 1) {
                    const leftVal = out[left];
                    const rightVal = out[i];
                    const span = i - left;
                    for (let j = left + 1; j < i; j += 1) {
                        const t = (j - left) / span;
                        out[j] = leftVal + ((rightVal - leftVal) * t);
                    }
                }
                left = i;
            }
            return out;
        };
        selectedRuns.forEach(({ id: selectedId, run: selectedRun }) => {
            const trader = selectedRun.trader;
            const btData = new Array(labels.length).fill(null);
            const liveData = new Array(labels.length).fill(null);
            let btTotalPnl = 0;
            let liveLatestPnl = 0;
            let livePlottedPoints = 0;
            let commonTicks = 0;
            const usedBtIds = new Set();
            const usedLiveIds = new Set();
            let btCarry = 0;
            let liveCarry = 0;

            sourceADays.forEach(day => {
                let sourceAId = null;
                if (currentFilters.source === compareSources.a && selectedRun.day === day) sourceAId = selectedId;
                if (!sourceAId) {
                    const dayCandidates = Object.entries(sourceAStore)
                        .filter(([_, r]) => r.round === round && r.day === day && r.trader === trader)
                        .sort((a, b) => (b[1].final_pnl || 0) - (a[1].final_pnl || 0));
                    sourceAId = dayCandidates[0]?.[0] || null;
                }
                if (!sourceAId) return;
                usedBtIds.add(sourceAId);
                const btCurve = buildEquityCurve(sourceAStore[sourceAId].history || []);
                btTotalPnl += Number(sourceAStore[sourceAId].final_pnl || 0);
                const btMap = new Map(btCurve.map(p => [p.ts, p.pnl]));
                btMap.forEach((pnl, ts) => {
                    const idx = indexByDayTs.get(`${day}:${ts}`);
                    if (idx !== undefined) btData[idx] = pnl + btCarry;
                });
                const btDayFinal = btCurve.length ? Number(btCurve[btCurve.length - 1].pnl || 0) : 0;
                btCarry += btDayFinal;

                let sourceBId = null;
                if (currentFilters.source === compareSources.b && selectedRun.day === day) sourceBId = selectedId;
                if (!sourceBId) {
                    const dayCandidates = Object.entries(sourceBStore)
                        .filter(([_, r]) => r.round === round && r.day === day && r.trader === trader)
                        .sort((a, b) => (b[1].final_pnl || 0) - (a[1].final_pnl || 0));
                    sourceBId = dayCandidates[0]?.[0] || null;
                }
                if (!sourceBId) return;
                usedLiveIds.add(sourceBId);
                const liveCurve = buildEquityCurve(sourceBStore[sourceBId].history || []);
                const liveMap = new Map(liveCurve.map(p => [p.ts, p.pnl]));
                liveLatestPnl = Number(sourceBStore[sourceBId].final_pnl || liveLatestPnl);
                liveMap.forEach((pnl, ts) => {
                    const idx = indexByDayTs.get(`${day}:${ts}`);
                    if (idx !== undefined) {
                        liveData[idx] = pnl + liveCarry;
                        livePlottedPoints += 1;
                        if (btMap.has(ts)) commonTicks += 1;
                    }
                });
                const liveDayFinal = liveCurve.length ? Number(liveCurve[liveCurve.length - 1].pnl || 0) : 0;
                liveCarry += liveDayFinal;
            });
            if (btData.every(v => v === null) || liveData.every(v => v === null)) return;
            const denseBtData = interpolateLinear(btData);
            const denseLiveData = interpolateLinear(liveData);

            const color = colorForTraderName(trader);
            const btRef = [...usedBtIds].slice(0, 2).join(',') || '-';
            const liveRef = [...usedLiveIds].slice(0, 2).join(',') || '-';
            datasets.push({
                label: `${trader} ${SOURCE_LABELS[compareSources.a] || 'A'} (${btRef})`,
                data: denseBtData,
                borderColor: color,
                backgroundColor: 'transparent',
                borderWidth: 2,
                pointRadius: 1.9,
                pointHoverRadius: 4,
                fill: false,
                tension: 0.15
            });
            datasets.push({
                label: `${trader} ${SOURCE_LABELS[compareSources.b] || 'B'} (${liveRef})`,
                data: denseLiveData,
                borderColor: '#ffffff',
                backgroundColor: 'rgba(255, 165, 0, 0.26)',
                borderDash: [6, 4],
                borderWidth: 2,
                pointRadius: 1.9,
                pointHoverRadius: 4,
                fill: '-1',
                tension: 0.15
            });
            const coverage = Math.round((commonTicks / Math.max(livePlottedPoints, 1)) * 100);
            summaryRows.push({
                trader: `${trader} (${(SOURCE_LABELS[compareSources.a] || 'A')}:${btRef} | ${(SOURCE_LABELS[compareSources.b] || 'B')}:${liveRef})`,
                btFinal: btTotalPnl,
                liveFinal: liveLatestPnl,
                delta: liveLatestPnl - btTotalPnl,
                commonTicks,
                coverage
            });
        });

        if (!datasets.length) {
            if (compareNote) compareNote.textContent = `No overlap to compare for selected strategies in round ${round}.`;
            if (charts.compare) charts.compare.destroy();
            return;
        }
        const zonePlugin = {
            id: 'compareZones',
            beforeDraw(chart) {
                const { ctx, chartArea, scales } = chart;
                if (!chartArea || !scales.x) return;
                ctx.save();
                dayZones.forEach(zone => {
                    if (zone.start < 0 || zone.end < zone.start) return;
                    const xStart = scales.x.getPixelForValue(zone.start);
                    const xEnd = scales.x.getPixelForValue(zone.end);
                    const left = Math.min(xStart, xEnd);
                    const width = Math.abs(xEnd - xStart);
                    const shade = zone.zoneIdx % 2 === 0 ? 'rgba(255,165,0,0.08)' : 'rgba(255,140,0,0.06)';
                    ctx.fillStyle = shade;
                    ctx.fillRect(left, chartArea.top, Math.max(width, 1), chartArea.bottom - chartArea.top);
                });
                ctx.restore();
            }
        };
        const gapDetailPlugin = {
            id: 'compareGapDetail',
            afterDatasetsDraw(chart) {
                const { ctx, scales } = chart;
                const yScale = scales.y;
                const xScale = scales.x;
                if (!yScale || !xScale) return;
                const ds = chart.data.datasets || [];
                for (let i = 0; i < ds.length - 1; i += 2) {
                    const bt = ds[i]?.data || [];
                    const live = ds[i + 1]?.data || [];
                    const maxLen = Math.min(bt.length, live.length);
                    for (let idx = 0; idx < maxLen - 1; idx += 1) {
                        const bt0 = bt[idx]; const bt1 = bt[idx + 1];
                        const lv0 = live[idx]; const lv1 = live[idx + 1];
                        if (bt0 === null || bt1 === null || lv0 === null || lv1 === null) continue;
                        const x0 = xScale.getPixelForValue(idx);
                        const x1 = xScale.getPixelForValue(idx + 1);
                        const yBt0 = yScale.getPixelForValue(bt0);
                        const yBt1 = yScale.getPixelForValue(bt1);
                        const yLv0 = yScale.getPixelForValue(lv0);
                        const yLv1 = yScale.getPixelForValue(lv1);
                        const avgGap = ((lv0 - bt0) + (lv1 - bt1)) / 2;
                        const intensity = Math.min(0.42, 0.08 + (Math.abs(avgGap) / 7000));
                        // Orange family, brighter when live outperforms, deeper when underperforming.
                        const fill = avgGap >= 0
                            ? `rgba(255, 176, 32, ${intensity})`
                            : `rgba(255, 116, 16, ${Math.min(0.48, intensity + 0.04)})`;
                        ctx.save();
                        ctx.beginPath();
                        ctx.moveTo(x0, yBt0);
                        ctx.lineTo(x1, yBt1);
                        ctx.lineTo(x1, yLv1);
                        ctx.lineTo(x0, yLv0);
                        ctx.closePath();
                        ctx.fillStyle = fill;
                        ctx.fill();
                        ctx.restore();
                    }
                }
            }
        };

        if (charts.compare) charts.compare.destroy();
        charts.compare = new Chart(document.getElementById('compareChart'), {
            type: 'line',
            data: { labels, datasets },
            plugins: [zonePlugin, gapDetailPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        grid: { color: 'rgba(255,255,255,0.03)' },
                        ticks: {
                            autoSkip: false,
                            maxRotation: 0,
                            color: 'rgba(226,232,240,0.7)',
                            callback(value) {
                                const label = String(labels[value] || '');
                                if (!label.includes(':')) return '';
                                const [dayPart, tsPart] = label.split(':');
                                return tsPart === String((dayTsMap.get(Number(dayPart.slice(1))) || [])[0]) ? `${dayPart}` : '';
                            }
                        }
                    },
                    y: { grid: { color: 'rgba(255,255,255,0.03)' } }
                },
                interaction: { mode: 'nearest', intersect: false },
                plugins: {
                    legend: { labels: { color: '#e2e8f0', boxWidth: 12 } },
                    zoom: {
                        pan: {
                            enabled: true,
                            mode: 'x'
                        },
                        zoom: {
                            wheel: { enabled: true },
                            pinch: { enabled: true },
                            mode: 'x'
                        }
                    }
                }
            }
        });

        summaryRows.sort((a, b) => b.delta - a.delta);
        summaryRows.forEach(row => {
            compareTableBody.innerHTML += `<tr><td><b>${row.trader}</b></td><td>${Math.round(row.btFinal).toLocaleString()}</td><td>${Math.round(row.liveFinal).toLocaleString()}</td><td style="color:${row.delta >= 0 ? 'var(--accent)' : 'var(--danger)'}">${Math.round(row.delta).toLocaleString()}</td><td>${row.commonTicks}</td><td>${row.coverage}%</td></tr>`;
        });
        if (compareNote) compareNote.textContent = `Round ${round}: ${SOURCE_LABELS[compareSources.a] || 'A'} plotted across ${sourceADays.length} day zones; ${SOURCE_LABELS[compareSources.b] || 'B'} is overlaid on matching day zones.`;
    }

    function renderPerformance() {
        const dataStore = getDataStore();
        const datasets = []; const tbody = document.querySelector('#leaderboardTable tbody'); tbody.innerHTML = '';
        const metricRows = [];
        const isTotalView = currentFilters.day === 'total';
        const traderDayMap = new Map();
        if (isTotalView) {
            Object.values(dataStore)
                .filter(r => r.round === currentFilters.round)
                .forEach(r => {
                    if (!traderDayMap.has(r.trader)) traderDayMap.set(r.trader, new Set());
                    traderDayMap.get(r.trader).add(r.day);
                });
        }
        const roundDays = isTotalView
            ? [...new Set(Object.values(dataStore).filter(r => r.round === currentFilters.round).map(r => r.day))].sort((a, b) => a - b)
            : [];
        const dayTsMap = new Map();
        const perfLabels = [];
        const perfIndexByDayTs = new Map();
        const perfDayZones = [];
        if (isTotalView) {
            roundDays.forEach(day => {
                const tsSet = new Set();
                Object.values(dataStore)
                    .filter(r => r.round === currentFilters.round && r.day === day)
                    .forEach(r => (r.history || []).forEach(h => tsSet.add(h.ts)));
                dayTsMap.set(day, [...tsSet].sort((a, b) => a - b));
            });
            roundDays.forEach((day, zoneIdx) => {
                const start = perfLabels.length;
                (dayTsMap.get(day) || []).forEach(ts => {
                    perfIndexByDayTs.set(`${day}:${ts}`, perfLabels.length);
                    perfLabels.push(`D${day}:${ts}`);
                });
                const end = perfLabels.length - 1;
                perfDayZones.push({ day, start, end, zoneIdx });
            });
        }
        selectedIds.forEach((id) => {
            const r = dataStore[id];
            const color = colorForTraderName(r.trader);
            const equityCurve = buildEquityCurve(r.history);
            const mdd = calcMDD(equityCurve);
            const ratio = (r.final_pnl / (Math.abs(mdd) || 1)).toFixed(2);
            const returns = calcReturns(equityCurve);
            const sharpe = calcSharpe(returns);
            const greenTicks = returns.length ? Math.round((returns.filter(v => v > 0).length / returns.length) * 100) : 0;
            const readiness = Math.min(100, Math.max(0, Math.round(((Number(ratio) * 0.6) + (Math.max(-2, Math.min(2, sharpe)) + 2) * 10 + (greenTicks / 5)))));
            const selection = evaluateSelectionScore(r, mdd, sharpe, greenTicks, Number(ratio));
            if (isTotalView) {
                const series = new Array(perfLabels.length).fill(null);
                equityCurve.forEach(h => {
                    const idx = perfIndexByDayTs.get(`${r.day}:${h.ts}`);
                    if (idx !== undefined) series[idx] = h.pnl;
                });
                datasets.push({ label: `${r.trader} (D${r.day})`, data: series, borderColor: color, borderWidth: 2, pointRadius: 1.4, pointHoverRadius: 4, spanGaps: true });
            } else {
                datasets.push({ label: r.trader, data: equityCurve.map(h => h.pnl), borderColor: color, borderWidth: 2, pointRadius: 1.4, pointHoverRadius: 4 });
            }
            metricRows.push({ trader: r.trader, pnl: r.final_pnl, mdd, sharpe, greenTicks, readiness, ratio: Number(ratio), color, id, selectionScore: selection.score, statusLabel: selection.statusLabel, statusRank: selection.statusRank, statusReason: selection.reason });
        });
        const headers = document.querySelectorAll('#leaderboardTable thead th');
        if (isTotalView) {
            headers.forEach(th => { th.style.display = ''; });
            const byTrader = new Map();
            metricRows.forEach(row => {
                const curr = byTrader.get(row.trader) || {
                    trader: row.trader,
                    color: row.color,
                    pnl: 0,
                    mdd: 0,
                    sharpeVals: [],
                    greenTicksVals: [],
                    selectionVals: [],
                    readinessVals: [],
                    statusWorstRank: 2,
                    reasons: [],
                };
                curr.pnl += Number(row.pnl || 0);
                curr.mdd += Number(row.mdd || 0); // aggregate drawdown across day-runs
                curr.sharpeVals.push(Number(row.sharpe || 0));
                curr.greenTicksVals.push(Number(row.greenTicks || 0));
                curr.selectionVals.push(Number(row.selectionScore || 0));
                curr.readinessVals.push(Number(row.readiness || 0));
                curr.statusWorstRank = Math.min(curr.statusWorstRank, Number(row.statusRank || 0));
                if (row.statusReason) curr.reasons.push(row.statusReason);
                byTrader.set(row.trader, curr);
            });
            const aggRows = [...byTrader.values()].map(r => {
                const avg = arr => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0);
                const sharpe = avg(r.sharpeVals);
                const greenTicks = Math.round(avg(r.greenTicksVals));
                const selectionScore = Math.round(avg(r.selectionVals));
                const readiness = Math.round(avg(r.readinessVals));
                const ratio = Number((r.pnl / (Math.abs(r.mdd) || 1)).toFixed(2));
                const statusLabel = r.statusWorstRank >= 2 ? 'GREEN' : (r.statusWorstRank === 1 ? 'AMBER' : 'RED');
                const statusReason = r.reasons[0] || 'Aggregated from day runs';
                return {
                    trader: r.trader,
                    color: r.color,
                    pnl: r.pnl,
                    mdd: r.mdd,
                    sharpe,
                    greenTicks,
                    selectionScore,
                    readiness,
                    ratio,
                    statusLabel,
                    statusReason,
                };
            });
            aggRows.sort((a, b) => {
                const delta = (a[sortMetric] || 0) - (b[sortMetric] || 0);
                return sortDirection === 'desc' ? -delta : delta;
            });
            aggRows.forEach(row => {
                const statusColor = row.statusLabel === 'GREEN' ? 'var(--accent)' : row.statusLabel === 'AMBER' ? 'var(--warning)' : 'var(--danger)';
                const whyText = row.statusReason.length > 42 ? `${row.statusReason.slice(0, 42)}...` : row.statusReason;
                tbody.innerHTML += `<tr><td style="color:${row.color}; font-weight:700;">● ${row.trader}</td><td style="color:${row.pnl > 0 ? 'var(--accent)' : 'var(--danger)'}">${Math.round(row.pnl).toLocaleString()}</td><td style="color:var(--danger)">${Math.round(row.mdd).toLocaleString()}</td><td>${row.ratio.toFixed(2)}x</td><td>${row.sharpe.toFixed(2)}</td><td>${row.greenTicks}%</td><td><b>${row.selectionScore}</b></td><td title="${row.statusReason}" style="color:${statusColor}; font-weight:700;">${row.statusLabel}</td><td title="${row.statusReason}" style="color:var(--text-dim);">${whyText}</td><td><div style="height:4px; width:100px; background:#111;"><div style="height:100%; width:${row.readiness}%; background:var(--accent);"></div></div></td></tr>`;
            });
        } else {
            headers.forEach(th => { th.style.display = ''; });
            metricRows.sort((a, b) => {
                const delta = (a[sortMetric] || 0) - (b[sortMetric] || 0);
                return sortDirection === 'desc' ? -delta : delta;
            });
            metricRows.forEach(row => {
                const statusColor = row.statusLabel === 'GREEN' ? 'var(--accent)' : row.statusLabel === 'AMBER' ? 'var(--warning)' : 'var(--danger)';
                const whyText = row.statusReason.length > 42 ? `${row.statusReason.slice(0, 42)}...` : row.statusReason;
                tbody.innerHTML += `<tr><td style="color:${row.color}; font-weight:700;">● ${row.trader}</td><td style="color:${row.pnl > 0 ? 'var(--accent)' : 'var(--danger)'}">${Math.round(row.pnl).toLocaleString()}</td><td style="color:var(--danger)">${Math.round(row.mdd).toLocaleString()}</td><td>${row.ratio.toFixed(2)}x</td><td>${row.sharpe.toFixed(2)}</td><td>${row.greenTicks}%</td><td><b>${row.selectionScore}</b></td><td title="${row.statusReason}" style="color:${statusColor}; font-weight:700;">${row.statusLabel}</td><td title="${row.statusReason}" style="color:var(--text-dim);">${whyText}</td><td><div style="height:4px; width:100px; background:#111;"><div style="height:100%; width:${row.readiness}%; background:var(--accent);"></div></div></td></tr>`;
            });
        }
        if (charts.perf) charts.perf.destroy();
        const labels = isTotalView
            ? perfLabels
            : (selectedIds.length > 0 ? buildEquityCurve(dataStore[selectedIds[0]].history).map(h => h.ts) : []);
        const perfZonePlugin = {
            id: 'perfTotalZones',
            beforeDraw(chart) {
                if (!isTotalView) return;
                const { ctx, chartArea, scales } = chart;
                if (!chartArea || !scales.x) return;
                ctx.save();
                perfDayZones.forEach(zone => {
                    if (zone.start < 0 || zone.end < zone.start) return;
                    const xStart = scales.x.getPixelForValue(zone.start);
                    const xEnd = scales.x.getPixelForValue(zone.end);
                    const left = Math.min(xStart, xEnd);
                    const width = Math.abs(xEnd - xStart);
                    const shade = zone.zoneIdx % 2 === 0 ? 'rgba(255,165,0,0.08)' : 'rgba(255,140,0,0.06)';
                    ctx.fillStyle = shade;
                    ctx.fillRect(left, chartArea.top, Math.max(width, 1), chartArea.bottom - chartArea.top);
                });
                ctx.restore();
            }
        };
        charts.perf = new Chart(document.getElementById('performanceChart'), {
            type: 'line',
            data: { labels, datasets },
            plugins: isTotalView ? [perfZonePlugin] : [],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: isTotalView
                        ? {
                            grid: { color: 'rgba(255,255,255,0.03)' },
                            ticks: {
                                autoSkip: false,
                                maxRotation: 0,
                                color: 'rgba(226,232,240,0.7)',
                                callback(value) {
                                    const label = String(labels[value] || '');
                                    if (!label.includes(':')) return '';
                                    const [dayPart, tsPart] = label.split(':');
                                    return tsPart === String((dayTsMap.get(Number(dayPart.slice(1))) || [])[0]) ? dayPart : '';
                                }
                            }
                        }
                        : { display: false },
                    y: { grid: { color: 'rgba(255,255,255,0.03)' } }
                },
                interaction: { mode: 'nearest', intersect: false },
                plugins: { legend: { display: false } }
            }
        });
        const quickStats = document.getElementById('quickStats');
        if (!metricRows.length) {
            quickStats.innerHTML = '';
            return;
        }
        const bestPnl = metricRows.reduce((a, b) => (a.pnl > b.pnl ? a : b));
        const safest = metricRows.reduce((a, b) => (Math.abs(a.mdd) < Math.abs(b.mdd) ? a : b));
        const bestSharpe = metricRows.reduce((a, b) => (a.sharpe > b.sharpe ? a : b));
        const avgGreen = Math.round(metricRows.reduce((acc, row) => acc + row.greenTicks, 0) / metricRows.length);
        quickStats.innerHTML = `
            <div class="metric-tile"><div class="metric-label">Top PnL</div><div class="metric-value">${Math.round(bestPnl.pnl).toLocaleString()} (${bestPnl.trader})</div></div>
            <div class="metric-tile"><div class="metric-label">Best Sharpe*</div><div class="metric-value">${bestSharpe.sharpe.toFixed(2)} (${bestSharpe.trader})</div></div>
            <div class="metric-tile"><div class="metric-label">Lowest Drawdown</div><div class="metric-value">${Math.round(Math.abs(safest.mdd)).toLocaleString()} (${safest.trader})</div></div>
            <div class="metric-tile"><div class="metric-label">Avg Green Ticks</div><div class="metric-value">${avgGreen}%</div></div>
        `;
    }

    function renderAttribution() {
        const dataStore = getDataStore();
        if (selectedIds.length === 0) {
            if (charts.attr) {
                charts.attr.destroy();
                charts.attr = null;
            }
            const tbody = document.querySelector('#assetLeaderboard tbody');
            if (tbody) tbody.innerHTML = '';
            return;
        }
        // Deduplicate same trader labels by keeping the strongest selected run.
        const uniqueByTrader = new Map();
        selectedIds.forEach(id => {
            const run = dataStore[id];
            if (!run) return;
            const prev = uniqueByTrader.get(run.trader);
            if (!prev || (run.final_pnl || 0) > (prev.final_pnl || 0)) uniqueByTrader.set(run.trader, run);
        });
        const attributionRuns = [...uniqueByTrader.values()];
        const assets = [...new Set(attributionRuns.flatMap(r => Object.keys(r.final_pnl_by_product || {})))].sort();
        const datasets = attributionRuns.map((r) => {
            return { label: r.trader, data: assets.map(a => r.final_pnl_by_product?.[a] || 0), backgroundColor: colorForTraderName(r.trader), borderRadius: 4 };
        });
        if (charts.attr) charts.attr.destroy();
        charts.attr = new Chart(document.getElementById('attributionChart'), { type: 'bar', data: { labels: assets, datasets }, options: { responsive: true, maintainAspectRatio: false, scales: { y: { grid: { color: 'rgba(255,255,255,0.03)' } } } } });
        const tbody = document.querySelector('#assetLeaderboard tbody'); tbody.innerHTML = '';
        const rows = assets.map(a => {
            const scores = attributionRuns.map(r => ({ name: r.trader, val: r.final_pnl_by_product?.[a] || 0 }));
            scores.sort((x,y) => y.val - x.val);
            const spread = scores[0].val - scores[scores.length - 1].val;
            return { asset: a, best: scores[0].name, max: scores[0].val, min: scores[scores.length-1].val, spread };
        });
        rows.sort((a, b) => {
            const av = assetSortMetric === 'asset' ? a.asset : a[assetSortMetric];
            const bv = assetSortMetric === 'asset' ? b.asset : b[assetSortMetric];
            const delta = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
            return assetSortDirection === 'desc' ? -delta : delta;
        });
        rows.forEach(row => {
            tbody.innerHTML += `<tr><td><b>${row.asset}</b></td><td>${row.best}</td><td style="color:var(--accent)">${Math.round(row.max).toLocaleString()}</td><td style="color:var(--danger)">${Math.round(row.min).toLocaleString()}</td><td>${Math.round(row.spread).toLocaleString()}</td></tr>`;
        });
    }

    function renderStability() {
        const dataStore = getDataStore();
        const tbody = document.querySelector('#stabilityTable tbody'); tbody.innerHTML = '';
        const assetTbody = document.querySelector('#assetStabilityTable tbody'); assetTbody.innerHTML = '';
        const roundRuns = Object.values(dataStore).filter(r => r.round === currentFilters.round);
        const roundDays = [...new Set(roundRuns.map(r => r.day))].sort((a, b) => a - b);
        const displayDays = roundDays.slice(0, 3);
        const fallbackDays = [0, 1, 2];
        while (displayDays.length < 3) displayDays.push(fallbackDays[displayDays.length]);
        for (let i = 0; i < 3; i += 1) {
            const stHeader = document.getElementById(`stability-day-col-${i}`);
            const hmHeader = document.getElementById(`heatmap-day-col-${i}`);
            if (stHeader) stHeader.childNodes[0].textContent = `D${displayDays[i]} PNL `;
            if (hmHeader) hmHeader.childNodes[0].textContent = `D${displayDays[i]} `;
        }
        const traders = [...new Set(Object.values(dataStore).map(r => r.trader))];
        const stabilityRows = [];
        traders.forEach(t => {
            const runs = Object.values(dataStore).filter(r => r.trader === t && r.round === currentFilters.round);
            if (runs.length < 2) return;
            const d0 = runs.find(r => r.day === displayDays[0])?.final_pnl || 0;
            const d1 = runs.find(r => r.day === displayDays[1])?.final_pnl || 0;
            const d2 = runs.find(r => r.day === displayDays[2])?.final_pnl || 0;
            const avg = (d0 + d1 + d2) / 3;
            const range = Math.max(d0, d1, d2) - Math.min(d0, d1, d2);
            const consistency = Math.max(0, 100 - Math.round((Math.abs(range) / (Math.abs(avg) + 1)) * 100));
            stabilityRows.push({ trader: t, d0, d1, d2, avg, range, consistency });
        });
        stabilityRows.sort((a, b) => {
            const av = stabilitySortMetric === 'trader' ? a.trader : a[stabilitySortMetric];
            const bv = stabilitySortMetric === 'trader' ? b.trader : b[stabilitySortMetric];
            const delta = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
            return stabilitySortDirection === 'desc' ? -delta : delta;
        });
        stabilityRows.forEach(row => {
            tbody.innerHTML += `<tr><td><b>${row.trader}</b></td><td>${Math.round(row.d0).toLocaleString()}</td><td>${Math.round(row.d1).toLocaleString()}</td><td>${Math.round(row.d2).toLocaleString()}</td><td>${Math.round(row.avg).toLocaleString()}</td><td style="color:${row.range > 50000 ? 'var(--danger)' : 'var(--warning)'}">${Math.round(row.range).toLocaleString()}</td><td style="color:${row.consistency < 40 ? 'var(--danger)' : 'var(--accent)'}">${row.consistency}%</td></tr>`;
        });
        const assets = [...new Set(roundRuns.flatMap(r => Object.keys(r.final_pnl_by_product || {})))].sort();
        const heatRows = assets.map(asset => {
            const dayVals = displayDays.map(day => {
                const vals = roundRuns.filter(r => r.day === day).map(r => r.final_pnl_by_product?.[asset] || 0);
                if (!vals.length) return 0;
                return vals.reduce((a, b) => a + b, 0) / vals.length;
            });
            const spread = Math.max(...dayVals) - Math.min(...dayVals);
            return { asset, d0: dayVals[0], d1: dayVals[1], d2: dayVals[2], spread };
        });
        heatRows.sort((a, b) => {
            const av = heatmapSortMetric === 'asset' ? a.asset : a[heatmapSortMetric];
            const bv = heatmapSortMetric === 'asset' ? b.asset : b[heatmapSortMetric];
            const delta = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
            return heatmapSortDirection === 'desc' ? -delta : delta;
        });
        heatRows.forEach(row => {
            const cell = v => {
                const alpha = Math.min(0.7, Math.abs(v) / 12000);
                const base = v >= 0 ? `rgba(0,255,157,${alpha})` : `rgba(255,71,87,${alpha})`;
                return `<td class="heat-cell" style="background:${base};">${Math.round(v).toLocaleString()}</td>`;
            };
            assetTbody.innerHTML += `<tr><td><b>${row.asset}</b></td>${cell(row.d0)}${cell(row.d1)}${cell(row.d2)}<td>${Math.round(row.spread).toLocaleString()}</td></tr>`;
        });
    }
    init();
