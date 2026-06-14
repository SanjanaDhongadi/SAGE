const prompts = [
  "What is the current critical issue and root cause?",
  "Show recent remediation actions and outcomes.",
  "Which pod has highest breach probability right now?",
  "What changed after the last remediation?",
  "Summarize unresolved incidents from last hour."
];

const promptList = document.getElementById("prompt-list");
const chatInput = document.getElementById("chat-input");
const chatForm = document.getElementById("chat-form");
const chatLog = document.getElementById("chat-log");
const summaryCards = document.getElementById("summary-cards");
const issueStatus = document.getElementById("issue-status");
const refreshBadge = document.getElementById("last-refresh");
const groqKeyInput = document.getElementById("groq-key");
const terminalPanel = document.getElementById("terminal-panel");

let snapshot = {};
let incidents = [];
let chatHistory = [];

function renderPrompts() {
  prompts.forEach((p) => {
    const btn = document.createElement("button");
    btn.className = "prompt-btn";
    btn.textContent = p;
    btn.onclick = () => {
      chatInput.value = p;
      chatInput.focus();
    };
    promptList.appendChild(btn);
  });
}

function renderChat() {
  chatLog.innerHTML = "";
  const last = chatHistory.slice(-6);
  last.forEach((m) => {
    const div = document.createElement("div");
    div.className = `msg ${m.role}`;
    div.textContent = m.text;
    chatLog.appendChild(div);
  });
  chatLog.scrollTop = chatLog.scrollHeight;
}

function pushChat(userText, agentText) {
  chatHistory.push({ role: "user", text: userText });
  chatHistory.push({ role: "agent", text: agentText });
  if (chatHistory.length > 24) chatHistory = chatHistory.slice(-24);
  renderChat();
}

async function loadJson(url, fallback) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

async function loadText(url, fallback = "") {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.text();
  } catch {
    return fallback;
  }
}

function renderSummary() {
  const metrics = snapshot.metrics || {};
  const states = snapshot.sla_states || {};
  const counters = snapshot.counters || {};
  const pods = Object.keys(metrics);
  const critical = Object.values(states).filter((s) => s === "CRITICAL").length;
  const warning = Object.values(states).filter((s) => s === "WARNING").length;
  const avgCpu = pods.length
    ? pods.reduce((a, p) => a + Number(metrics[p].cpu_percent || 0), 0) / pods.length
    : 0;
  const avgMem = pods.length
    ? pods.reduce((a, p) => a + Number(metrics[p].mem_percent || 0), 0) / pods.length
    : 0;

  summaryCards.innerHTML = "";
  const cards = [
    ["Pods", pods.length],
    ["Critical", critical],
    ["Warning", warning],
    ["Avg CPU %", avgCpu.toFixed(1)],
    ["Avg Mem %", avgMem.toFixed(1)],
    ["Remediations", counters.remediation_completed || 0],
    ["Injector Events", counters.injector_events || 0]
  ];
  cards.forEach(([k, v]) => {
    const d = document.createElement("div");
    d.className = "metric";
    d.innerHTML = `<strong>${v}</strong><div>${k}</div>`;
    summaryCards.appendChild(d);
  });
}

function renderIssueStatus() {
  const latest = incidents[incidents.length - 1];
  if (!latest) {
    issueStatus.innerHTML = "No incidents yet.";
    return;
  }
  const resolved = String(latest.outcome || "").toUpperCase() === "SUCCESS";
  issueStatus.innerHTML = `
    <div><strong>Pod:</strong> ${latest.pod || "-"}</div>
    <div><strong>Action:</strong> ${latest.action_taken || "-"}</div>
    <div><strong>Status:</strong> <span class="status-chip ${resolved ? "resolved" : "unresolved"}">${resolved ? "Resolved" : "Unresolved"}</span></div>
  `;
}

function bestPodByBreach() {
  const metrics = snapshot.metrics || {};
  let best = null;
  Object.entries(metrics).forEach(([pod, m]) => {
    const p = Number(m.breach_prob || 0);
    if (!best || p > best.prob) best = { pod, prob: p };
  });
  return best;
}

