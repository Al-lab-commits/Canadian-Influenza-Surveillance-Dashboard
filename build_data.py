#!/usr/bin/env python3
"""Ingest historical RVDSS public CSVs -> SQLite -> SQL-driven Plotly JSON.
Requires Python 3.9+, no pip dependencies. Internet required to refresh public source.
"""
import csv, hashlib, io, json, sqlite3, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
DATA.mkdir(exist_ok=True)
DB=DATA/'influenza_surveillance.sqlite'
REPO='https://raw.githubusercontent.com/dajmcdon/rvdss-canada/main/data'
SEASONS=[f'{y}_{y+1}' for y in range(2016,2026)]
GEO={('nation','ca'):('Canada','national'),('region','on'):('ON','regional'),('region','qc'):('QC','regional'),('region','bc'):('BC','regional')}
for code in ['nl','pe','ns','nb','mb','sk','ab','yt','nt','nu']:
    GEO[('lab',code)]=(code.upper(),'laboratory summary')
INDICATORS={
  'fluah1':'fluah1n1pdm09_positive_tests','fluah3':'fluah3_positive_tests',
  'fluauns':'fluauns_positive_tests','flua':'flua_positive_tests',
  'flub':'flub_positive_tests','flu':'flu_positive_tests',
  'rsv':'rsv_positive_tests','sarscov2':'sarscov2_positive_tests',
  'hpiv':'hpiv_positive_tests','adv':'adv_positive_tests',
  'hmpv':'hmpv_positive_tests','evrv':'evrv_positive_tests','hcov':'hcov_positive_tests'
}
def num(v):
    if v is None or str(v).strip().upper() in ('','NA','N/A','NULL'): return None
    try: return float(v)
    except (ValueError,TypeError): return None

def values(row,k):
    if k=='flu':
        p=num(row.get('flu_positive_tests'))
        if p is None:
            a=num(row.get('flua_positive_tests')); b=num(row.get('flub_positive_tests'))
            p=a+b if a is not None and b is not None else None
    else: p=num(row.get(INDICATORS[k]))
    tests=num(row.get('flu_tests')) if k.startswith('flu') else num(row.get(k+'_tests'))
    return p,tests

def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'CanadianInfluenzaPortfolio/1.0 (public research data)'})
    with urllib.request.urlopen(req,timeout=90) as f: return f.read()

