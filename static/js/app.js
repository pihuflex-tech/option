/* ==========================================================================
   NIFTY 50 OPTION TERMINAL & PAPER TRADER - FRONTEND CONTROLLER
   - High-Frequency Steady DOM (Zero Blinking / No Flicker)
   - Target (Take-Profit) & Stop-Loss Functionality with Auto Square-Off
   - Clear Order History Modal & Backend Sync
   - One-Click Trade History CSV Export
   ========================================================================== */

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
let ws = null;
let expInitialized = false;
let activeOrder = null;
let orderSubmitting = false;
let currentCash = 1000000.0;
let pendingSquareOff = null;
let reconnectTimer = null;
let activeTab = "positions";
let activeSLTargetSymbol = null;

// ===== Toast Notification System =====
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    const icons = {
        success: "✓",
        error: "✕",
        info: "ℹ",
        warning: "⚠️"
    };

    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || "ℹ"}</span>
        <span style="flex:1;">${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("toast-hide");
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}

// ===== WebSocket Connection Management =====
function connectWebSocket() {
    if (ws) {
        try { ws.close(); } catch (e) {}
    }

    const dot = document.getElementById("conn-dot");
    const metaTxt = document.getElementById("meta-txt");

    ws = new WebSocket(`${wsProtocol}//${location.host}/ws`);

    ws.onopen = function() {
        if (dot) dot.classList.remove("offline");
        if (metaTxt) metaTxt.innerHTML = "<span>⚡ Link connected. Receiving live market feed...</span>";
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
    };

    ws.onmessage = function(ev) {
        try {
            handleSnapshot(ev.data);
        } catch (err) {
            console.error("Error processing snapshot:", err);
        }
    };

    ws.onclose = function() {
        if (dot) dot.classList.add("offline");
        if (metaTxt) metaTxt.innerHTML = "<span>⚠️ Link offline. Reconnecting in 2s...</span>";
        
        if (!reconnectTimer) {
            reconnectTimer = setTimeout(() => {
                reconnectTimer = null;
                connectWebSocket();
            }, 2000);
        }
    };

    ws.onerror = function() {
        if (dot) dot.classList.add("offline");
    };
}

// Start WebSocket connection
connectWebSocket();

// Expiry contract switcher
function onExpChange(idx) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ "exp_idx": idx }));
    }
}

