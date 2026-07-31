VALID_TRANSITIONS = {
    'active': ['accepted', 'cancelled'],
    'accepted': ['started', 'cancelled'],
    'started': ['completed'],
    'completed': [],
    'cancelled': []
}

def validate_transition(current_status: str, new_status: str) -> tuple[bool, str]:
    if not current_status or not new_status:
        return False, "Status cannot be empty"
        
    curr = current_status.lower()
    new = new_status.lower()
    
    if curr not in VALID_TRANSITIONS:
        return False, f"Unknown current status: {current_status}"
        
    allowed_next = VALID_TRANSITIONS[curr]
    
    if new not in allowed_next:
        return False, f"Invalid transition from {current_status} to {new_status}. Allowed: {', '.join(allowed_next) if allowed_next else 'None'}"
        
    return True, ""
