"""A reply can replace an unresolved landmark hint with a concrete street address.

The earlier message remains in the evidence history; a verified landmark is never discarded.
"""

def retire_hint(previous, fields, merged, index):
    if ('landmark' in fields or not fields.get('street', {}).get('value')
            or not fields.get('number', {}).get('value')
            or (previous.get('landmark_check') or {}).get('status') == 'resolved'):
        return []
    old = merged.pop('landmark', None)
    return ([{'field': 'landmark', 'from': old['value'], 'to': None, 'message_index': index,
              'reason': 'unresolved_hint_replaced_by_reply_address'}] if old else [])
