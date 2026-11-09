#!/usr/bin/env python3
"""Download the 13 Canadian province/territory polygon boundaries for offline/local rendering."""
import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / 'data' / 'canada_provinces.geojson'
URLS = [
 'https://cdn.jsdelivr.net/gh/codeforgermany/click_that_hood@main/public/data/canada.geojson',
 'https://raw.githubusercontent.com/codeforgermany/click_that_hood/main/public/data/canada.geojson',
]
expected = {'Quebec','Newfoundland and Labrador','British Columbia','Nunavut','Northwest Territories','New Brunswick','Nova Scotia','Saskatchewan','Alberta','Prince Edward Island','Yukon Territory','Manitoba','Ontario'}
errors=[]
for url in URLS:
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'InfluenzaPortfolioMap/1.0'})
        with urllib.request.urlopen(request, timeout=25) as response: raw=response.read()
        geo=json.loads(raw)
        found={f.get('properties',{}).get('name') for f in geo.get('features',[])}
        if geo.get('type')!='FeatureCollection' or not expected.issubset(found):
            raise ValueError('GeoJSON does not contain all 13 required province/territory polygons')
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(raw)
        print('SUCCESS:', OUT)
        print('Verified provincial/territorial boundaries:', len(expected))
        break
    except Exception as exc:
        errors.append(f'{url}: {exc}')
else:
    raise SystemExit('Unable to fetch boundaries. Check internet access.\n'+'\n'.join(errors))
