import os
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from typing import TypedDict, List
import openpyxl

REMED_LOG = "/home/SLA_Project/sage/data/remediation_log.xlsx"
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0, max_tokens=800)

class ChatState(TypedDict):
    question: str
    log_data: str
    answer: str
    history: List[dict]

def load_log(state: ChatState) -> ChatState:
    if not os.path.exists(REMED_LOG):
        state["log_data"] = "No incidents logged yet."
        return state
    wb = openpyxl.load_workbook(REMED_LOG)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) <= 1:
        state["log_data"] = "No incidents logged yet."
        return state
    headers = rows[0]
    data_rows = rows[1:][-50:]
    lines = [", ".join(str(v) for v in headers)]
    for r in data_rows:
        lines.append(", ".join(str(v) if v is not None else "" for v in r))
    state["log_data"] = "\n".join(lines)
    return state

def answer_question(state: ChatState) -> ChatState:
    history_str = "".join(f"User: {h['user']}\nSAGE: {h['sage']}\n" for h in state["history"][-4:])
    prompt = f"""You are SAGE chatbot. Answer questions about Kubernetes pod incidents from the log.
Be concise.

{history_str}Log:
{state['log_data']}

Question: {state['question']}
Answer:"""
    state["answer"] = llm.invoke(prompt).content.strip()
    return state

def build_chat_graph():
    g = StateGraph(ChatState)
    g.add_node("load_log", load_log)
    g.add_node("answer", answer_question)
    g.set_entry_point("load_log")
    g.add_edge("load_log", "answer")
    g.add_edge("answer", END)
    return g.compile()

def run_chatbot():
    graph = build_chat_graph()
    history = []
    print("\n=== SAGE Chatbot — Ask about pod incidents ===\nType 'exit' to quit\n")
    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if not q:
            continue
        result = graph.invoke({"question": q, "log_data": "", "answer": "", "history": history})
        print(f"SAGE: {result['answer']}\n")
        history.append({"user": q, "sage": result["answer"]})
