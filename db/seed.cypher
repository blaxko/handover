// ---------- People ----------
UNWIND [
  {id:'p-tunde',  name:'Tunde Bakare',  aliases:['Tunde','T. Bakare','@tunde','TB']},
  {id:'p-ada',    name:'Ada Okafor',    aliases:['Ada','Ada O.','A. Okafor','@ada']},
  {id:'p-adan',   name:'Ada Nwankwo',   aliases:['Ada','Ada N.','@adan']},
  {id:'p-chidi',  name:'Chidi Eze',     aliases:['Chidi','@chidi']},
  {id:'p-funmi',  name:'Funmi Adeyemi', aliases:['Funmi','@funmi']},
  {id:'p-kemi',   name:'Kemi Lawal',    aliases:['Kemi','@kemi']},
  {id:'p-segun',  name:'Segun Bello',   aliases:['Segun','@segun']},
  {id:'p-musa',   name:'Musa Ibrahim',  aliases:['Musa','@musa']},
  {id:'p-zainab', name:'Zainab Yusuf',  aliases:['Zainab','@zainab']}
] AS p
MERGE (n:Person {id:p.id}) SET n.name = p.name, n.aliases = p.aliases, n.status = 'active';

// ---------- Teams ----------
UNWIND [
  {id:'t-payments', name:'Payments'}, {id:'t-platform', name:'Platform'},
  {id:'t-risk', name:'Risk'}, {id:'t-support', name:'Support'}, {id:'t-mobile', name:'Mobile'}
] AS t
MERGE (n:Team {id:t.id}) SET n.name = t.name;

UNWIND [
  ['p-tunde','t-payments','2025-11-03',null], ['p-ada','t-payments','2026-02-01',null],
  ['p-segun','t-payments','2025-01-10','2026-01-12'], ['p-segun','t-platform','2026-01-12',null],
  ['p-chidi','t-platform','2025-03-01',null], ['p-kemi','t-platform','2025-06-01',null],
  ['p-musa','t-risk','2025-04-01',null], ['p-zainab','t-mobile','2025-08-01',null],
  ['p-adan','t-support','2025-09-01',null], ['p-funmi','t-platform','2024-11-01',null]
] AS r
MATCH (p:Person {id:r[0]}), (t:Team {id:r[1]})
CREATE (p)-[:MEMBER_OF {valid_from:r[2], valid_to:r[3]}]->(t);

// ---------- Services ----------
UNWIND [
  {id:'s-payments', name:'payments-api',  aliases:['payments','payments service','pay-api']},
  {id:'s-ledger',   name:'ledger',        aliases:['ledger service','the ledger']},
  {id:'s-auth',     name:'auth',          aliases:['auth service','login']},
  {id:'s-notify',   name:'notifications', aliases:['notify','notifications service']},
  {id:'s-fraud',    name:'fraud-scorer',  aliases:['fraud','fraud scorer']},
  {id:'s-mobile',   name:'mobile-app',    aliases:['mobile','app']}
] AS s
MERGE (n:Service {id:s.id}) SET n.name = s.name, n.aliases = s.aliases;

UNWIND [
  ['s-mobile','s-payments'], ['s-payments','s-ledger'], ['s-payments','s-auth'],
  ['s-payments','s-fraud'], ['s-notify','s-payments']
] AS d
MATCH (a:Service {id:d[0]}), (b:Service {id:d[1]})
CREATE (a)-[:DEPENDS_ON]->(b);

