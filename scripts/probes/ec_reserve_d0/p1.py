import json,datetime,collections
G=json.load(open('grid.json'))
f=lambda x:datetime.datetime.fromtimestamp(x,datetime.timezone.utc).strftime('%m-%d %H:%M')
ok=[g for g in G if g['l'] is not None and g['s'] is not None]
print("minutes with local+soc+cmd:",len(ok), "of",len(G))
# settled disagreement
dis=[g for g in ok if abs(g['l']-g['cmd'])>=2 and g['age']>600]
print("settled disagreement minutes (|local-cmd|>=2, >600s after last row):",len(dis))
# group into runs
def runs(ms,gap=180):
    r=[];cur=[]
    for g in ms:
        if cur and g['t']-cur[-1]['t']>gap: r.append(cur);cur=[]
        cur.append(g)
    if cur:r.append(cur)
    return r
for r in runs(dis):
    ls=[g['l'] for g in r];ss=[g['s'] for g in r];cs=[g['cmd'] for g in r];cl=[g['c'] for g in r]
    print(f(r[0]['t']),'->',f(r[-1]['t']),len(r),'min | cmd',sorted(set(cs)),'local',min(ls),max(ls),'soc',min(ss),max(ss),'cloud',sorted(set(x for x in cl if x is not None))[:5],'maxdiff(l-soc)',max(l-s for l,s in zip(ls,ss)),'min(l-soc)',min(l-s for l,s in zip(ls,ss)))
# distribution of wobble: local>cmd, soc<=cmd+? 
print("\nBucket settled local-cmd>=2 minutes by (soc - cmd):")
b=collections.Counter()
for g in dis:
    b[(g['s']-g['cmd'])//3*3]+=1
for k in sorted(b): print(k,b[k])
print("\nAll minutes with local>cmd (any age>600) by soc-cmd and local-soc max:")
