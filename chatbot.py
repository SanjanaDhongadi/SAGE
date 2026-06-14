import sys
sys.path.insert(0, "/home/SLA_Project/sage")
from dotenv import load_dotenv
load_dotenv()
from agents.chatbot_agent import run_chatbot
if __name__ == "__main__":
    run_chatbot()