// ===== NO-BLINKING OPTION CHAIN MATRIX UPDATER =====
// Patches existing DOM elements in-place to completely remove table flickering
function updateMatrixTable(matrix, atmStrike) {
    const container = document.getElementById("rows-target");
    if (!container || !matrix) return;

    const existingRows = container.querySelectorAll("tr[data-strike]");
    
    // Check if table needs full initialization or strike count/strikes changed
    let needsRebuild = existingRows.length !== matrix.length;
    if (!needsRebuild) {
        for (let i = 0; i < matrix.length; i++) {
            if (existingRows[i].getAttribute("data-strike") !== String(matrix[i].strike)) {
                needsRebuild = true;
                break;
            }
        }
    }

    if (needsRebuild) {
        let buffer = "";
        for (let r of matrix) {
            const isAtm = r.is_atm;
            const atmClass = isAtm ? "strike-cell atm" : "strike-cell";
            const atmBadge = isAtm ? `<span class="atm-badge">ATM</span>` : "";
            const isCeItm = r.strike < atmStrike;
            const isPeItm = r.strike > atmStrike;
            const ceRowClass = isCeItm ? "ce-val itm-ce" : "ce-val";
            const peRowClass = isPeItm ? "pe-val itm-pe" : "pe-val";

            buffer += `<tr data-strike="${r.strike}">
                <td class="${ceRowClass}" data-col="ce-td">
                    <span class="clickable-price" data-col="ce-btn">
                        <span class="ce-ltp-val">₹ ${r.ce_ltp.toFixed(2)}</span>
                        <span class="trade-tag">+ BUY</span>
                    </span>
                </td>
                <td class="sub-code ce-sym" title="${r.ce_sym}">${r.ce_sym}</td>
                <td class="${atmClass}" data-col="strike-td">
                    <span class="atm-badge-container">${atmBadge}</span>
                    <span class="strike-num">${r.strike}</span>
                </td>
                <td class="sub-code pe-sym" title="${r.pe_sym}">${r.pe_sym}</td>
                <td class="${peRowClass}" data-col="pe-td">
                    <span class="clickable-price" data-col="pe-btn">
                        <span class="trade-tag">+ BUY</span>
                        <span class="pe-ltp-val">₹ ${r.pe_ltp.toFixed(2)}</span>
                    </span>
                </td>
            </tr>`;
        }
        container.innerHTML = buffer;
    }

    // Steady in-place DOM updates (ZERO BLINKING / ZERO FLICKER)
    const rows = container.querySelectorAll("tr[data-strike]");
    for (let i = 0; i < matrix.length && i < rows.length; i++) {
        const r = matrix[i];
        const row = rows[i];

        // 1. CE Side
        const ceLtpVal = row.querySelector(".ce-ltp-val");
        const ceBtn = row.querySelector("[data-col='ce-btn']");
        const ceTd = row.querySelector("[data-col='ce-td']");
        const ceFormatted = `₹ ${r.ce_ltp.toFixed(2)}`;
        if (ceLtpVal && ceLtpVal.textContent !== ceFormatted) {
            ceLtpVal.textContent = ceFormatted;
        }
        if (ceBtn) {
            ceBtn.onclick = () => openTradeModal(r.ce_sym, r.ce_token, r.ce_ltp, r.ce_lotsize);
        }
        const isCeItm = r.strike < atmStrike;
        const targetCeClass = isCeItm ? "ce-val itm-ce" : "ce-val";
        if (ceTd && ceTd.className !== targetCeClass) {
            ceTd.className = targetCeClass;
        }

        // 2. PE Side
        const peLtpVal = row.querySelector(".pe-ltp-val");
        const peBtn = row.querySelector("[data-col='pe-btn']");
        const peTd = row.querySelector("[data-col='pe-td']");
        const peFormatted = `₹ ${r.pe_ltp.toFixed(2)}`;
        if (peLtpVal && peLtpVal.textContent !== peFormatted) {
            peLtpVal.textContent = peFormatted;
        }
        if (peBtn) {
            peBtn.onclick = () => openTradeModal(r.pe_sym, r.pe_token, r.pe_ltp, r.pe_lotsize);
        }
        const isPeItm = r.strike > atmStrike;
        const targetPeClass = isPeItm ? "pe-val itm-pe" : "pe-val";
        if (peTd && peTd.className !== targetPeClass) {
            peTd.className = targetPeClass;
        }

        // 3. ATM / Strike Cell
        const strikeTd = row.querySelector("[data-col='strike-td']");
        const isAtm = r.is_atm;
        const targetAtmClass = isAtm ? "strike-cell atm" : "strike-cell";
        if (strikeTd && strikeTd.className !== targetAtmClass) {
            strikeTd.className = targetAtmClass;
        }
        const badgeCont = row.querySelector(".atm-badge-container");
        if (badgeCont) {
            const expectedBadge = isAtm ? `<span class="atm-badge">ATM</span>` : "";
            if (badgeCont.innerHTML !== expectedBadge) {
                badgeCont.innerHTML = expectedBadge;
            }
        }
    }
}

