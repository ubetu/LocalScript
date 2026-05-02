#!/usr/bin/env python3
import httpx

BASE_URL = "http://localhost:8000"
TIMEOUT = 120

WF_CONTEXT = {
    "wf": {
        "vars": {
            "emails": ["user1@example.com", "user2@example.com", "user3@example.com"]
        }
    }
}


def post(client: httpx.Client, content: str, session_id: str | None = None, wf_context: dict | None = None) -> dict:
    payload = {"content": content}
    if session_id:
        payload["session_id"] = session_id
    if wf_context:
        payload["wf_context"] = wf_context
    resp = client.post("/generate", json=payload)
    resp.raise_for_status()
    return resp.json()


def main():
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        print("Step 1: sending request WITHOUT wf_context")
        r1 = post(client, "Из полученного списка email получи последний.")
        session_id = r1["session_id"]
        print(f"  session_id: {session_id}")
        print(f"  question: {r1.get('question')}")
        print(f"  result: {r1.get('result')}")

        if not r1.get("question"):
            print("FAIL: expected a clarification question, got none")
            return

        print("\nStep 2: sending follow-up WITH wf_context")
        r2 = post(client, "прислал", session_id=session_id, wf_context=WF_CONTEXT)
        print(f"  question: {r2.get('question')}")
        print(f"  result: {r2.get('result')}")

        if r2.get("question"):
            print("\nFAIL: got another question — possible_input did NOT make it into state")
        elif r2.get("result"):
            print("\nPASS: got a result — possible_input was properly applied on resume")
        else:
            print("\nUNKNOWN: no question and no result")


if __name__ == "__main__":
    main()
