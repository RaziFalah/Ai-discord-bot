
import re

def parse_blackjack_situation(content):
    """Parse blackjack situation from user message"""
    content_lower = content.lower()
    
    # Look for player total
    player_total = None
    dealer_card = None
    has_ace = False
    
    # Extract player total (look for patterns like "I have 16", "my hand is 12", etc.)
    player_patterns = [
        r'(?:i have|my hand|player|total)\s*(?:is)?\s*(\d+)',
        r'(\d+)\s*(?:total|hand)',
        r'hand\s*(?:of)?\s*(\d+)'
    ]
    
    for pattern in player_patterns:
        match = re.search(pattern, content_lower)
        if match:
            player_total = int(match.group(1))
            break
    
    # Extract dealer card (look for patterns like "dealer shows 10", "dealer has ace", etc.)
    dealer_patterns = [
        r'dealer\s*(?:shows|has|showing)\s*(?:an?)?\s*(\w+)',
        r'dealer\s*(\w+)',
        r'(?:against|vs)\s*(?:dealer)?\s*(\w+)'
    ]
    
    for pattern in dealer_patterns:
        match = re.search(pattern, content_lower)
        if match:
            dealer_str = match.group(1)
            if dealer_str in ['ace', 'a']:
                dealer_card = 11
            elif dealer_str in ['jack', 'queen', 'king', 'j', 'q', 'k']:
                dealer_card = 10
            elif dealer_str.isdigit():
                dealer_card = int(dealer_str)
            break
    
    # Check for ace in player hand
    if 'ace' in content_lower or ' a ' in content_lower:
        has_ace = True
    
    return player_total, dealer_card, has_ace

def validate_blackjack_situation(player_total, dealer_card):
    """Validate if the blackjack situation is logically possible"""
    if player_total is None or dealer_card is None:
        return False, "Please specify both your hand total and the dealer's card. Example: 'I have 16, dealer shows 10'"
    
    if player_total < 2 or player_total > 21:
        return False, f"Invalid hand total: {player_total}. Hand totals should be between 2 and 21."
    
    if dealer_card < 2 or dealer_card > 11:
        return False, f"Invalid dealer card: {dealer_card}. Dealer cards should be 2-10 or Ace (11)."
    
    return True, ""

def get_basic_strategy_advice(player_total, dealer_card, has_ace=False):
    """Get basic blackjack strategy advice"""
    
    # Check if dealer has blackjack
    if dealer_card == 11:  # Dealer shows Ace
        return "HAND OVER"
    
    # Soft hands (with Ace counted as 11)
    if has_ace and player_total <= 21:
        if player_total >= 19:
            return "STAND"
        elif player_total == 18:
            if dealer_card in [2, 7, 8]:
                return "STAND"
            elif dealer_card in [3, 4, 5, 6]:
                return "DOUBLE DOWN"
            else:
                return "HIT"
        elif player_total == 17:
            if dealer_card in [3, 4, 5, 6]:
                return "DOUBLE DOWN"
            else:
                return "HIT"
        else:  # Soft 16 or less
            if dealer_card in [4, 5, 6]:
                return "DOUBLE DOWN"
            else:
                return "HIT"
    
    # Hard hands
    if player_total >= 17:
        return "STAND"
    elif player_total >= 13:
        if dealer_card <= 6:
            return "STAND"
        else:
            return "HIT"
    elif player_total == 12:
        if dealer_card in [4, 5, 6]:
            return "STAND"
        else:
            return "HIT"
    elif player_total == 11:
        return "DOUBLE DOWN"
    elif player_total == 10:
        if dealer_card <= 9:
            return "DOUBLE DOWN"
        else:
            return "HIT"
    elif player_total == 9:
        if dealer_card in [3, 4, 5, 6]:
            return "DOUBLE DOWN"
        else:
            return "HIT"
    else:  # 8 or less
        return "HIT"