// ===== SNAPSHOT INGESTION & UI UPDATES =====
function handleSnapshot(raw) {
    const d = JSON.parse(raw);
    if (d.error) {
        const metaTxt = document.getElementById("meta-txt");
        if (metaTxt) metaTxt.innerHTML = `<span style="color:#f43f5e;">⚠️ ${d.error}</span>`;
        const container = document.getElementById("rows-target");
        if (container) container.innerHTML = `<tr><td colspan="5" style="padding:40px; color:#f43f5e; text-align:center;">${d.error}</td></tr>`;
        return;
    }

    // Automated SL / Target Alerts
    if (d.alerts && d.alerts.length > 0) {
        for (let alertItem of d.alerts) {
            if (alertItem.type === "TARGET_HIT") {
                showToast(`🎯 TARGET HIT: ${alertItem.symbol} auto-closed @ ₹${Number(alertItem.price).toFixed(2)} (Target: ₹${Number(alertItem.target).toFixed(2)})`, "success");
            } else if (alertItem.type === "STOP_LOSS_HIT") {
                showToast(`🛑 STOP-LOSS HIT: ${alertItem.symbol} auto-closed @ ₹${Number(alertItem.price).toFixed(2)} (SL: ₹${Number(alertItem.stop_loss).toFixed(2)})`, "warning");
            }
        }
        if (activeTab === "orders") {
            fetchOrderHistory();
        }
    }

    if (!expInitialized && d.expiries) {
        const s = document.getElementById("exp-select");
        if (s) {
            s.innerHTML = d.expiries.map((x, i) => `<option value="${i}">${x}</option>`).join("");
            expInitialized = true;
        }
    }

    // Spot Price
    const spotElem = document.getElementById("spot-val");
    if (spotElem) spotElem.innerText = `₹ ${d.spot.toFixed(2)}`;
    
    // Status Bar
    const metaTxt = document.getElementById("meta-txt");
    if (metaTxt) {
        metaTxt.innerHTML = `<span><strong>Expiry:</strong> ${d.expiry}</span> • <span><strong>ATM:</strong> ${d.atm}</span> • <span><strong>Sync:</strong> ${new Date().toLocaleTimeString()}</span>`;
    }

    // Portfolio updates
    currentCash = d.wallet.cash || 0.0;
    const cashElem = document.getElementById("port-cash");
    if (cashElem) cashElem.innerText = `₹ ${currentCash.toLocaleString("en-IN", {minimumFractionDigits:2, maximumFractionDigits:2})}`;
    
    const nwElem = document.getElementById("port-networth");
    if (nwElem) nwElem.innerText = `₹ ${d.wallet.net_worth.toLocaleString("en-IN", {minimumFractionDigits:2, maximumFractionDigits:2})}`;
    
    const pnlElem = document.getElementById("port-pnl");
    if (pnlElem) {
        const pnl = d.wallet.total_pnl || 0.0;
        pnlElem.innerText = `₹ ${pnl >= 0 ? '+' : ''}${pnl.toLocaleString("en-IN", {minimumFractionDigits:2, maximumFractionDigits:2})}`;
        pnlElem.style.color = pnl >= 0 ? "var(--ce-green)" : "var(--pe-red)";
    }

    const posCount = (d.wallet.positions && d.wallet.positions.length) || 0;
    const posCountElem = document.getElementById("port-pos-count");
    if (posCountElem) posCountElem.innerText = `${posCount} Active`;
    
    const badgeElem = document.getElementById("pos-count-badge");
    if (badgeElem) badgeElem.innerText = String(posCount);

    // Update Matrix Table without blinking
    if (d.matrix) {
        updateMatrixTable(d.matrix, d.atm);
    }

    // Active Positions Table Update
    updatePositionsTable(d.wallet.positions || []);
}

