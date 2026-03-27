import re

def simulate_autoselect(desc):
    if not desc:
        return "high (default)"
    
    desc_lower = desc.lower()
    
    # Current broken logic
    current_result = "high (default)"
    if "masters" in desc_lower:
        current_result = "masters"
    elif "high" in desc_lower:
        current_result = "high"
    elif "mid" in desc_lower or "medium" in desc_lower:
        current_result = "mid"
    elif "low" in desc_lower:
        current_result = "low"
        
    # Fixed logic using word boundaries (Regex)
    fixed_result = "high (default)"
    if re.search(r'\bmasters?\b', desc_lower):
        fixed_result = "masters"
    elif re.search(r'\bhigh\b', desc_lower):
        fixed_result = "high"
    elif re.search(r'\b(mid|medium)\b', desc_lower):
        fixed_result = "mid"
    elif re.search(r'\blow\b', desc_lower):
        fixed_result = "low"
        
    return current_result, fixed_result

scenarios = [
    "A repertoire for masters",
    "Following the games of masters",
    "A solid repertoire for middle game", # "mid" is in "middle"
    "Playing slow and positional",        # "low" is in "slow"
    "Highly recommended lines",           # "high" is in "Highly"
    "Low and mid options",
    "Empty description",
]

print(f"{'Description':<40} | {'Current Output':<15} | {'Fixed Output'}")
print("-" * 80)
for s in scenarios:
    curr, fixed = simulate_autoselect(s)
    print(f"{s:<40} | {curr:<15} | {fixed}")