function localAgentReply(question) {
  const q = String(question || "").toLowerCase();
  if (q === "hi" || q === "hii" || q === "hello" || q === "hey") {
    return "Hi! Ask me about pod names, current status, top breach probability, injector activity, or remediation summary.";
  }
  const states = snapshot.sla_states || {};
  const pods = Object.keys(states);
  const criticalPods = pods.filter((p) => states[p] === "CRITICAL");
  const warningPods = pods.filter((p) => states[p] === "WARNING");
  const latest = incidents[incidents.length - 1];
  const best = bestPodByBreach();

  if (q.includes("name of the pod") || q.includes("pod names") || q.includes("list pod")) {
    return pods.length ? `Current pods (${pods.length}): ${pods.join(", ")}` : "No pod state data yet. Wait for monitor cycle.";
  }
  if (q.includes("critical") || q.includes("warning") || q.includes("status")) {
    return `Current status: critical=${criticalPods.length}, warning=${warningPods.length}, healthy=${Math.max(0, pods.length - criticalPods.length - warningPods.length)}.`;
  }
  if (q.includes("highest") || q.includes("breach")) {
    return best ? `Highest breach probability pod is ${best.pod} (${(best.prob * 100).toFixed(1)}%).` : "No breach probability data available yet.";
  }
  if (q.includes("what is happening") || q.includes("summary") || q.includes("happening")) {
    return [
      `Pods tracked: ${pods.length}.`,
      `Critical: ${criticalPods.length}; Warning: ${warningPods.length}.`,
      best ? `Top risk pod: ${best.pod} (${(best.prob * 100).toFixed(1)}%).` : "Top risk pod: unavailable.",
      latest ? `Last remediation action: ${latest.action_taken || "-"} on ${latest.pod || "-"}.` : "No remediation history yet."
    ].join("\n");
  }
  if (q.includes("injector") || q.includes("stress")) {
    const lastInj = snapshot.last_injector_event || {};
    if (!lastInj.logical_pod) return "Injector has no recent recorded stress event.";
    return `Last injector event: pod=${lastInj.logical_pod}, type=${lastInj.stress_type}, duration=${lastInj.duration_seconds}s.`;
  }
  if (!latest) return "I can answer pod status, highest breach pod, and summary. No incident history yet.";
  return [
    `I understood your question: "${question}".`,
    best ? `Current top risk pod: ${best.pod} (${(best.prob * 100).toFixed(1)}%).` : "Current top risk pod: unavailable.",
    `Latest incident pod: ${latest.pod || "-"}, action=${latest.action_taken || "-"}, outcome=${latest.outcome || "-"}.`
  ].join("\n");
}

function renderTerminalPanel() {
  const events = Array.isArray(snapshot.agent_events) ? snapshot.agent_events : [];
  terminalPanel.innerHTML = "";
  const dedup = new Set();
  events.slice(-40).forEach((e) => {
    const key = `${e.iso}|${e.component}|${e.message}|${JSON.stringify(e.fields || {})}`;
    if (dedup.has(key)) return;
    dedup.add(key);
    const d = document.createElement("div");
    d.className = "event";
    const details = e.fields ? ` ${JSON.stringify(e.fields)}` : "";
    d.textContent = `[${e.iso || "-"}] [${e.component || "agent"}] [${e.level || "INFO"}] ${e.message || ""}${details}`;
    terminalPanel.appendChild(d);
  });
}

async function groqReply(question) {
  const key = groqKeyInput.value.trim();
  if (!key) return localAgentReply(question);
  const payload = {
    model: "llama-3.1-8b-instant",
    messages: [
      { role: "system", content: "You are SAGE ops assistant. Use only provided context and be concise." },
      { role: "user", content: `Context:\n${JSON.stringify({ snapshot, incidents: incidents.slice(-8) }).slice(0, 12000)}\n\nQuestion: ${question}` }
    ],
    temperature: 0
  };
  try {
    const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${key}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      return `Groq request failed (${res.status}). Falling back to local context.\n${localAgentReply(question)}`;
    }
    const data = await res.json();
    return data.choices?.[0]?.message?.content || localAgentReply(question);
  } catch {
    return localAgentReply(question);
  }
}

async function refreshData() {
  snapshot = await loadJson("../data/ui_status.json", {});
  const memoryDoc = await loadJson("../data/episodic_memory.json", { incidents: [] });
  incidents = Array.isArray(memoryDoc.incidents) ? memoryDoc.incidents : [];

  renderSummary();
  renderIssueStatus();
  renderTerminalPanel();
  const ts = snapshot.generated_at ? new Date(snapshot.generated_at).toLocaleTimeString() : new Date().toLocaleTimeString();
  refreshBadge.textContent = `Updated ${ts}`;
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = chatInput.value.trim();
  if (!q) return;
  chatInput.value = "";
  const resp = await groqReply(q);
  pushChat(q, resp);
});

renderPrompts();
pushChat("Sample question", "SAGE dashboard ready. Ask any question about pods, status, breaches, injector, or remediations.");
refreshData();
setInterval(refreshData, 10000);