// ===== POSITIONS TABLE RENDERER =====
function updatePositionsTable(positions) {
    const posContainer = document.getElementById("pos-target");
    if (!posContainer) return;

    if (!positions || positions.length === 0) {
        posContainer.innerHTML = `<tr><td colspan="8" style="padding:24px; text-align:center; color:#64748b;">No open positions</td></tr>`;
        return;
    }

    let posHtml = "";
    for (let p of positions) {
        const pnlColor = p.pnl >= 0 ? "var(--ce-green)" : "var(--pe-red)";
        
        const tgtBadge = p.target && p.target > 0 
            ? `<span class="badge-target">🎯 ₹${Number(p.target).toFixed(2)}</span>`
            : `<span class="badge-notset">--</span>`;
            
        const slBadge = p.stop_loss && p.stop_loss > 0 
            ? `<span class="badge-sl">🛑 ₹${Number(p.stop_loss).toFixed(2)}</span>`
            : `<span class="badge-notset">--</span>`;

        posHtml += `<tr>
            <td style="color:#38bdf8; font-weight:600; font-family:var(--font-sans);">${p.symbol}</td>
            <td>${p.qty}</td>
            <td>₹ ${p.avg_price.toFixed(2)}</td>
            <td style="font-weight:600;">₹ ${p.ltp.toFixed(2)}</td>
            <td>${tgtBadge}</td>
            <td>${slBadge}</td>
            <td style="color:${pnlColor}; font-weight:700;">
                ₹ ${p.pnl >= 0 ? '+' : ''}${p.pnl.toFixed(2)} (${p.pnl_pct.toFixed(2)}%)
            </td>
            <td style="text-align:center; display:flex; gap:6px; justify-content:center;">
                <button class="btn-sltarget" onclick="openSLTargetModal('${p.symbol}', ${p.target || 'null'}, ${p.stop_loss || 'null'}, ${p.ltp}, ${p.avg_price})">🎯 SL/Tgt</button>
                <button class="btn-exit" onclick="squareOff('${p.symbol}', '${p.token}', ${p.qty}, ${p.lotsize})">Square Off</button>
            </td>
        </tr>`;
    }
    posContainer.innerHTML = posHtml;
}

// ===== QUICK TRADE MODAL & TARGET / STOP-LOSS LOGIC =====
function openTradeModal(sym, token, price, lotsize) {
    if (!sym || sym === "--" || !token) {
        showToast("Invalid option contract selected.", "warning");
        return;
    }
    
    activeOrder = { 
        sym: String(sym), 
        token: String(token), 
        price: parseFloat(price) || 0.0, 
        lotsize: parseInt(lotsize) || 50 
    };
    
    const isCall = activeOrder.sym.endsWith("CE");
    const contractType = isCall ? "CALL (CE)" : "PUT (PE)";
    
    document.getElementById("m-title").innerText = `Place Paper Order — BUY ${contractType}`;
    document.getElementById("m-sym").value = activeOrder.sym;
    document.getElementById("m-price").value = `₹ ${activeOrder.price.toFixed(2)}`;
    document.getElementById("m-lotsize-txt").innerText = activeOrder.lotsize;
    document.getElementById("m-lots").value = 1;
    
    // Reset Target & SL inputs
    document.getElementById("m-target").value = "";
    document.getElementById("m-sl").value = "";
    const rrStrip = document.getElementById("m-rr-strip");
    if (rrStrip) rrStrip.style.display = "none";
    
    calcTotal();
    calcRiskReward();
    document.getElementById("order-modal").style.display = "flex";
}

function quickSetLots(lots) {
    const input = document.getElementById("m-lots");
    if (input) {
        input.value = Math.max(1, parseInt(lots) || 1);
        calcTotal();
        calcRiskReward();
    }
}

function quickAddLots(add) {
    const input = document.getElementById("m-lots");
    if (input) {
        const cur = parseInt(input.value) || 1;
        input.value = Math.max(1, cur + add);
        calcTotal();
        calcRiskReward();
    }
}

// Quick Target helpers
function quickAddTarget(pts) {
    if (!activeOrder) return;
    const tgt = (activeOrder.price + pts).toFixed(2);
    document.getElementById("m-target").value = tgt;
    calcRiskReward();
}

function quickAddTargetPct(pct) {
    if (!activeOrder) return;
    const tgt = (activeOrder.price * (1 + pct / 100)).toFixed(2);
    document.getElementById("m-target").value = tgt;
    calcRiskReward();
}

function clearTargetInput() {
    document.getElementById("m-target").value = "";
    calcRiskReward();
}

// Quick SL helpers
function quickSubSL(pts) {
    if (!activeOrder) return;
    const sl = Math.max(0.05, activeOrder.price - pts).toFixed(2);
    document.getElementById("m-sl").value = sl;
    calcRiskReward();
}

