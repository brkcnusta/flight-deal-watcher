import json
import os

STATE_PATH = os.path.join(os.path.dirname(__file__), "state", "state.json")


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"routes": {}}
    with open(STATE_PATH, "r") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def route_key(route: dict) -> str:
    return f"{route['origin']}-{route['destination']}-{route['trip_type']}"
