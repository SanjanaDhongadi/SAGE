import openpyxl, json, os

os.makedirs("/home/SLA_Project/sage/data", exist_ok=True)

# remediation_log.xlsx
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["timestamp","pod","trigger_state","breach_prob_before","breach_prob_after",
           "time_to_breach","root_cause","action_taken","reasoning","outcome",
           "recovery_time_seconds","memory_used"])
wb.save("/home/SLA_Project/sage/data/remediation_log.xlsx")

# stress_log.xlsx
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["timestamp","pod","stress_type","duration_seconds","reasoning"])
wb.save("/home/SLA_Project/sage/data/stress_log.xlsx")

# episodic_memory.json
with open("/home/SLA_Project/sage/data/episodic_memory.json", "w") as f:
    json.dump({"episodes": []}, f)

print("Data files initialized.")