function quickSubSLPct(pct) {
    if (!activeOrder) return;
    const sl = Math.max(0.05, activeOrder.price * (1 - pct / 100)).toFixed(2);
    document.getElementById("m-sl").value = sl;
    calcRiskReward();
}

function clearSLInput() {
    document.getElementById("m-sl").value = "";
    calcRiskReward();
}

// Risk:Reward & Max P&L Calculator
function calcRiskReward() {
    if (!activeOrder) return;
    const lots = parseInt(document.getElementById("m-lots").value) || 1;
    const qty = lots * activeOrder.lotsize;
    const buyPrice = activeOrder.price;
    
    const targetInput = document.getElementById("m-target");
    const slInput = document.getElementById("m-sl");
    const rrStrip = document.getElementById("m-rr-strip");
    const rrRatio = document.getElementById("m-rr-ratio");
    const maxProfit = document.getElementById("m-max-profit");
    const maxLoss = document.getElementById("m-max-loss");

    const tgtVal = parseFloat(targetInput.value);
    const slVal = parseFloat(slInput.value);

    const hasTgt = !isNaN(tgtVal) && tgtVal > buyPrice;
    const hasSl = !isNaN(slVal) && slVal < buyPrice && slVal > 0;

    if (!hasTgt && !hasSl) {
        if (rrStrip) rrStrip.style.display = "none";
        return;
    }

    if (rrStrip) rrStrip.style.display = "flex";

    if (hasTgt) {
        const profit = (tgtVal - buyPrice) * qty;
        maxProfit.innerText = `Target Profit: +₹${profit.toLocaleString("en-IN", {minimumFractionDigits:2, maximumFractionDigits:2})}`;
        maxProfit.style.display = "inline";
    } else {
        maxProfit.style.display = "none";
    }

    if (hasSl) {
        const loss = (buyPrice - slVal) * qty;
        maxLoss.innerText = `Max Risk: -₹${loss.toLocaleString("en-IN", {minimumFractionDigits:2, maximumFractionDigits:2})}`;
        maxLoss.style.display = "inline";
    } else {
        maxLoss.style.display = "none";
    }

    if (hasTgt && hasSl) {
        const profitPerUnit = tgtVal - buyPrice;
        const riskPerUnit = buyPrice - slVal;
        if (riskPerUnit > 0) {
            const ratio = (profitPerUnit / riskPerUnit).toFixed(1);
            rrRatio.innerText = `R:R 1 : ${ratio}`;
            rrRatio.style.display = "inline-block";
        } else {
            rrRatio.style.display = "none";
        }
    } else {
        rrRatio.style.display = "none";
    }
}

