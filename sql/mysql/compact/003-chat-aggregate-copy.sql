-- WITHDRAWN: this same-schema draft inlined historical evidence and rejected deleted-message orphans.
-- It is not a supported migration entry point. Use copy/24-chat-evidence.sql on distinct admitted ECS schemas.
-- The replacement retains independent audit evidence before attaching optional exact current projections.
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Withdrawn chat aggregate copy; use compact/copy/24-chat-evidence.sql';
