CREATE INDEX FOR (p:Person) ON (p.id);
CREATE INDEX FOR (s:Service) ON (s.id);
CREATE INDEX FOR (m:Message) ON (m.id);
// baseline (keyword RAG):
CALL db.idx.fulltext.createNodeIndex('Message', 'text');
