"""Date parsing without losing month/year or relative-week context."""
import calendar
import re
import unicodedata
from datetime import datetime, timedelta
from booking_rules import JST, as_jst

def parse_dates(text: str, now: datetime | None = None) -> list[datetime]:
    now = as_jst(now or datetime.now(JST))
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'((?:\d{4}[/年-])?\d{1,2}[/月.-]\d{1,2}日?)\s*(?:[（(]?[月火水木金土日]曜(?:日)?[）)]?|[（(][月火水木金土日][）)])', r'\1', text)
    dates = set()
    def add(y, m, d):
        try: dates.add(JST.localize(datetime(y, m, d)))
        except ValueError: pass
    # Explicit ISO/year dates take precedence over substrings and weekday labels.
    pattern = r'(?<!\d)(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?'
    for m in re.finditer(pattern, text): add(*map(int, m.groups()))
    rest = re.sub(pattern, '', text)
    for word, delta in [('明後日',2),('あさって',2),('明日',1),('今日',0)]:
        if word in rest: dates.add(today + timedelta(days=delta)); rest = rest.replace(word,'')
    weekdays = {'月':0,'火':1,'水':2,'木':3,'金':4,'土':5,'日':6}
    wd_pattern = r'(再来週|来週|今週)?\s*の?\s*([月火水木金土日])曜(?:日)?'
    month_match = re.search(r'(?<!\d)(\d{1,2})月', rest)
    month_context = int(month_match[1]) if month_match else None
    if month_context and not 1 <= month_context <= 12: return sorted(dates)
    year_context = now.year + int(bool(month_context and month_context < now.month))
    for m in re.finditer(wd_pattern, rest):
        week, wd = m.groups(); target = weekdays[wd]
        if month_context and not week:
            for day in range(1,calendar.monthrange(year_context,month_context)[1]+1):
                candidate = JST.localize(datetime(year_context,month_context,day))
                if candidate >= today and candidate.weekday()==target: dates.add(candidate)
        elif week:
            offset = {'今週':0,'来週':7,'再来週':14}[week]
            dates.add(today + timedelta(days=-today.weekday()+target+offset))
        else: dates.add(today + timedelta(days=(target-today.weekday())%7))
    rest = re.sub(wd_pattern,'',rest)
    md_pattern = r'(?<!\d)(\d{1,2})[/月.](\d{1,2})日?'
    spans=[]
    for m in re.finditer(md_pattern,rest):
        month,day=map(int,m.groups()); year=now.year
        try:
            if datetime(year,month,day).date()<today.date(): year+=1
            add(year,month,day); spans.append(m.span())
        except ValueError: pass
    rest=re.sub(md_pattern,'',rest)
    for m in re.finditer(r'(?<!\d)(\d{1,2})日',rest):
        day=int(m[1]); month=month_context or now.month; year=year_context if month_context else now.year
        if not month_context and day<now.day:
            month+=1
            if month==13: year+=1;month=1
        add(year,month,day)
    if month_context and not dates:
        for day in range(1,calendar.monthrange(year_context,month_context)[1]+1):
            candidate=JST.localize(datetime(year_context,month_context,day))
            if candidate>=today: dates.add(candidate)
    return sorted(dates)