// Total Premium & Margin Calculation
function calcTotal() {
    if (!activeOrder) return;
    const lotsInput = document.getElementById("m-lots");
    const lots = parseInt(lotsInput.value) || 1;
    const totalQty = lots * activeOrder.lotsize;
    const total = totalQty * activeOrder.price;
    
    const summaryElem = document.getElementById("m-qty-summary");
    if (summaryElem) {
        summaryElem.innerText = `${totalQty} Qty (${lots} ${lots === 1 ? 'Lot' : 'Lots'} × ${activeOrder.lotsize})`;
    }
    
    const totalInput = document.getElementById("m-total");
    if (totalInput) {
        totalInput.value = `₹ ${total.toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    }

    // Margin warning check
    const banner = document.getElementById("m-margin-banner");
    const buyButton = document.getElementById("btn-submit-order") || document.querySelector(".btn-buy");
    if (banner) {
        if (total > currentCash) {
            banner.style.display = "flex";
            if (buyButton) buyButton.disabled = true;
        } else {
            banner.style.display = "none";
            if (buyButton && !orderSubmitting) buyButton.disabled = false;
        }
    }
}

function closeModal() {
    const modal = document.getElementById("order-modal");
    if (modal) modal.style.display = "none";
    activeOrder = null;
}

// Order Submission
async function submitOrder() {
    if (!activeOrder || orderSubmitting) return;
    const lots = parseInt(document.getElementById("m-lots").value);
    if (!Number.isInteger(lots) || lots < 1) {
        showToast("Enter a valid number of lots (minimum 1).", "warning");
        return;
    }

    const targetVal = parseFloat(document.getElementById("m-target").value) || null;
    const slVal = parseFloat(document.getElementById("m-sl").value) || null;

    if (targetVal !== null && targetVal <= activeOrder.price) {
        showToast("Target price must be greater than current entry price.", "warning");
        return;
    }
    if (slVal !== null && slVal >= activeOrder.price) {
        showToast("Stop-loss price must be lower than current entry price.", "warning");
        return;
    }

    const buyButton = document.getElementById("btn-submit-order") || document.querySelector(".btn-buy");
    orderSubmitting = true;
    if (buyButton) {
        buyButton.disabled = true;
        buyButton.innerText = "Executing Paper Trade...";
    }
    
    try {
        const payload = {
            symbol: activeOrder.sym,
            token: activeOrder.token,
            action: "BUY",
            lots: lots,
            lotsize: activeOrder.lotsize,
            price: activeOrder.price,
            target: targetVal,
            stop_loss: slVal
        };

        const res = await fetch("/api/order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok || data.status !== "success") {
            showToast(data.message || "Paper order failed.", "error");
            return;
        }
        
        let msg = `Order Executed: BUY ${activeOrder.sym}`;
        if (targetVal) msg += ` | Tgt: ₹${targetVal.toFixed(2)}`;
        if (slVal) msg += ` | SL: ₹${slVal.toFixed(2)}`;
        showToast(msg, "success");
        
        closeModal();
        if (activeTab === "orders") {
            fetchOrderHistory();
        }
    } catch (err) {
        showToast("Network error submitting paper order: " + err, "error");
    } finally {
        orderSubmitting = false;
        if (buyButton) {
            buyButton.disabled = false;
            buyButton.innerText = "BUY NOW (Paper)";
        }
    }
}

// ===== EDIT SL & TARGET MODAL (FOR RUNNING POSITIONS) =====
function openSLTargetModal(sym, target, sl, ltp, avgPrice) {
    activeSLTargetSymbol = sym;
    document.getElementById("edit-sl-sym").value = sym;
    document.getElementById("edit-sl-avg").value = `₹ ${(parseFloat(avgPrice) || 0).toFixed(2)}`;
    document.getElementById("edit-sl-ltp").value = `₹ ${(parseFloat(ltp) || 0).toFixed(2)}`;
    document.getElementById("edit-target-val").value = target && target > 0 ? target : "";
    document.getElementById("edit-sl-val").value = sl && sl > 0 ? sl : "";
    
    document.getElementById("sltarget-modal").style.display = "flex";
}

function closeSLTargetModal() {
    const modal = document.getElementById("sltarget-modal");
    if (modal) modal.style.display = "none";
    activeSLTargetSymbol = null;
}

async function submitSLTargetUpdate() {
    if (!activeSLTargetSymbol) return;
    const tgt = parseFloat(document.getElementById("edit-target-val").value) || null;
    const sl = parseFloat(document.getElementById("edit-sl-val").value) || null;

    try {
        const res = await fetch("/api/position/sl-target", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                symbol: activeSLTargetSymbol,
                target: tgt,
                stop_loss: sl
            })
        });
        const data = await res.json();
        if (!res.ok || data.status !== "success") {
            showToast(data.message || "Failed to update Target/SL.", "error");
            return;
        }

        showToast(`Target & Stop-Loss updated for ${activeSLTargetSymbol}`, "success");
        closeSLTargetModal();
    } catch (err) {
        showToast("Error updating Target/SL: " + err, "error");
    }
}

// ===== SQUARE-OFF MODAL & EXECUTION =====
function squareOff(sym, token, qty, lotsize) {
    pendingSquareOff = {
        sym: String(sym),
        token: String(token),
        qty: parseInt(qty),
        lotsize: parseInt(lotsize) || 50
    };
    
    const sqSym = document.getElementById("sq-sym");
    if (sqSym) sqSym.innerText = `${pendingSquareOff.qty} shares of ${pendingSquareOff.sym}`;
    
    const modal = document.getElementById("squareoff-modal");
    if (modal) modal.style.display = "flex";
}

function closeSquareOffModal() {
    const modal = document.getElementById("squareoff-modal");
    if (modal) modal.style.display = "none";
    pendingSquareOff = null;
}

async function confirmSquareOff() {
    if (!pendingSquareOff) return;
    const { sym, token, qty, lotsize } = pendingSquareOff;
    closeSquareOffModal();
    
    const lots = Math.max(1, Math.floor(qty / lotsize));
    const exitBtn = document.getElementById("btn-confirm-squareoff");
    if (exitBtn) exitBtn.disabled = true;
    
    try {
        const res = await fetch("/api/order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                symbol: sym,
                token: token,
                action: "SELL",
                lots: lots,
                lotsize: lotsize,
                price: 0.0
            })
        });
        const data = await res.json();
        if (!res.ok || data.status !== "success") {
            showToast(data.message || "Failed to square off position.", "error");
        } else {
            showToast(`Position squared off: SELL ${qty} ${sym}`, "success");
            if (activeTab === "orders") {
                fetchOrderHistory();
            }
        }
    } catch (err) {
        showToast("Error executing square-off: " + err, "error");
    } finally {
        if (exitBtn) exitBtn.disabled = false;
    }
}

// ===== CLEAR HISTORY MODAL & EXECUTION =====
function openClearHistoryModal() {
    const modal = document.getElementById("clear-confirm-modal");
    if (modal) modal.style.display = "flex";
}

function closeClearHistoryModal() {
    const modal = document.getElementById("clear-confirm-modal");
    if (modal) modal.style.display = "none";
}

async function confirmClearHistory() {
    closeClearHistoryModal();
    try {
        const res = await fetch("/api/orders/clear", { method: "POST" });
        const data = await res.json();
        if (!res.ok || data.status !== "success") {
            showToast(data.message || "Failed to clear trade history.", "error");
            return;
        }

        showToast(data.message || "Trade history cleared successfully.", "success");
        fetchOrderHistory();
    } catch (err) {
        showToast("Error clearing history: " + err, "error");
    }
}

// ===== DOWNLOAD TRADE HISTORY AS CSV =====
async function downloadTradeHistoryCSV() {
    try {
        const res = await fetch("/api/orders");
        const data = await res.json();
        const orders = data.orders || [];

        if (orders.length === 0) {
            showToast("No trade history available to download.", "warning");
            return;
        }

        // CSV Header row
        const headers = [
            "Order ID", "Timestamp", "Symbol", "Exchange", "Side", 
            "Quantity", "Price (INR)", "Order Type", "Status", 
            "Target (INR)", "Stop-Loss (INR)", "Remarks"
        ];
        
        const rows = [headers.join(",")];

        for (let ord of orders) {
            const row = [
                `"${ord.order_id || ''}"`,
                `"${ord.timestamp || ''}"`,
                `"${ord.symbol || ''}"`,
                `"${ord.exchange || 'NFO'}"`,
                `"${ord.side || ''}"`,
                ord.quantity || 0,
                (ord.price || 0).toFixed(2),
                `"${ord.order_type || 'MARKET'}"`,
                `"${ord.status || 'COMPLETE'}"`,
                ord.target ? Number(ord.target).toFixed(2) : "",
                ord.stop_loss ? Number(ord.stop_loss).toFixed(2) : "",
                `"${(ord.remarks || '').replace(/"/g, '""')}"`
            ];
            rows.push(row.join(","));
        }

        const csvContent = rows.join("\r\n");
        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        
        const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        const link = document.createElement("a");
        link.href = url;
        link.setAttribute("download", `nifty_paper_trade_history_${timestamp}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        showToast("Trade history downloaded as CSV file!", "success");
    } catch (err) {
        showToast("Error generating CSV download: " + err, "error");
    }
}

// ===== TABS SWITCHING & ORDER BOOK =====
function switchTab(tabId) {
    activeTab = tabId;
    
    const btnPositions = document.getElementById("tab-btn-positions");
    const btnOrders = document.getElementById("tab-btn-orders");
    const panePositions = document.getElementById("tab-content-positions");
    const paneOrders = document.getElementById("tab-content-orders");
    
    if (tabId === "positions") {
        if (btnPositions) btnPositions.classList.add("active");
        if (btnOrders) btnOrders.classList.remove("active");
        if (panePositions) panePositions.classList.add("active");
        if (paneOrders) paneOrders.classList.remove("active");
    } else {
        if (btnPositions) btnPositions.classList.remove("active");
        if (btnOrders) btnOrders.classList.add("active");
        if (panePositions) panePositions.classList.remove("active");
        if (paneOrders) paneOrders.classList.add("active");
        fetchOrderHistory();
    }
}

function refreshCurrentTab() {
    if (activeTab === "orders") {
        fetchOrderHistory();
        showToast("Refreshed order history.", "info");
    } else {
        showToast("Positions live stream is active.", "info");
    }
}

async function fetchOrderHistory() {
    const target = document.getElementById("orders-target");
    if (!target) return;
    
    try {
        const res = await fetch("/api/orders");
        const data = await res.json();
        const orders = data.orders || [];
        
        if (orders.length === 0) {
            target.innerHTML = `<tr><td colspan="9" style="padding:24px; text-align:center; color:#64748b;">No trade history recorded yet</td></tr>`;
            return;
        }
        
        let html = "";
        for (let ord of orders) {
            const sideClass = ord.side === "BUY" ? "badge-buy" : "badge-sell";
            
            const tgtText = ord.target && ord.target > 0 
                ? `<span class="badge-target">🎯 ₹${Number(ord.target).toFixed(2)}</span>` 
                : `<span class="badge-notset">--</span>`;
                
            const slText = ord.stop_loss && ord.stop_loss > 0 
                ? `<span class="badge-sl">🛑 ₹${Number(ord.stop_loss).toFixed(2)}</span>` 
                : `<span class="badge-notset">--</span>`;

            let remarksBadge = `<span class="badge-status badge-complete">${ord.status || 'COMPLETE'}</span>`;
            if (ord.remarks && ord.remarks.includes("TARGET_HIT")) {
                remarksBadge = `<span class="badge-status" style="background:rgba(16,185,129,0.2); color:#10b981; border:1px solid #10b981;">🎯 TARGET HIT</span>`;
            } else if (ord.remarks && ord.remarks.includes("STOP_LOSS_HIT")) {
                remarksBadge = `<span class="badge-status" style="background:rgba(244,63,94,0.2); color:#f43f5e; border:1px solid #f43f5e;">🛑 SL HIT</span>`;
            }

            html += `<tr>
                <td style="font-family:var(--font-mono); color:var(--text-muted); font-size:12px;">${ord.order_id || '--'}</td>
                <td style="color:var(--text-secondary); font-size:12px;">${ord.timestamp || '--'}</td>
                <td style="font-weight:600; color:#38bdf8;">${ord.symbol}</td>
                <td><span class="${sideClass}">${ord.side}</span></td>
                <td>${ord.quantity}</td>
                <td style="font-weight:600;">₹ ${(ord.price || 0).toFixed(2)}</td>
                <td>${tgtText}</td>
                <td>${slText}</td>
                <td>${remarksBadge}</td>
            </tr>`;
        }
        target.innerHTML = html;
    } catch (e) {
        target.innerHTML = `<tr><td colspan="9" style="padding:20px; text-align:center; color:#f43f5e;">Failed to load order history: ${e}</td></tr>`;
    }
}
