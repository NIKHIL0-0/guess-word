let token = "";
let matchId = null;
let selectedMatch = null;
let busy = false;
const userMatchNumbers = new Map();

const $ = (selector) => document.querySelector(selector);

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": token, ...(options.headers || {}) },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}

async function refreshCsrfToken() {
  const response = await fetch("/api/auth/csrf", {
    credentials: "same-origin",
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok || !data.csrf_token) throw new Error("Unable to initialize security token.");
  token = data.csrf_token;
}

function showMessage(selector, message, success = false) {
  const element = $(selector);
  element.textContent = message;
  element.className = `message ${success ? "success" : "error"}`;
}

function setBusy(button, value, label) {
  button.disabled = value;
  if (value) {
    button.dataset.label = button.textContent;
    button.textContent = label;
  } else {
    button.textContent = button.dataset.label || button.textContent;
  }
}

async function init() {
  try {
    token = (await api("/api/auth/csrf")).csrf_token;
    const user = (await api("/api/auth/me")).user;
    if ($("#auth")) {
      window.location.href = "/game";
    } else {
      signedIn(user);
    }
  } catch (error) {
    if (error.message !== "Authentication required.") showMessage("#authResult", error.message);
  }
}

function signedIn(user) {
  if (user.role === "admin" && $("#adminDashboard")) {
    $("#who").textContent = `${user.username} · administrator`;
    loadAdminDashboard();
    return;
  }
  if (!$("#game")) {
    window.location.href = user.role === "admin" ? "/admin" : "/game";
    return;
  }
  $("#who").textContent = `${user.username} · ${user.role}`;
  $("#game").hidden = false;
  loadMatches();
  if (user.role === "admin") loadAdminReport();
}

async function login() {
  if (busy) return;
  busy = true;
  const button = $("#loginButton");
  setBusy(button, true, "Signing in...");
  try {
    await refreshCsrfToken();
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: $("#username").value.trim(), password: $("#password").value }),
    });
    signedIn(data.user);
  } catch (error) {
    showMessage("#authResult", error.message);
  } finally {
    busy = false;
    setBusy(button, false);
  }
}

async function register() {
  if (busy) return;
  busy = true;
  const button = $("#registerButton");
  setBusy(button, true, "Creating...");
  try {
    await refreshCsrfToken();
    await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username: $("#username").value.trim(), password: $("#password").value }),
    });
    showMessage("#authResult", "Account created. Signing you in...", true);
    await login();
  } catch (error) {
    showMessage("#authResult", error.message);
  } finally {
    busy = false;
    setBusy(button, false);
  }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } finally { window.location.reload(); }
}

function renderBoard(match) {
  const guesses = match?.guesses || [];
  const feedbackRows = match?.feedback || [];
  $("#board").replaceChildren(...Array.from({ length: 5 }, (_, rowIndex) => {
    const row = document.createElement("div");
    row.className = "row";
    const word = guesses[rowIndex] || "";
    row.append(...Array.from({ length: 5 }, (_, index) => {
      const tile = document.createElement("div");
      const state = feedbackRows[rowIndex]?.[index] || "";
      tile.className = `tile ${word[index] ? "filled" : ""} ${state}`;
      tile.textContent = word[index] || "";
      return tile;
    }));
    return row;
  }));
}

function renderMatches(items) {
  $("#matchCount").textContent = items.length;
  userMatchNumbers.clear();
  items.forEach((match, index) => {
    userMatchNumbers.set(match.match_id, items.length - index);
  });
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No matches yet. Start your first challenge.";
    $("#matches").replaceChildren(empty);
    return;
  }
  $("#matches").replaceChildren(...items.map((match) => {
    const button = document.createElement("button");
    button.className = `match ${match.match_id === matchId ? "selected" : ""}`;
    button.innerHTML = `<span>Match #${userMatchNumbers.get(match.match_id)}</span><small>${match.status}</small>`;
    button.addEventListener("click", () => selectMatch(match.match_id));
    return button;
  }));
}

async function loadMatches() {
  try {
    const data = await api("/api/matches");
    renderMatches(data.matches);
    if (selectedMatch) {
      const current = data.matches.find((item) => item.match_id === matchId);
      if (current) renderBoard(current);
    }
  } catch (error) { showMessage("#result", error.message); }
}

async function selectMatch(id) {
  try {
    const data = await api(`/api/matches/${id}`);
    const matchList = (await api("/api/matches")).matches;
    selectedMatch = data.match; matchId = id;
    renderMatches(matchList);
    const finished = ["won", "lost", "revealed"].includes(data.match.status);
    $("#matchTitle").textContent = `Match #${userMatchNumbers.get(id) || "selected"}`;
    $("#matchHint").textContent = `${data.match.status} · ${data.match.valid_guess_count || 0} guesses`;
    $("#revealButton").hidden = finished;
    $("#guess").disabled = finished;
    renderBoard(data.match);
    if (data.match.status === "won") showMessage("#result", "You won this match!", true);
    else if (data.match.status === "lost") showMessage("#result", "Standard tries are over. Fun mode is active.", true);
    else if (data.match.status === "revealed") showMessage("#result", "This match has been revealed.", true);
  } catch (error) { showMessage("#result", error.message); }
}

