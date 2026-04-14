import json
import os

DATA_DIR = "data"

def names_file(list_name: str) -> str:
    return os.path.join(DATA_DIR, f"names-{list_name}.txt")

def state_file(list_name: str) -> str:
    return os.path.join(DATA_DIR, f"roster_state_{list_name}.json")

def load_names(list_name: str) -> list:
    path = names_file(list_name)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        names = []
        for line in f:
            # strip comments and whitespace
            entry = line.split("#")[0].strip()
            if entry:
                names.append(entry)
        return names

def load_state(list_name: str) -> dict:
    path = state_file(list_name)
    if not os.path.exists(path):
        return {"current_index": 0}
    with open(path, "r") as f:
        content = f.read().strip()
        if not content:
            return {"current_index": 0}
        return json.loads(content)

def save_state(list_name: str, state: dict):
    with open(state_file(list_name), "w") as f:
        json.dump(state, f)

def get_current(list_name: str) -> tuple:
    names = load_names(list_name)
    if not names:
        return None, 0, 0
    state = load_state(list_name)
    index = state["current_index"] % len(names)
    return names[index], index, len(names)

def advance(list_name: str) -> tuple:
    names = load_names(list_name)
    if not names:
        return None, 0, 0
    state = load_state(list_name)
    next_index = (state["current_index"] + 1) % len(names)
    save_state(list_name, {"current_index": next_index})
    return names[next_index], next_index, len(names)