def ingest(conn,season):
    url=f'{REPO}/season_{season}/respiratory_detections.csv'
    try:
        raw=get(url); sha=hashlib.sha256(raw).hexdigest()
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        latest={}; count=0
        for row in reader:
            count+=1
            geo=GEO.get((row.get('geo_type','').strip().lower(),row.get('geo_value','').strip().lower()))
            if not geo: continue
            date=row.get('time_value','')
            if len(date)!=10 or date[4]!='-' or date[7]!='-': continue
            key=(date,geo[0]); issue=row.get('issue') or ''
            if key not in latest or issue>=((latest[key].get('issue')) or ''):latest[key]=row
        conn.execute('DELETE FROM weekly_surveillance WHERE season=?',(season,))
        conn.execute('DELETE FROM validation_issues WHERE season=?',(season,))
        # Insert batch first to satisfy foreign key. The source rows remain traceable to URL + SHA.
        conn.execute('INSERT OR REPLACE INTO source_batches VALUES (?,?,?,?,?,?,?,?)',
                     (season,url,datetime.now(timezone.utc).isoformat(),sha,count,len(latest),'loaded',None))
        inserted=0; issues=0
        for (date,g),row in latest.items():
            src=(row.get('geo_type','').strip().lower(),row.get('geo_value','').strip().lower())
            geotype=GEO[src][1]
            epi=num(row.get('epiweek')); week=int(epi)%100 if epi is not None else None
            for k in INDICATORS:
                positive,tests=values(row,k)
                if positive is None and tests is None: continue
                if (positive is not None and positive<0) or (tests is not None and tests<0):
                    conn.execute('INSERT INTO validation_issues(season,week_date,geography,indicator,issue_code,detail) VALUES(?,?,?,?,?,?)',
                          (season,date,g,k,'NEGATIVE_VALUE',f'positive={positive}; tests={tests}'))
                    issues+=1;continue
                if positive is not None and tests is not None and positive>tests:
                    conn.execute('INSERT INTO validation_issues(season,week_date,geography,indicator,issue_code,detail) VALUES(?,?,?,?,?,?)',
                          (season,date,g,k,'POSITIVE_GT_TESTS',f'positive={positive}; tests={tests}'))
                    issues+=1
                    # Retain source value for audit; dashboard excludes invalid rate values.
                conn.execute('''INSERT OR REPLACE INTO weekly_surveillance
                (season,week_date,epiweek,geography,geography_source,indicator,positive_tests,tests_performed,source_issue,source_url)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',(season,date,week,g,geotype,k,positive,tests,row.get('issue'),url))
                inserted+=1
        conn.commit()
        print(f'{season}: {count} source rows, {len(latest)} geography-weeks, {inserted} indicators, {issues} flags')
    except Exception as exc:
        conn.rollback()
        conn.execute('INSERT OR REPLACE INTO source_batches VALUES (?,?,?,?,?,?,?,?)',
                     (season,url,None,None,0,0,'failed',str(exc)[:500]))
        conn.commit()
        print(f'{season}: FAILED: {exc}',file=sys.stderr)

def export(conn):
    # SQL is the reporting interface. Export ONLY validated, record-level observations.
    query='''SELECT season,week_date,epiweek,geography,geography_source,indicator,
    positive_tests,tests_performed FROM v_weekly_reporting
    ORDER BY season,week_date,geography,indicator'''
    data={}; dropped=0
    for season,date,week,geo,gtype,virus,p,t in conn.execute(query):
        key=(season,date,geo)
        if key not in data:data[key]={'season':season,'date':date,'week':week,'geo':geo,'geography_source':gtype,'issue':'SQL validated','vals':{}}
        # preserve missing observations, and do not display impossible positivity
        if p is not None and t is not None and p>t:
            p=None;dropped+=1
        data[key]['vals'][virus]={'positive':p,'tests':t}
    payload={
        'source':'SQLite v_weekly_reporting generated from historical PHAC-derived archive',
        'generated_utc':datetime.now(timezone.utc).isoformat(),
        'records':list(data.values()),
        'batches':[{'season':s,'rows':n,'error':m if st=='failed' else ''} for s,n,st,m in conn.execute('SELECT season,retained_observations,status,message FROM source_batches ORDER BY season')],
        'validation_flags':conn.execute('SELECT COUNT(*) FROM validation_issues').fetchone()[0],
        'excluded_impossible_rates':dropped
    }
    (DATA/'dashboard_rows.json').write_text(json.dumps(payload,separators=(',',':')),encoding='utf-8')
    with (DATA/'season_summary.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.writer(handle)
        writer.writerow(['season','geography','geography_source','indicator','positive_tests','tests_performed','reported_weeks','positivity_pct'])
        writer.writerows(conn.execute('SELECT * FROM v_season_reporting ORDER BY season,geography,indicator'))
    # Optional local province boundary file for reliable map rendering
    url='https://raw.githubusercontent.com/codeforgermany/click_that_hood/main/public/data/canada.geojson'
    try:
        raw=get(url); g=json.loads(raw)
        if g.get('type')!='FeatureCollection' or len(g.get('features',[]))<13:raise ValueError('Unexpected boundary data')
        (DATA/'canada_provinces.geojson').write_bytes(raw)
        print('Province boundaries saved locally')
    except Exception as exc:print('Boundary download skipped:',exc)
    print('Wrote',len(data),'SQL-exported geography-week observations to',DATA/'dashboard_rows.json')

def main():
    with sqlite3.connect(DB) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.executescript((ROOT/'sql'/'schema.sql').read_text())
        for season in SEASONS:ingest(conn,season)
        export(conn)
    print('Database:',DB)

if __name__=='__main__':main()
