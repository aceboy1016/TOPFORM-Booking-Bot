"""Deterministic search preferences shared by chat and waitlist matching."""
import re
import unicodedata
from datetime import datetime, timedelta
from booking_rules import JST, booking_limit
from config import STORE_NAMES


def filters_from(text, previous=None, reference=None):
    text = unicodedata.normalize('NFKC', text)
    result = dict(previous or {})
    if re.search(r'いつでも|何時でも|時間帯.*指定なし|全部の時間', text) and not re.search(r'午前|午後|朝|夜|夕方|以降|まで',text): return {}
    if any(w in text for w in ('午前', '朝', '午後', '夜', '夕方', '以降', 'まで', '早め', '遅め', '遅く', '早く')):
        result = {}
    if '午前' in text or '朝' in text: result['before'] = 12*60
    elif '午後' in text: result['after'] = 12*60
    elif '夜' in text or '夕方' in text: result['after'] = 17*60
    for match in re.finditer(r'(\d{1,2})(?::(\d{2})|時(半|\d{1,2}分)?)\s*(以降|から|まで|以前)', text):
        h, minute, jp, direction = match.groups()
        value = int(h)*60 + (int(minute) if minute else 30 if jp=='半' else int(jp[:-1]) if jp else 0)
        if 0<=value<=24*60:
            result['after' if direction in ('以降','から') else 'through'] = value
    if reference is not None:
        if re.search(r'遅め|遅く',text): result['after'] = reference+30
        if re.search(r'早め|早く',text): result['before'] = reference
    return result


def matching(slots, filters):
    return [s for s in slots if s.hour*60+s.minute >= filters.get('after',0)
            and s.hour*60+s.minute < filters.get('before',1441)
            and s.hour*60+s.minute <= filters.get('through',1440)
            and s.strftime('%H:%M') not in filters.get('exclude',[])]


def filter_label(filters):
    def clock(n): return f'{n//60:02d}:{n%60:02d}'
    return '・'.join(([clock(filters['after'])+'以降'] if 'after' in filters else [])+
                    ([clock(filters['before'])+'より前'] if 'before' in filters else [])+
                    ([clock(filters['through'])+'まで'] if 'through' in filters else []))


def upcoming_days(now=None):
    now=now or datetime.now(JST)
    first=now.replace(hour=0,minute=0,second=0,microsecond=0)
    return [first+timedelta(days=i) for i in range((booking_limit(now).date()-first.date()).days+1)]


def preferred_stores(text):
    mentioned=[(text.find(name.replace('店','')), key) for key,name in STORE_NAMES.items() if name.replace('店','') in text]
    if len(mentioned)==2 and re.search(r'ダメ|だめ|なければ|なかったら|無理|満席なら',text):
        return [key for _,key in sorted(mentioned)]
    return None