// ---------- Messages (provenance) ----------
UNWIND [
  {id:'m01', ts:'2025-11-03', ch:'#eng-announce', by:'p-funmi',  about:'s-payments', text:'Welcome TB! Tunde is now the owner of payments-api.'},
  {id:'m02', ts:'2026-01-12', ch:'#eng-announce', by:'p-funmi',  about:'s-ledger',   text:'Segun is moving to Platform; @tunde takes over ledger.'},
  {id:'m00', ts:'2025-01-10', ch:'#eng-announce', by:'p-funmi',  about:'s-ledger',   text:'Segun will own the new ledger service.'},
  {id:'m03', ts:'2026-03-02', ch:'#payments',     by:'p-tunde',  about:'s-payments', text:'payments-api retries are flaky, T. Bakare looking into it.'},
  {id:'m04', ts:'2026-05-20', ch:'#wiki',         by:'p-chidi',  about:'s-payments', text:'Payments owner: Tunde. Ping him for anything on pay-api.'},
  {id:'m05', ts:'2026-07-08', ch:'#payments',     by:'p-ada',    about:'s-ledger',   text:'Paired with Tunde on the settlement refactor in ledger.'},
  {id:'m06', ts:'2026-08-14', ch:'#incidents',    by:'p-ada',    about:'s-payments', text:'Fixed the double-charge bug in payments-api.'},
  {id:'m07', ts:'2026-09-01', ch:'#payments',     by:'p-ada',    about:'s-fraud',    text:'Reviewed fraud-scorer timeouts that were hurting payments-api.'},
  {id:'m08', ts:'2026-09-22', ch:'#risk',         by:'p-musa',   about:'s-fraud',    text:'fraud-scorer v2 rollout done.'},
  {id:'m09', ts:'2026-10-02', ch:'#mobile',       by:'p-zainab', about:'s-mobile',   text:'mobile-app checkout now depends on payments-api v3.'},
  {id:'m10', ts:'2026-10-10', ch:'#support',      by:'p-adan',   about:'s-payments', text:'Ada N. here, refund escalations go to the payments team.'},
  {id:'m11', ts:'2025-03-01', ch:'#eng-announce', by:'p-funmi',  about:'s-auth',     text:'Chidi owns auth going forward.'},
  {id:'m12', ts:'2025-06-01', ch:'#eng-announce', by:'p-funmi',  about:'s-notify',   text:'Kemi owns notifications.'},
  {id:'m13', ts:'2025-04-01', ch:'#eng-announce', by:'p-funmi',  about:'s-fraud',    text:'Musa owns fraud-scorer.'},
  {id:'m14', ts:'2025-08-01', ch:'#eng-announce', by:'p-funmi',  about:'s-mobile',   text:'Zainab owns mobile-app.'}
] AS m
MATCH (a:Person {id:m.by}), (s:Service {id:m.about})
CREATE (a)-[:AUTHORED]->(msg:Message {id:m.id, ts:m.ts, channel:m.ch, text:m.text})-[:ABOUT]->(s);

// ---------- Ownership (bi-temporal, sourced) ----------
UNWIND [
  ['p-segun','s-ledger','2025-01-10','2026-01-12','m00'],
  ['p-tunde','s-ledger','2026-01-12',null,'m02'],
  ['p-tunde','s-payments','2025-11-03',null,'m01'],
  ['p-chidi','s-auth','2025-03-01',null,'m11'],
  ['p-kemi','s-notify','2025-06-01',null,'m12'],
  ['p-musa','s-fraud','2025-04-01',null,'m13'],
  ['p-zainab','s-mobile','2025-08-01',null,'m14']
] AS o
MATCH (p:Person {id:o[0]}), (s:Service {id:o[1]})
CREATE (p)-[:OWNS {valid_from:o[2], valid_to:o[3], source:o[4]}]->(s);

// ---------- Who has actually worked on what ----------
UNWIND [
  ['p-ada','s-payments','2026-08-14'], ['p-ada','s-ledger','2026-07-08'], ['p-ada','s-fraud','2026-09-01'],
  ['p-tunde','s-payments','2026-03-02'], ['p-tunde','s-ledger','2026-07-08'],
  ['p-segun','s-ledger','2025-12-15'], ['p-musa','s-fraud','2026-09-22'],
  ['p-zainab','s-mobile','2026-10-02'], ['p-chidi','s-auth','2026-06-30']
] AS w
MATCH (p:Person {id:w[0]}), (s:Service {id:w[1]})
CREATE (p)-[:WORKED_ON {last:w[2]}]->(s);

// ---------- Tickets ----------
UNWIND [
  {id:'t-101', name:'Refund webhook returns 500', st:'open',   svc:'s-payments', to:'p-tunde', since:'2026-09-30'},
  {id:'t-102', name:'Reconciliation drift in ledger', st:'open', svc:'s-ledger', to:'p-tunde', since:'2026-10-05'},
  {id:'t-103', name:'Retry storm on payments-api', st:'closed', svc:'s-payments', to:'p-tunde', since:'2026-03-02'},
  {id:'t-104', name:'Token refresh race', st:'open',          svc:'s-auth',     to:'p-chidi', since:'2026-10-01'}
] AS t
MATCH (s:Service {id:t.svc}), (p:Person {id:t.to})
CREATE (tk:Ticket {id:t.id, name:t.name, status:t.st})-[:FOR]->(s),
       (tk)-[:ASSIGNED_TO {valid_from:t.since}]->(p);