async function newMatch() {
  const button = $("#newMatchButton");
  setBusy(button, true, "Creating...");
  try { const data = await api("/api/matches", { method: "POST" }); await selectMatch(data.match.match_id); }
  catch (error) { showMessage("#result", error.message); }
  finally { setBusy(button, false); }
}

async function submitGuess(event) {
  event.preventDefault();
  if (!matchId) return showMessage("#result", "Start or select a match first.");
  const guess = $("#guess").value.trim();
  if (guess.length !== 5) return showMessage("#result", "Enter exactly five letters.");
  try {
    const data = await api(`/api/matches/${matchId}/guess`, { method: "POST", body: JSON.stringify({ guess }) });
    $("#guess").value = "";
    if (data.ranking) {
      const rank = data.ranking;
      $("#ranking").hidden = false;
      $("#ranking").innerHTML = `<strong>You won!</strong><span>Rank <b>${rank.rank}</b> out of ${rank.total_population}</span>`;
      showWinModal(rank);
    }

    function showWinModal(rank) {
      $("#winStats").innerHTML = `<div><span>Your ranking</span><strong>${rank.rank} <small>of ${rank.total_population}</small></strong></div>`;
      $("#winModal").hidden = false;
    }
    showMessage("#result", data.status === "won" ? "You found the word!" : data.status === "fun" ? "Fun mode unlocked." : `Feedback: ${data.feedback.join(", ")}`, data.status === "won");
    await selectMatch(matchId);
  } catch (error) { showMessage("#result", error.message); }
}

async function revealMatch() {
  if (!matchId) return showMessage("#result", "Start or select a match first.");
  try {
    const data = await api(`/api/matches/${matchId}/reveal`, { method: "POST" });
    showMessage("#result", `The answer was ${data.secret.toUpperCase()}.`, true);
    await selectMatch(matchId);
  } catch (error) { showMessage("#result", error.message); }
}

async function loadAdminReport() {
  try {
    const data = await api("/api/admin/reports/daily");
    $("#adminReport").hidden = false;
    $("#adminReport").textContent = `Admin daily report\n${JSON.stringify(data.report, null, 2)}`;
  } catch (_) {}
}

async function loadAdminDashboard() {
  try {
    const [daily, words] = await Promise.all([
      api("/api/admin/reports/daily"),
      api("/api/admin/reports/words"),
    ]);
    const dailyRows = daily.report || [];
    const wordRows = words.report || [];
    $("#dailyRows").replaceChildren(...dailyRows.map((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${row.date}</td><td>${row.users}</td><td>${row.guesses}</td><td>${row.correct_guesses}</td>`;
      return tr;
    }));
    $("#wordRows").replaceChildren(...wordRows.map((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><strong>${row.word}</strong></td><td>${row.matches}</td><td>${row.guesses}</td><td>${row.wins}</td><td>${row.losses}</td><td>${row.win_rate}%</td>`;
      return tr;
    }));
    const totalWords = wordRows.length;
    const totalGuesses = dailyRows.reduce((sum, row) => sum + row.guesses, 0);
    const totalCorrect = dailyRows.reduce((sum, row) => sum + row.correct_guesses, 0);
    $("#adminSummary").innerHTML = `<div class="card stat-card"><span>Words in bank</span><strong>${totalWords}</strong></div><div class="card stat-card"><span>Words tried</span><strong>${totalGuesses}</strong></div><div class="card stat-card"><span>Correct guesses</span><strong>${totalCorrect}</strong></div>`;
  } catch (error) {
    showMessage("#adminResult", error.message);
  }
}

$("#loginButton")?.addEventListener("click", login);
$("#registerButton")?.addEventListener("click", register);
$("#logoutButton")?.addEventListener("click", logout);
$("#newMatchButton")?.addEventListener("click", newMatch);
$("#revealButton")?.addEventListener("click", revealMatch);
$("#guessForm")?.addEventListener("submit", submitGuess);
$("#passwordToggle")?.addEventListener("click", () => {
  const input = $("#password");
  input.type = input.type === "password" ? "text" : "password";
  $("#passwordToggle").textContent = input.type === "password" ? "Show" : "Hide";
});
$("#password")?.addEventListener("keydown", (event) => { if (event.key === "Enter") login(); });
$("#closeWinButton")?.addEventListener("click", () => { $("#winModal").hidden = true; });
$("#continueButton")?.addEventListener("click", () => { $("#winModal").hidden = true; });
$("#winModal")?.addEventListener("click", (event) => {
  if (event.target === $("#winModal")) $("#winModal").hidden = true;
});
document.addEventListener("keydown", (event) => {
  if (!$("#game") || document.activeElement === $("#guess")) return;
  if (event.key === "Enter") $("#guessForm").requestSubmit();
});
init();
